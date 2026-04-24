from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from harnessgate import (
    CreateSessionOpts,
    MessageEvent,
    MessagePayload,
    Provider,
    ProviderCapabilities,
    ProviderEvent,
    ProviderSession,
    Sender,
    StatusEvent,
    StreamManager,
)


class MockProvider(Provider):
    def __init__(self, events: list[ProviderEvent]) -> None:
        self._events = events

    @property
    def id(self) -> str:
        return "mock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def create_session(self, opts: CreateSessionOpts) -> ProviderSession:
        return ProviderSession(id="s1", status="idle", created_at=0)

    async def send_message(self, session_id: str, message: MessagePayload) -> None:
        pass

    async def stream(self, session_id: str) -> AsyncIterator[ProviderEvent]:
        for event in self._events:
            yield event

    async def destroy_session(self, session_id: str) -> None:
        pass


class TestStreamManager:
    @pytest.mark.asyncio
    async def test_delivers_events(self):
        manager = StreamManager()
        provider = MockProvider([
            MessageEvent(text="hello"),
            StatusEvent(status="idle"),
        ])

        received: list[ProviderEvent] = []
        manager.ensure_stream("s1", provider, lambda e: received.append(e))

        await asyncio.sleep(0.05)

        assert len(received) >= 1
        assert received[0] == MessageEvent(text="hello")
        manager.stop_all()

    @pytest.mark.asyncio
    async def test_ensure_stream_is_idempotent(self):
        manager = StreamManager()
        provider = MockProvider([])

        manager.ensure_stream("s1", provider, lambda e: None)
        manager.ensure_stream("s1", provider, lambda e: None)

        assert manager.active_count == 1
        manager.stop_all()

    @pytest.mark.asyncio
    async def test_stop_stream_removes_specific(self):
        manager = StreamManager()
        provider = MockProvider([])

        manager.ensure_stream("s1", provider, lambda e: None)
        assert manager.is_active("s1")

        manager.stop_stream("s1")
        assert not manager.is_active("s1")

    @pytest.mark.asyncio
    async def test_stop_all_clears(self):
        manager = StreamManager()
        provider = MockProvider([])

        manager.ensure_stream("s1", provider, lambda e: None)
        manager.ensure_stream("s2", provider, lambda e: None)
        assert manager.active_count == 2

        manager.stop_all()
        assert manager.active_count == 0
