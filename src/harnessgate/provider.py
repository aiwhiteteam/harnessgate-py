from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from .messages import InboundMessage, MessagePayload, Sender

SessionStatus = Literal["idle", "running", "rescheduling", "terminated"]

ToolExecutor = Callable[[str, Any], Awaitable[Any]]
"""(tool_name, tool_input) → result. Callback for executing custom tools."""


@dataclass
class ProviderSession:
    id: str
    status: SessionStatus
    created_at: float


@dataclass
class CreateSessionOpts:
    provider_config: dict[str, Any]
    sender: Sender
    user_id: str | None = None
    agent_id: str | None = None
    environment_id: str | None = None
    system_prompt: str | None = None
    extra: dict[str, Any] | None = None


@dataclass
class ResolvedUser:
    user_id: str
    agent_id: str | None = None
    session_id: str | None = None
    environment_id: str | None = None
    metadata: dict[str, Any] | None = None


UserResolver = Callable[
    [Sender, str, InboundMessage],
    Awaitable[ResolvedUser | None],
]


@dataclass
class ProviderCapabilities:
    interrupt: bool = False
    tool_confirmation: bool = False
    custom_tools: bool = False
    thinking: bool = False


@dataclass
class MessageEvent:
    type: Literal["message"] = "message"
    text: str = ""


@dataclass
class ThinkingEvent:
    type: Literal["thinking"] = "thinking"
    text: str = ""


@dataclass
class ToolUseEvent:
    type: Literal["tool_use"] = "tool_use"
    name: str = ""
    input: Any = None


@dataclass
class ToolResultEvent:
    type: Literal["tool_result"] = "tool_result"
    output: str = ""


@dataclass
class StatusEvent:
    type: Literal["status"] = "status"
    status: Literal["running", "idle", "error"] = "idle"
    stop_reason: str | None = None


@dataclass
class CustomToolRequestEvent:
    type: Literal["custom_tool_request"] = "custom_tool_request"
    id: str = ""
    name: str = ""
    input: Any = None


@dataclass
class ErrorEvent:
    type: Literal["error"] = "error"
    message: str = ""


@dataclass
class FileEvent:
    type: Literal["file"] = "file"
    file_id: str = ""
    filename: str | None = None
    mime_type: str | None = None


@dataclass
class RawEvent:
    type: Literal["raw"] = "raw"
    event_type: str = ""
    data: Any = None


ProviderEvent = (
    MessageEvent
    | ThinkingEvent
    | ToolUseEvent
    | ToolResultEvent
    | StatusEvent
    | CustomToolRequestEvent
    | ErrorEvent
    | FileEvent
    | RawEvent
)

ProviderEventListener = Callable[[str, ProviderEvent], None]


class Provider(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def create_session(self, opts: CreateSessionOpts) -> ProviderSession: ...

    @abstractmethod
    async def send_message(self, session_id: str, message: MessagePayload) -> None: ...

    @abstractmethod
    def stream(self, session_id: str) -> AsyncIterator[ProviderEvent]: ...

    @abstractmethod
    async def destroy_session(self, session_id: str) -> None: ...

    async def interrupt(self, session_id: str) -> None:
        raise NotImplementedError

    async def confirm_tool(self, session_id: str, tool_use_id: str, approved: bool) -> None:
        raise NotImplementedError

    async def submit_tool_result(self, session_id: str, tool_use_id: str, result: Any) -> None:
        raise NotImplementedError
