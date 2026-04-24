"""
Claude provider using the Anthropic Python SDK.

Uses client.beta.sessions for managed agent session lifecycle,
matching the event handling pattern from Votrix.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from ..provider import (
    CreateSessionOpts,
    CustomToolRequestEvent,
    ErrorEvent,
    FileEvent,
    MessageEvent,
    MessagePayload,
    Provider,
    ProviderCapabilities,
    ProviderEvent,
    ProviderSession,
    StatusEvent,
    ThinkingEvent,
    ToolExecutor,
    ToolResultEvent,
    ToolUseEvent,
)

logger = logging.getLogger("harnessgate.providers.claude")

_STREAM_TIMEOUT = anthropic.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


class ClaudeProvider(Provider):
    """Provider backed by Anthropic Managed Agents (beta sessions API)."""

    def __init__(self, api_key: str, *, tool_executor: ToolExecutor | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._tool_executor = tool_executor

    @property
    def id(self) -> str:
        return "claude"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(interrupt=True, tool_confirmation=True, custom_tools=True, thinking=True)

    # -- Session lifecycle ----------------------------------------------------

    async def create_session(self, opts: CreateSessionOpts) -> ProviderSession:
        config = opts.provider_config
        agent_id = config.get("agentId")
        environment_id = config.get("environmentId")

        if not agent_id or not environment_id:
            raise ValueError("Claude provider requires agentId and environmentId in provider config")

        metadata: dict[str, str] = {}
        if opts.user_id:
            metadata["userId"] = opts.user_id
        if opts.sender:
            metadata["senderPlatformId"] = opts.sender.id
            if opts.sender.username:
                metadata["senderUsername"] = opts.sender.username
            if opts.sender.display_name:
                metadata["senderDisplayName"] = opts.sender.display_name
        if opts.extra:
            for k, v in opts.extra.items():
                metadata[k] = str(v)

        kwargs: dict[str, Any] = {"agent": agent_id, "environment_id": environment_id}
        if metadata:
            kwargs["metadata"] = metadata

        session = await self._client.beta.sessions.create(**kwargs)

        logger.info("Session created: %s%s", session.id, f" for user {opts.user_id}" if opts.user_id else "")
        return ProviderSession(id=session.id, status="idle", created_at=time.time())

    async def destroy_session(self, session_id: str) -> None:
        try:
            await self._client.beta.sessions.delete(session_id)
            logger.info("Session deleted: %s", session_id)
        except Exception as err:
            logger.warning("Failed to delete session %s: %s", session_id, err)

    # -- Messaging ------------------------------------------------------------

    async def send_message(self, session_id: str, message: MessagePayload) -> None:
        content: list[dict[str, Any]] = [{"type": "text", "text": message.text}]

        await self._client.beta.sessions.events.send(
            session_id,
            events=[{"type": "user.message", "content": content}],
        )
        logger.debug("Message sent to session %s", session_id)

    async def interrupt(self, session_id: str) -> None:
        await self._client.beta.sessions.events.send(
            session_id,
            events=[{"type": "user.interrupt"}],
        )
        logger.info("Session interrupted: %s", session_id)

    # -- Streaming (core event loop) ------------------------------------------

    async def stream(self, session_id: str) -> AsyncIterator[ProviderEvent]:
        """Stream session events using the Anthropic SDK.

        Handles the full event lifecycle including requires_action loops
        for custom tool execution (matching the Votrix pattern).
        """
        pending_tools: dict[str, Any] = {}
        sent_results: set[str] = set()
        mcp_tool_ids: set[str] = set()

        async with await self._client.beta.sessions.events.stream(
            session_id, timeout=_STREAM_TIMEOUT
        ) as event_stream:
            async for event in event_stream:
                logger.debug("[event] %s", event.type)

                match event.type:
                    case "agent.message":
                        for block in event.content:
                            if block.type == "text" and block.text:
                                yield MessageEvent(text=block.text)
                            elif file_id := getattr(block, "file_id", None):
                                yield FileEvent(
                                    file_id=file_id,
                                    filename=getattr(block, "filename", None) or getattr(block, "name", None),
                                    mime_type=getattr(block, "mime_type", None) or getattr(block, "media_type", None),
                                )

                    case "agent.tool_use":
                        yield ToolUseEvent(
                            name=getattr(event, "name", ""),
                            input=getattr(event, "input", {}),
                        )

                    case "agent.tool_result":
                        output = _extract_text_content(getattr(event, "content", ""))
                        yield ToolResultEvent(output=output)

                    case "agent.mcp_tool_use":
                        mcp_tool_ids.add(event.id)
                        yield ToolUseEvent(
                            name=getattr(event, "name", ""),
                            input=getattr(event, "input", {}),
                        )

                    case "agent.mcp_tool_result":
                        output = _extract_text_content(getattr(event, "content", ""))
                        yield ToolResultEvent(output=output)

                    case "agent.custom_tool_use":
                        pending_tools[event.id] = event
                        yield CustomToolRequestEvent(
                            id=event.id,
                            name=event.name,
                            input=event.input,
                        )

                    case "agent.thinking":
                        yield ThinkingEvent()

                    case "session.status_idle":
                        if event.stop_reason.type == "requires_action":
                            result_events = await self._handle_requires_action(
                                session_id, event, pending_tools, sent_results, mcp_tool_ids,
                            )
                            for evt in result_events:
                                yield evt
                            # stream stays open — agent continues
                        else:
                            yield StatusEvent(status="idle")
                            break

                    case "session.error" | "error":
                        error = getattr(event, "error", None)
                        if error:
                            error_type = getattr(error, "type", "unknown")
                            error_msg = getattr(error, "message", str(error))
                            msg = f"{error_type}: {error_msg}"
                        else:
                            msg = str(event)
                        yield ErrorEvent(message=msg)
                        break

                    case _:
                        logger.debug("[event] unhandled: %s", event.type)

    async def _handle_requires_action(
        self,
        session_id: str,
        event: Any,
        pending_tools: dict[str, Any],
        sent_results: set[str],
        mcp_tool_ids: set[str],
    ) -> list[ProviderEvent]:
        """Execute custom tools and send results back, matching Votrix's pattern."""
        events_to_yield: list[ProviderEvent] = []

        # IDs the agent is waiting on that we never received
        missed_ids = [
            eid for eid in event.stop_reason.event_ids
            if eid not in pending_tools and eid not in sent_results and eid not in mcp_tool_ids
        ]
        to_execute = [
            (eid, pending_tools.pop(eid))
            for eid in event.stop_reason.event_ids
            if eid in pending_tools
        ]

        # Send error results for missed tool calls
        if missed_ids:
            error_events = [
                {
                    "type": "user.custom_tool_result",
                    "custom_tool_use_id": eid,
                    "content": [{"type": "text", "text": json.dumps({"error": "Tool call was not received; please retry."})}],
                }
                for eid in missed_ids
            ]
            try:
                await self._client.beta.sessions.events.send(session_id, events=error_events)
                logger.warning("Sent error result for %d missed tool(s): %r", len(missed_ids), missed_ids)
            except Exception as e:
                logger.warning("Failed to send missed tool error results: %s", e)

        if not to_execute:
            return events_to_yield

        # Execute tools if we have an executor
        if self._tool_executor:
            async def _run_one(eid: str, te: Any) -> tuple[str, str, Any]:
                try:
                    return eid, te.name, await self._tool_executor(te.name, te.input)
                except Exception as exc:
                    logger.error("Tool execution error [%s]: %s", te.name, exc)
                    return eid, te.name, {"error": str(exc)}

            tool_results = await asyncio.gather(*[_run_one(eid, te) for eid, te in to_execute])

            results: list[dict[str, Any]] = []
            for eid, _name, result in tool_results:
                sent_results.add(eid)
                result_str = json.dumps(result) if not isinstance(result, str) else result
                events_to_yield.append(ToolResultEvent(output=result_str))
                results.append({
                    "type": "user.custom_tool_result",
                    "custom_tool_use_id": eid,
                    "content": [{"type": "text", "text": result_str}],
                })

            await self._client.beta.sessions.events.send(session_id, events=results)
        else:
            # No executor — send error results so the agent can continue
            error_results: list[dict[str, Any]] = []
            for eid, te in to_execute:
                sent_results.add(eid)
                error_results.append({
                    "type": "user.custom_tool_result",
                    "custom_tool_use_id": eid,
                    "content": [{"type": "text", "text": json.dumps({"error": f"No tool executor configured for '{te.name}'"})}],
                })
                events_to_yield.append(ErrorEvent(message=f"No tool executor for '{te.name}'"))

            await self._client.beta.sessions.events.send(session_id, events=error_results)

        return events_to_yield

    # -- Tool confirmation / results ------------------------------------------

    async def confirm_tool(self, session_id: str, tool_use_id: str, approved: bool) -> None:
        await self._client.beta.sessions.events.send(
            session_id,
            events=[{
                "type": "user.tool_confirmation",
                "tool_use_id": tool_use_id,
                "result": "allow" if approved else "deny",
            }],
        )

    async def submit_tool_result(self, session_id: str, tool_use_id: str, result: Any) -> None:
        await self._client.beta.sessions.events.send(
            session_id,
            events=[{
                "type": "user.custom_tool_result",
                "custom_tool_use_id": tool_use_id,
                "content": [{"type": "text", "text": str(result)}],
            }],
        )


def _extract_text_content(raw_content: Any) -> str:
    """Extract text from SDK content blocks (list of typed objects or plain string)."""
    if isinstance(raw_content, list):
        return "\n".join(
            getattr(b, "text", "") for b in raw_content
            if getattr(b, "type", "") == "text"
        )
    return str(raw_content)
