from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from aiogram import Bot, Dispatcher, types as tg_types

from ..messages import InboundMessage, OutboundMessage, Sender
from ..platform import (
    ChannelTarget,
    PlatformAdapter,
    PlatformCapabilities,
    PlatformContext,
    SendResult,
)

logger = logging.getLogger("harnessgate.platforms.telegram")


class TelegramAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._bots: dict[str, Bot] = {}
        self._dispatchers: dict[str, Dispatcher] = {}

    @property
    def id(self) -> str:
        return "telegram"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            max_text_length=4096,
            supports_markdown=True,
            supports_threads=True,
            supports_typing_indicator=True,
            supports_attachments=True,
        )

    async def start(self, ctx: PlatformContext) -> None:
        token = ctx.config.get("botToken")
        if not token:
            raise ValueError("Telegram adapter requires botToken in platform config")
        await self.connect({"botToken": token}, ctx)

    async def connect(self, credentials: dict[str, Any], ctx: PlatformContext) -> str:
        token = credentials.get("botToken")
        if not token:
            raise ValueError("Telegram connect requires botToken in credentials")

        bot = Bot(token=str(token))
        bot_info = await bot.get_me()
        app_id = str(bot_info.id)

        dp = Dispatcher()

        @dp.message()
        async def handle_message(message: tg_types.Message) -> None:
            if not message.text and not message.caption:
                return

            sender = Sender(
                id=str(message.from_user.id) if message.from_user else "unknown",
                username=message.from_user.username if message.from_user else None,
                display_name=message.from_user.full_name if message.from_user else None,
            )

            chat_type: str = "direct"
            if message.chat.type in ("group", "supergroup"):
                chat_type = "group"
            elif message.chat.type == "channel":
                chat_type = "channel"

            thread_id = str(message.message_thread_id) if message.message_thread_id else None
            if thread_id:
                chat_type = "thread"

            msg = InboundMessage(
                id=str(message.message_id),
                platform="telegram",
                channel_id=str(message.chat.id),
                thread_id=thread_id,
                sender=sender,
                text=message.text or message.caption or "",
                timestamp=time.time(),
                chat_type=chat_type,  # type: ignore[arg-type]
                app_id=app_id,
            )
            ctx.on_message(msg)

        self._bots[app_id] = bot
        self._dispatchers[app_id] = dp

        asyncio.create_task(dp.start_polling(bot))

        logger.info("Telegram bot started: @%s (appId=%s)", bot_info.username, app_id)
        return app_id

    async def disconnect(self, app_id: str) -> None:
        dp = self._dispatchers.pop(app_id, None)
        bot = self._bots.pop(app_id, None)
        if dp:
            await dp.stop_polling()
        if bot:
            await bot.session.close()
        logger.info("Telegram bot stopped: appId=%s", app_id)

    def active_connections(self) -> list[str]:
        return list(self._bots.keys())

    async def stop(self) -> None:
        for app_id in list(self._bots.keys()):
            await self.disconnect(app_id)
        logger.info("Telegram adapter stopped")

    async def send(self, target: ChannelTarget, message: OutboundMessage) -> SendResult:
        bot = self._bots.get(target.app_id or "") or next(iter(self._bots.values()), None)
        if not bot:
            return SendResult(success=False, error="No bot instance available")

        try:
            kwargs: dict[str, Any] = {}
            if target.thread_id:
                kwargs["message_thread_id"] = int(target.thread_id)
            if target.reply_to_id:
                kwargs["reply_to_message_id"] = int(target.reply_to_id)

            sent = await bot.send_message(int(target.channel_id), message.text, **kwargs)
            return SendResult(success=True, message_id=str(sent.message_id))
        except Exception as err:
            logger.error("Failed to send to %s: %s", target.channel_id, err)
            return SendResult(success=False, error=str(err))

    async def send_typing(self, target: ChannelTarget) -> None:
        bot = self._bots.get(target.app_id or "") or next(iter(self._bots.values()), None)
        if not bot:
            return
        try:
            await bot.send_chat_action(int(target.channel_id), "typing")
        except Exception:
            pass
