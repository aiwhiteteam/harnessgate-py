from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from botbuilder.core import TurnContext
from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)
from botbuilder.schema import Activity, ActivityTypes, ConversationReference

from ..messages import InboundMessage, OutboundMessage, Sender
from ..platform import (
    ChannelTarget,
    PlatformAdapter,
    PlatformCapabilities,
    PlatformContext,
    SendResult,
)

logger = logging.getLogger("harnessgate.platforms.teams")


class _TeamsInstance:
    __slots__ = ("app_id", "app_password", "adapter", "conversation_refs")

    def __init__(self, app_id: str, app_password: str, adapter: CloudAdapter) -> None:
        self.app_id = app_id
        self.app_password = app_password
        self.adapter = adapter
        self.conversation_refs: dict[str, ConversationReference] = {}


class TeamsAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._instances: dict[str, _TeamsInstance] = {}
        self._runner: web.AppRunner | None = None
        self._on_message: Any = None

    @property
    def id(self) -> str:
        return "teams"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            max_text_length=28000,
            supports_markdown=True,
            supports_threads=True,
            supports_typing_indicator=True,
            supports_attachments=True,
        )

    async def start(self, ctx: PlatformContext) -> None:
        self._on_message = ctx.on_message
        port = int(ctx.config.get("port", 3978))

        # Register instance from config if provided
        if ctx.config.get("appId") and ctx.config.get("appPassword"):
            await self.connect(
                {
                    "appId": ctx.config["appId"],
                    "appPassword": ctx.config["appPassword"],
                },
                ctx,
            )

        app = web.Application()
        app.router.add_post("/api/messages", self._handle_activity)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", port)
        await site.start()
        logger.info("Teams bot listening on http://localhost:%d/api/messages", port)

    async def connect(self, credentials: dict[str, Any], ctx: PlatformContext) -> str:
        app_id = str(credentials.get("appId", ""))
        app_password = str(credentials.get("appPassword", ""))

        if not app_id or not app_password:
            raise ValueError("Teams connect requires appId and appPassword")

        config = {
            "MicrosoftAppId": app_id,
            "MicrosoftAppPassword": app_password,
            "MicrosoftAppType": "MultiTenant",
        }
        bot_auth = ConfigurationBotFrameworkAuthentication(config)
        adapter = CloudAdapter(bot_auth)

        async def on_error(context: TurnContext, error: Exception) -> None:
            logger.error("Teams adapter error: %s", error)

        adapter.on_turn_error = on_error

        self._instances[app_id] = _TeamsInstance(app_id, app_password, adapter)
        logger.info("Teams instance registered: appId=%s", app_id)
        return app_id

    async def disconnect(self, app_id: str) -> None:
        self._instances.pop(app_id, None)
        logger.info("Teams instance removed: appId=%s", app_id)

    def active_connections(self) -> list[str]:
        return list(self._instances.keys())

    async def stop(self) -> None:
        self._instances.clear()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Teams adapter stopped")

    async def send(self, target: ChannelTarget, message: OutboundMessage) -> SendResult:
        instance = self._instances.get(target.app_id or "") or next(
            iter(self._instances.values()), None
        )
        if not instance:
            return SendResult(success=False, error="No Teams instance configured")

        conv_ref = instance.conversation_refs.get(target.channel_id)
        if not conv_ref:
            return SendResult(
                success=False,
                error=f"No conversation reference for {target.channel_id}",
            )

        sent_id: str | None = None

        async def callback(context: TurnContext) -> None:
            nonlocal sent_id
            response = await context.send_activity(message.text)
            if response:
                sent_id = response.id

        try:
            await instance.adapter.continue_conversation(
                conv_ref, callback, instance.app_id
            )
            return SendResult(success=True, message_id=sent_id)
        except Exception as err:
            logger.error("Failed to send to %s: %s", target.channel_id, err)
            return SendResult(success=False, error=str(err))

    async def send_typing(self, target: ChannelTarget) -> None:
        instance = self._instances.get(target.app_id or "") or next(
            iter(self._instances.values()), None
        )
        if not instance:
            return

        conv_ref = instance.conversation_refs.get(target.channel_id)
        if not conv_ref:
            return

        async def callback(context: TurnContext) -> None:
            typing_activity = Activity(type=ActivityTypes.typing)
            await context.send_activity(typing_activity)

        try:
            await instance.adapter.continue_conversation(
                conv_ref, callback, instance.app_id
            )
        except Exception:
            pass

    # -- Activity handler ------------------------------------------------------

    async def _handle_activity(self, request: web.Request) -> web.Response:
        for instance in self._instances.values():
            try:

                async def process_activity(context: TurnContext) -> None:
                    if context.activity.type == ActivityTypes.message:
                        # Store conversation reference for proactive messaging
                        conv_ref = TurnContext.get_conversation_reference(
                            context.activity
                        )
                        channel_id = _get_channel_id(context.activity)
                        instance.conversation_refs[channel_id] = conv_ref

                        normalized = _normalize_activity(
                            context.activity, instance.app_id
                        )
                        if normalized and self._on_message:
                            self._on_message(normalized)

                response = await instance.adapter.process(request, process_activity)
                return response  # type: ignore[return-value]
            except Exception:
                continue

        return web.Response(status=401, text="Unauthorized")


def _normalize_activity(activity: Activity, app_id: str) -> InboundMessage | None:
    """Convert a Bot Framework Activity to a HarnessGate InboundMessage."""
    # Skip bot's own messages
    if activity.from_property and activity.from_property.id == app_id:
        return None

    text = activity.text or ""
    if not text and not activity.attachments:
        return None

    # Remove @mention of the bot
    clean_text = _remove_bot_mention(text)

    channel_id = _get_channel_id(activity)

    chat_type = "direct"
    if activity.conversation and activity.conversation.conversation_type in (
        "groupChat",
        "channel",
    ):
        chat_type = "group"

    sender_id = "unknown"
    display_name: str | None = None
    if activity.from_property:
        sender_id = activity.from_property.id or "unknown"
        display_name = activity.from_property.name

    timestamp = 0.0
    if activity.timestamp:
        timestamp = activity.timestamp.timestamp()

    return InboundMessage(
        id=activity.id or f"teams_{int(timestamp * 1000)}",
        platform="teams",
        channel_id=channel_id,
        sender=Sender(id=sender_id, display_name=display_name),
        text=clean_text,
        timestamp=timestamp,
        chat_type=chat_type,  # type: ignore[arg-type]
        app_id=app_id,
        raw=activity,
    )


def _get_channel_id(activity: Activity) -> str:
    if activity.conversation:
        return activity.conversation.id or "unknown"
    return activity.channel_id or "unknown"


def _remove_bot_mention(text: str) -> str:
    """Remove Teams @mention tags from message text."""
    import re

    return re.sub(r"<at>.*?</at>\s*", "", text).strip()
