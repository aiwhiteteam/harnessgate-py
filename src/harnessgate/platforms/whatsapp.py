from __future__ import annotations

import json
import logging
import time
from typing import Any

from aiohttp import ClientSession, web

from ..messages import Attachment, InboundMessage, OutboundMessage, Sender
from ..platform import (
    ChannelTarget,
    PlatformAdapter,
    PlatformCapabilities,
    PlatformContext,
    SendResult,
)

logger = logging.getLogger("harnessgate.platforms.whatsapp")

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class _WhatsAppInstance:
    __slots__ = ("phone_number_id", "access_token", "verify_token")

    def __init__(self, phone_number_id: str, access_token: str, verify_token: str) -> None:
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.verify_token = verify_token


class WhatsAppAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._instances: dict[str, _WhatsAppInstance] = {}
        self._runner: web.AppRunner | None = None
        self._on_message: Any = None
        self._http: ClientSession | None = None

    @property
    def id(self) -> str:
        return "whatsapp"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            max_text_length=4096,
            supports_markdown=False,
            supports_threads=False,
            supports_typing_indicator=False,
            supports_attachments=True,
        )

    async def start(self, ctx: PlatformContext) -> None:
        self._on_message = ctx.on_message
        self._http = ClientSession()
        port = int(ctx.config.get("port", 3000))

        # Register instance from config if provided
        if ctx.config.get("phoneNumberId") and ctx.config.get("accessToken") and ctx.config.get("verifyToken"):
            await self.connect(
                {
                    "phoneNumberId": ctx.config["phoneNumberId"],
                    "accessToken": ctx.config["accessToken"],
                    "verifyToken": ctx.config["verifyToken"],
                },
                ctx,
            )

        app = web.Application()
        app.router.add_get("/webhook", self._handle_verification)
        app.router.add_post("/webhook", self._handle_webhook)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", port)
        await site.start()
        logger.info("WhatsApp webhook listening on http://localhost:%d/webhook", port)

    async def connect(self, credentials: dict[str, Any], ctx: PlatformContext) -> str:
        phone_number_id = str(credentials.get("phoneNumberId", ""))
        access_token = str(credentials.get("accessToken", ""))
        verify_token = str(credentials.get("verifyToken", ""))

        if not phone_number_id or not access_token or not verify_token:
            raise ValueError(
                "WhatsApp connect requires phoneNumberId, accessToken, and verifyToken"
            )

        self._instances[phone_number_id] = _WhatsAppInstance(
            phone_number_id, access_token, verify_token
        )
        logger.info("WhatsApp instance registered: phoneNumberId=%s", phone_number_id)
        return phone_number_id

    async def disconnect(self, app_id: str) -> None:
        self._instances.pop(app_id, None)
        logger.info("WhatsApp instance removed: phoneNumberId=%s", app_id)

    def active_connections(self) -> list[str]:
        return list(self._instances.keys())

    async def stop(self) -> None:
        self._instances.clear()
        if self._runner:
            await self._runner.cleanup()
        if self._http:
            await self._http.close()
            self._http = None
        logger.info("WhatsApp adapter stopped")

    async def send(self, target: ChannelTarget, message: OutboundMessage) -> SendResult:
        instance = self._instances.get(target.app_id or "") or next(
            iter(self._instances.values()), None
        )
        if not instance:
            return SendResult(success=False, error="No WhatsApp instance configured")
        if not self._http:
            return SendResult(success=False, error="HTTP client not initialized")

        try:
            url = f"{GRAPH_API_BASE}/{instance.phone_number_id}/messages"
            async with self._http.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {instance.access_token}",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": target.channel_id,
                    "type": "text",
                    "text": {"body": message.text},
                },
            ) as resp:
                if resp.status >= 400:
                    err = await resp.text()
                    logger.error("WhatsApp send failed: %d %s", resp.status, err)
                    return SendResult(success=False, error=f"HTTP {resp.status}: {err}")

                result = await resp.json()
                msg_id = None
                messages = result.get("messages")
                if messages and len(messages) > 0:
                    msg_id = messages[0].get("id")
                return SendResult(success=True, message_id=msg_id)
        except Exception as err:
            logger.error("Failed to send to %s: %s", target.channel_id, err)
            return SendResult(success=False, error=str(err))

    # -- Webhook handlers ------------------------------------------------------

    async def _handle_verification(self, request: web.Request) -> web.Response:
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")

        if mode != "subscribe" or not token or not challenge:
            return web.Response(status=400, text="Missing verification parameters")

        matched = any(i.verify_token == token for i in self._instances.values())
        if not matched:
            logger.warning("Webhook verification failed: unknown verify_token")
            return web.Response(status=403, text="Forbidden")

        logger.info("Webhook verification successful")
        return web.Response(text=challenge)

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.Response(status=200, text="EVENT_RECEIVED")

        if payload.get("object") != "whatsapp_business_account":
            return web.Response(status=200, text="EVENT_RECEIVED")

        try:
            # Determine which instance this is for
            phone_number_id = (
                payload.get("entry", [{}])[0]
                .get("changes", [{}])[0]
                .get("value", {})
                .get("metadata", {})
                .get("phone_number_id", "")
            )

            messages = _normalize_webhook(payload, phone_number_id)
            for msg in messages:
                if self._on_message:
                    self._on_message(msg)
        except Exception as err:
            logger.error("Failed to process webhook: %s", err)

        return web.Response(status=200, text="EVENT_RECEIVED")


def _normalize_webhook(payload: dict[str, Any], app_id: str) -> list[InboundMessage]:
    """Extract all inbound messages from a WhatsApp webhook payload."""
    results: list[InboundMessage] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            wa_messages = value.get("messages")
            if not wa_messages:
                continue

            contacts = {c["wa_id"]: c for c in value.get("contacts", [])}

            for msg in wa_messages:
                sender_id = msg.get("from", "unknown")
                contact = contacts.get(sender_id, {})
                display_name = contact.get("profile", {}).get("name")

                text = _extract_text(msg)
                attachments = _extract_attachments(msg)

                if not text and not attachments:
                    continue

                try:
                    timestamp = int(msg.get("timestamp", 0)) * 1000
                except (ValueError, TypeError):
                    timestamp = int(time.time() * 1000)

                results.append(
                    InboundMessage(
                        id=msg.get("id", ""),
                        platform="whatsapp",
                        channel_id=sender_id,
                        sender=Sender(id=sender_id, display_name=display_name),
                        text=text or "",
                        attachments=attachments if attachments else [],
                        timestamp=timestamp,
                        chat_type="direct",
                        app_id=app_id,
                        raw=msg,
                    )
                )

    return results


def _extract_text(msg: dict[str, Any]) -> str | None:
    msg_type = msg.get("type")
    if msg_type == "text":
        return msg.get("text", {}).get("body")
    # Captions on media
    for media_type in ("image", "video", "document"):
        media = msg.get(media_type)
        if media and media.get("caption"):
            return media["caption"]
    return None


def _extract_attachments(msg: dict[str, Any]) -> list[Attachment]:
    attachments: list[Attachment] = []
    media_map: list[tuple[str, str]] = [
        ("image", "image"),
        ("video", "video"),
        ("audio", "audio"),
        ("document", "file"),
        ("sticker", "image"),
    ]

    msg_type = msg.get("type")
    for wa_type, att_type in media_map:
        if msg_type == wa_type:
            media = msg.get(wa_type)
            if media:
                attachments.append(
                    Attachment(
                        type=att_type,  # type: ignore[arg-type]
                        url=f"whatsapp://media/{media.get('id', '')}",
                        mime_type=media.get("mime_type"),
                        filename=media.get("filename"),
                    )
                )
    return attachments
