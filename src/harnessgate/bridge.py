from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .messages import InboundMessage, MessagePayload, OutboundMessage
from .platform import ChannelTarget, PlatformAdapter, PlatformContext
from .provider import (
    CreateSessionOpts,
    Provider,
    ProviderEvent,
    ProviderEventListener,
    ResolvedUser,
    UserResolver,
)
from .session import (
    MemorySessionStore,
    SessionEntry,
    SessionStore,
    build_session_key,
)
from .stream import StreamManager

logger = logging.getLogger("harnessgate.bridge")


@dataclass
class BridgeConfig:
    provider: dict[str, Any] = field(default_factory=dict)
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class _ActiveTurn:
    chunks: list[str]
    target: ChannelTarget
    platform_id: str


class Bridge:
    def __init__(self, provider: Provider, config: BridgeConfig | None = None) -> None:
        self._provider = provider
        self._config = config or BridgeConfig()
        self._platforms: dict[str, PlatformAdapter] = {}
        self._session_store: SessionStore = MemorySessionStore()
        self._stream_manager = StreamManager()
        self._active_turns: dict[str, _ActiveTurn] = {}
        self._event_listeners: list[ProviderEventListener] = []
        self._user_resolver: UserResolver | None = None

    def set_session_store(self, store: SessionStore) -> None:
        self._session_store = store

    def add_platform(self, adapter: PlatformAdapter) -> None:
        self._platforms[adapter.id] = adapter

    def on_event(self, listener: ProviderEventListener) -> None:
        self._event_listeners.append(listener)

    def set_user_resolver(self, resolver: UserResolver) -> None:
        self._user_resolver = resolver

    async def connect(self, platform: str, credentials: dict[str, Any]) -> str:
        adapter = self._platforms.get(platform)
        if not adapter:
            raise ValueError(f"No adapter registered for platform: {platform}")

        ctx = PlatformContext(
            on_message=lambda msg: asyncio.get_event_loop().create_task(self._handle_inbound(msg)),
            on_error=lambda err: logger.error("Connection %s error: %s", platform, err),
            config={},
        )
        app_id = await adapter.connect(credentials, ctx)
        logger.info("Connected: %s appId=%s", platform, app_id)
        return app_id

    async def disconnect(self, platform: str, app_id: str) -> None:
        adapter = self._platforms.get(platform)
        if adapter:
            await adapter.disconnect(app_id)
            logger.info("Disconnected: %s appId=%s", platform, app_id)

    async def start(self) -> None:
        logger.info(
            "Starting bridge with provider %r and %d platform(s)",
            self._provider.id,
            len(self._platforms),
        )

        tasks = []
        for pid, adapter in self._platforms.items():
            platform_config = self._config.platforms.get(pid, {})
            ctx = PlatformContext(
                on_message=lambda msg: asyncio.get_event_loop().create_task(self._handle_inbound(msg)),
                on_error=lambda err: logger.error("Platform error: %s", err),
                config=platform_config,
            )
            tasks.append(self._start_platform(pid, adapter, ctx))

        await asyncio.gather(*tasks)
        logger.info("Bridge started")

    async def _start_platform(self, pid: str, adapter: PlatformAdapter, ctx: PlatformContext) -> None:
        try:
            await adapter.start(ctx)
            logger.info("Platform started: %s", pid)
        except Exception as err:
            logger.error("Failed to start platform %s: %s", pid, err)

    async def stop(self) -> None:
        logger.info("Stopping bridge...")
        self._stream_manager.stop_all()
        tasks = [self._stop_platform(a) for a in self._platforms.values()]
        await asyncio.gather(*tasks)
        logger.info("Bridge stopped")

    async def _stop_platform(self, adapter: PlatformAdapter) -> None:
        try:
            await adapter.stop()
        except Exception as err:
            logger.error("Error stopping platform %s: %s", adapter.id, err)

    async def _handle_inbound(self, msg: InboundMessage) -> None:
        resolved_user: ResolvedUser | None = None
        if self._user_resolver:
            try:
                resolved_user = await self._user_resolver(msg.sender, msg.platform, msg)
            except Exception as err:
                logger.error("User resolver error for %s: %s", msg.sender.id, err)
                return
            if not resolved_user:
                logger.debug("User rejected: %s:%s", msg.platform, msg.sender.id)
                return

        user_id = resolved_user.user_id if resolved_user else msg.sender.id
        agent_id = resolved_user.agent_id if resolved_user else None
        session_id = resolved_user.session_id if resolved_user else None
        is_direct = msg.chat_type == "direct"
        is_thread = msg.chat_type == "thread"

        session_key = build_session_key(
            platform=msg.platform,
            chat_type=msg.chat_type,
            channel_id=msg.channel_id,
            user_id=user_id if is_direct else None,
            thread_id=msg.thread_id if is_thread else None,
            agent_id=agent_id,
            session_id=session_id,
            app_id=msg.app_id,
        )
        logger.debug("Inbound from %s: %s", session_key, msg.text[:100])

        entry = await self._session_store.get(session_key)

        if not entry:
            try:
                provider_config = {**self._config.provider}
                if resolved_user and resolved_user.agent_id:
                    provider_config["agentId"] = resolved_user.agent_id
                if resolved_user and resolved_user.environment_id:
                    provider_config["environmentId"] = resolved_user.environment_id

                session = await self._provider.create_session(
                    CreateSessionOpts(
                        provider_config=provider_config,
                        sender=msg.sender,
                        user_id=resolved_user.user_id if resolved_user else None,
                        extra=resolved_user.metadata if resolved_user else None,
                    )
                )

                entry = SessionEntry(
                    key=session_key,
                    provider_session_id=session.id,
                    platform=msg.platform,
                    channel_id=msg.channel_id,
                    thread_id=msg.thread_id,
                    user_id=user_id,
                    app_id=msg.app_id,
                    created_at=time.time(),
                    last_active_at=time.time(),
                )
                await self._session_store.set(session_key, entry)
                logger.info("New session: %s → %s", session_key, session.id)
            except Exception as err:
                logger.error("Failed to create session for %s: %s", session_key, err)
                return

        await self._session_store.touch(session_key)

        cached_entry = entry
        self._stream_manager.ensure_stream(
            entry.provider_session_id,
            self._provider,
            lambda event: asyncio.get_event_loop().create_task(
                self._handle_provider_event(session_key, cached_entry, event)
            ),
        )

        adapter = self._platforms.get(msg.platform)
        if adapter:
            target = ChannelTarget(
                channel_id=msg.channel_id,
                thread_id=msg.thread_id,
                app_id=msg.app_id,
            )
            try:
                await adapter.send_typing(target)
            except Exception:
                pass

        try:
            await self._provider.send_message(
                entry.provider_session_id,
                MessagePayload(text=msg.text, attachments=msg.attachments),
            )
        except Exception as err:
            logger.error("Failed to send message to provider for %s: %s", session_key, err)

    async def _handle_provider_event(
        self,
        session_key: str,
        entry: SessionEntry,
        event: ProviderEvent,
    ) -> None:
        for listener in self._event_listeners:
            try:
                listener(entry.provider_session_id, event)
            except Exception as err:
                logger.error("Event listener error: %s", err)

        adapter = self._platforms.get(entry.platform)
        if not adapter:
            return

        target = ChannelTarget(
            channel_id=entry.channel_id,
            thread_id=entry.thread_id,
            app_id=entry.app_id,
        )

        if event.type == "message":
            turn = self._active_turns.get(session_key)
            if not turn:
                turn = _ActiveTurn(chunks=[], target=target, platform_id=entry.platform)
                self._active_turns[session_key] = turn
            turn.chunks.append(event.text)

        elif event.type == "status":
            if event.status == "idle":
                await self._flush_turn(session_key, adapter, target)
            elif event.status == "running":
                try:
                    await adapter.send_typing(target)
                except Exception:
                    pass

        elif event.type == "error":
            await self._flush_turn(session_key, adapter, target)
            try:
                await adapter.send(target, OutboundMessage(text=f"Error: {event.message}"))
            except Exception:
                pass

    async def _flush_turn(
        self,
        session_key: str,
        adapter: PlatformAdapter,
        target: ChannelTarget,
    ) -> None:
        turn = self._active_turns.pop(session_key, None)
        if not turn or not turn.chunks:
            return

        full_text = "".join(turn.chunks)
        if not full_text.strip():
            return

        max_len = adapter.capabilities.max_text_length
        parts = split_text(full_text, max_len)

        for part in parts:
            try:
                await adapter.send(target, OutboundMessage(text=part))
            except Exception as err:
                logger.error("Failed to send to %s: %s", adapter.id, err)

    def get_session_store(self) -> SessionStore:
        return self._session_store


def split_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break

        split_at = remaining.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len

        parts.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()

    return parts
