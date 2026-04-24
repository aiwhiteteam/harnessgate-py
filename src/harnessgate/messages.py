from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Sender:
    id: str
    username: str | None = None
    display_name: str | None = None


@dataclass
class Attachment:
    type: Literal["image", "audio", "video", "file"]
    url: str | None = None
    data: bytes | None = None
    mime_type: str | None = None
    filename: str | None = None


@dataclass
class InboundMessage:
    id: str
    platform: str
    channel_id: str
    sender: Sender
    text: str
    timestamp: float
    chat_type: Literal["direct", "group", "channel", "thread"]
    thread_id: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    app_id: str | None = None
    raw: Any = None


@dataclass
class OutboundMessage:
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    reply_to_id: str | None = None


@dataclass
class MessagePayload:
    text: str
    attachments: list[Attachment] = field(default_factory=list)
