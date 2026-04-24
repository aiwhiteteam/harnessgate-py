from __future__ import annotations

import logging
import time
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from ..messages import Attachment, InboundMessage, OutboundMessage, Sender
from ..platform import (
    ChannelTarget,
    PlatformAdapter,
    PlatformCapabilities,
    PlatformContext,
    SendResult,
)

logger = logging.getLogger("harnessgate.platforms.slack")


class SlackAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._apps: dict[str, AsyncApp] = {}
        self._handlers: dict[str, AsyncSocketModeHandler] = {}

    @property
    def id(self) -> str:
        return "slack"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            max_text_length=4000,
            supports_markdown=True,
            supports_threads=True,
            supports_typing_indicator=False,
            supports_attachments=True,
        )

    async def start(self, ctx: PlatformContext) -> None:
        bot_token = ctx.config.get("botToken")
        app_token = ctx.config.get("appToken")
        if not bot_token or not app_token:
            raise ValueError(
                "Slack adapter requires botToken and appToken in platform config"
            )
        await self.connect({"botToken": bot_token, "appToken": app_token}, ctx)

    async def connect(self, credentials: dict[str, Any], ctx: PlatformContext) -> str:
        bot_token = credentials.get("botToken")
        app_token = credentials.get("appToken")
        if not bot_token or not app_token:
            raise ValueError(
                "Slack connect requires botToken and appToken in credentials"
            )

        app = AsyncApp(token=str(bot_token))

        # Get app identity
        auth = await app.client.auth_test()
        app_id = str(auth.get("bot_id") or auth.get("user_id") or "unknown")

        @app.event("message")
        async def handle_message(event: dict[str, Any], say: Any) -> None:
            # Ignore bot messages
            if event.get("bot_id") or event.get("subtype"):
                return

            normalized = _normalize_message(event, app_id)
            if normalized:
                ctx.on_message(normalized)

        @app.event({"type": "message", "subtype": "message_changed"})
        async def handle_message_changed(event: dict[str, Any], say: Any) -> None:
            pass  # Ignore edits

        handler = AsyncSocketModeHandler(app, str(app_token))
        await handler.start_async()

        self._apps[app_id] = app
        self._handlers[app_id] = handler

        logger.info("Slack bot started (socket mode, appId=%s)", app_id)
        return app_id

    async def disconnect(self, app_id: str) -> None:
        handler = self._handlers.pop(app_id, None)
        self._apps.pop(app_id, None)
        if handler:
            await handler.close_async()
        logger.info("Slack bot stopped: appId=%s", app_id)

    def active_connections(self) -> list[str]:
        return list(self._apps.keys())

    async def stop(self) -> None:
        for app_id in list(self._apps.keys()):
            await self.disconnect(app_id)
        logger.info("Slack adapter stopped")

    async def send(self, target: ChannelTarget, message: OutboundMessage) -> SendResult:
        app = self._apps.get(target.app_id or "") or next(
            iter(self._apps.values()), None
        )
        if not app:
            return SendResult(success=False, error="No app instance available")

        try:
            kwargs: dict[str, Any] = {
                "channel": target.channel_id,
                "text": message.text,
            }
            if target.thread_id:
                kwargs["thread_ts"] = target.thread_id

            result = await app.client.chat_postMessage(**kwargs)
            return SendResult(success=True, message_id=str(result.get("ts", "")))
        except Exception as err:
            logger.error("Failed to send to %s: %s", target.channel_id, err)
            return SendResult(success=False, error=str(err))


def _normalize_message(event: dict[str, Any], app_id: str) -> InboundMessage | None:
    """Convert a Slack message event to a HarnessGate InboundMessage."""
    text = event.get("text", "")
    files = event.get("files", [])
    if not text and not files:
        return None

    channel = event.get("channel", "")
    channel_type = event.get("channel_type", "")
    thread_ts = event.get("thread_ts")
    ts = event.get("ts", "")

    is_direct = channel_type == "im"
    is_thread = bool(thread_ts and thread_ts != ts)

    if is_direct:
        chat_type = "direct"
    elif is_thread:
        chat_type = "thread"
    else:
        chat_type = "group"

    attachments: list[Attachment] = []
    for f in files:
        attachments.append(
            Attachment(
                type="file",
                url=f.get("url_private"),
                filename=f.get("name"),
                mime_type=f.get("mimetype"),
            )
        )

    # Slack ts is a float like "1234567890.123456"
    try:
        timestamp = float(ts)
    except (ValueError, TypeError):
        timestamp = time.time()

    return InboundMessage(
        id=ts,
        platform="slack",
        channel_id=channel,
        thread_id=thread_ts,
        sender=Sender(id=event.get("user", "unknown")),
        text=text,
        timestamp=timestamp,
        chat_type=chat_type,  # type: ignore[arg-type]
        attachments=attachments if attachments else [],
        app_id=app_id,
        raw=event,
    )
