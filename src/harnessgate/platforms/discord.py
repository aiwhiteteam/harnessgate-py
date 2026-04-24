from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord

from ..messages import Attachment, InboundMessage, OutboundMessage, Sender
from ..platform import (
    ChannelTarget,
    PlatformAdapter,
    PlatformCapabilities,
    PlatformContext,
    SendResult,
)

logger = logging.getLogger("harnessgate.platforms.discord")


class DiscordAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._clients: dict[str, discord.Client] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def id(self) -> str:
        return "discord"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            max_text_length=2000,
            supports_markdown=True,
            supports_threads=True,
            supports_typing_indicator=True,
            supports_attachments=True,
        )

    async def start(self, ctx: PlatformContext) -> None:
        token = ctx.config.get("token")
        if not token:
            raise ValueError("Discord adapter requires token in platform config")
        await self.connect({"token": token}, ctx)

    async def connect(self, credentials: dict[str, Any], ctx: PlatformContext) -> str:
        token = credentials.get("token")
        if not token:
            raise ValueError("Discord connect requires token in credentials")

        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True

        client = discord.Client(intents=intents)
        ready_event = asyncio.Event()
        app_id = ""

        @client.event
        async def on_ready() -> None:
            nonlocal app_id
            app_id = str(client.user.id) if client.user else "unknown"
            logger.info("Discord bot started: %s (appId=%s)", client.user, app_id)
            ready_event.set()

        @client.event
        async def on_message(message: discord.Message) -> None:
            if message.author.bot:
                return

            normalized = _normalize_message(message, app_id)
            if normalized:
                ctx.on_message(normalized)

        @client.event
        async def on_error(event: str, *args: Any, **kwargs: Any) -> None:
            import sys
            exc = sys.exc_info()[1]
            if exc:
                ctx.on_error(exc)

        task = asyncio.create_task(client.start(str(token)))

        # Wait for the client to be ready so we can get the app_id
        try:
            await asyncio.wait_for(ready_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            task.cancel()
            raise ValueError("Discord client failed to connect within 30 seconds")

        self._clients[app_id] = client
        self._tasks[app_id] = task
        return app_id

    async def disconnect(self, app_id: str) -> None:
        client = self._clients.pop(app_id, None)
        task = self._tasks.pop(app_id, None)
        if client:
            await client.close()
        if task:
            task.cancel()
        logger.info("Discord bot stopped: appId=%s", app_id)

    def active_connections(self) -> list[str]:
        return list(self._clients.keys())

    async def stop(self) -> None:
        for app_id in list(self._clients.keys()):
            await self.disconnect(app_id)
        logger.info("Discord adapter stopped")

    async def send(self, target: ChannelTarget, message: OutboundMessage) -> SendResult:
        client = self._clients.get(target.app_id or "") or next(
            iter(self._clients.values()), None
        )
        if not client:
            return SendResult(success=False, error="No client instance available")

        try:
            channel = client.get_channel(int(target.channel_id))
            if channel is None:
                channel = await client.fetch_channel(int(target.channel_id))

            if not isinstance(channel, discord.abc.Messageable):
                return SendResult(
                    success=False,
                    error=f"Channel {target.channel_id} is not text-based",
                )

            kwargs: dict[str, Any] = {}
            if target.reply_to_id:
                kwargs["reference"] = discord.MessageReference(
                    message_id=int(target.reply_to_id)
                )

            sent = await channel.send(message.text, **kwargs)
            return SendResult(success=True, message_id=str(sent.id))
        except Exception as err:
            logger.error("Failed to send to %s: %s", target.channel_id, err)
            return SendResult(success=False, error=str(err))

    async def send_typing(self, target: ChannelTarget) -> None:
        client = self._clients.get(target.app_id or "") or next(
            iter(self._clients.values()), None
        )
        if not client:
            return
        try:
            channel = client.get_channel(int(target.channel_id))
            if channel is None:
                channel = await client.fetch_channel(int(target.channel_id))
            if isinstance(channel, discord.abc.Messageable):
                await channel.trigger_typing()
        except Exception:
            pass


def _normalize_message(msg: discord.Message, app_id: str) -> InboundMessage | None:
    """Convert a discord.py Message to a HarnessGate InboundMessage."""
    text = msg.content
    if not text and len(msg.attachments) == 0:
        return None

    is_direct = isinstance(msg.channel, discord.DMChannel)
    is_thread = isinstance(msg.channel, discord.Thread)

    if is_direct:
        chat_type = "direct"
    elif is_thread:
        chat_type = "thread"
    else:
        chat_type = "group"

    # For threads, use parent channel as channel_id
    if is_thread and msg.channel.parent_id:
        channel_id = str(msg.channel.parent_id)
        thread_id: str | None = str(msg.channel.id)
    else:
        channel_id = str(msg.channel.id)
        thread_id = None

    attachments: list[Attachment] = []
    for att in msg.attachments:
        att_type: str = "file"
        if att.content_type and att.content_type.startswith("image/"):
            att_type = "image"
        elif att.content_type and att.content_type.startswith("audio/"):
            att_type = "audio"
        elif att.content_type and att.content_type.startswith("video/"):
            att_type = "video"

        attachments.append(
            Attachment(
                type=att_type,  # type: ignore[arg-type]
                url=att.url,
                filename=att.filename,
                mime_type=att.content_type,
            )
        )

    return InboundMessage(
        id=str(msg.id),
        platform="discord",
        channel_id=channel_id,
        thread_id=thread_id,
        sender=Sender(
            id=str(msg.author.id),
            username=msg.author.name,
            display_name=msg.author.display_name,
        ),
        text=text,
        timestamp=time.time(),
        chat_type=chat_type,  # type: ignore[arg-type]
        attachments=attachments if attachments else [],
        app_id=app_id,
        raw=msg,
    )
