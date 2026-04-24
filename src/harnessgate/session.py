from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("harnessgate.session")


def build_session_key(
    *,
    platform: str,
    chat_type: str,
    channel_id: str,
    thread_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    app_id: str | None = None,
) -> str:
    parts = [platform, chat_type, channel_id]
    if app_id:
        parts.append(f"app:{app_id}")
    if thread_id:
        parts.append(f"t:{thread_id}")
    if user_id:
        parts.append(f"u:{user_id}")
    if agent_id:
        parts.append(f"a:{agent_id}")
    if session_id:
        parts.append(f"s:{session_id}")
    return ":".join(parts)


@dataclass
class SessionEntry:
    key: str
    provider_session_id: str
    platform: str
    channel_id: str
    thread_id: str | None = None
    user_id: str | None = None
    app_id: str | None = None
    created_at: float = 0.0
    last_active_at: float = 0.0


class SessionStore(ABC):
    @abstractmethod
    async def get(self, key: str) -> SessionEntry | None: ...

    @abstractmethod
    async def set(self, key: str, entry: SessionEntry) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abstractmethod
    async def touch(self, key: str) -> None: ...


class MemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, SessionEntry] = {}

    async def get(self, key: str) -> SessionEntry | None:
        return self._sessions.get(key)

    async def set(self, key: str, entry: SessionEntry) -> None:
        self._sessions[key] = entry
        logger.debug("Session mapped: %s → %s", key, entry.provider_session_id)

    async def delete(self, key: str) -> bool:
        return self._sessions.pop(key, None) is not None

    async def touch(self, key: str) -> None:
        entry = self._sessions.get(key)
        if entry:
            entry.last_active_at = time.time()
