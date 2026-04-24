from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .messages import InboundMessage, OutboundMessage


@dataclass
class ChannelTarget:
    channel_id: str
    thread_id: str | None = None
    reply_to_id: str | None = None
    app_id: str | None = None


@dataclass
class SendResult:
    success: bool
    message_id: str | None = None
    error: str | None = None


@dataclass
class PlatformCapabilities:
    max_text_length: int
    supports_markdown: bool = False
    supports_threads: bool = False
    supports_typing_indicator: bool = False
    supports_attachments: bool = False


@dataclass
class PlatformContext:
    on_message: Callable[[InboundMessage], None]
    on_error: Callable[[Exception], None]
    config: dict[str, Any]


class PlatformAdapter(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> PlatformCapabilities: ...

    @abstractmethod
    async def start(self, ctx: PlatformContext) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, target: ChannelTarget, message: OutboundMessage) -> SendResult: ...

    async def send_typing(self, target: ChannelTarget) -> None:
        pass

    async def connect(self, credentials: dict[str, Any], ctx: PlatformContext) -> str:
        raise NotImplementedError

    async def disconnect(self, app_id: str) -> None:
        raise NotImplementedError

    def active_connections(self) -> list[str]:
        return []
