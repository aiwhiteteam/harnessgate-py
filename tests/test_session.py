from __future__ import annotations

import pytest

from harnessgate import MemorySessionStore, SessionEntry, build_session_key


class TestBuildSessionKey:
    def test_builds_composite_key(self):
        assert build_session_key(platform="telegram", chat_type="direct", channel_id="12345") == "telegram:direct:12345"

    def test_handles_group_chats(self):
        assert build_session_key(platform="discord", chat_type="group", channel_id="guild-99") == "discord:group:guild-99"

    def test_includes_user_id(self):
        assert build_session_key(platform="telegram", chat_type="direct", channel_id="chat-1", user_id="user-42") == "telegram:direct:chat-1:u:user-42"

    def test_includes_thread_id(self):
        assert build_session_key(platform="slack", chat_type="thread", channel_id="ch1", thread_id="ts123") == "slack:thread:ch1:t:ts123"

    def test_includes_agent_and_session_id(self):
        assert build_session_key(platform="web", chat_type="direct", channel_id="c1", user_id="u1", agent_id="agent_coding", session_id="conv_1") == "web:direct:c1:u:u1:a:agent_coding:s:conv_1"

    def test_omits_none_segments(self):
        assert build_session_key(platform="telegram", chat_type="direct", channel_id="12345", user_id=None) == "telegram:direct:12345"

    def test_includes_app_id(self):
        assert build_session_key(platform="telegram", chat_type="direct", channel_id="12345", app_id="123456789") == "telegram:direct:12345:app:123456789"


class TestMemorySessionStore:
    @pytest.fixture
    def store(self):
        return MemorySessionStore()

    def _make_entry(self, **kwargs) -> SessionEntry:
        defaults = {
            "key": "test:direct:1",
            "provider_session_id": "sesn_01",
            "platform": "test",
            "channel_id": "1",
            "created_at": 1000.0,
            "last_active_at": 1000.0,
        }
        defaults.update(kwargs)
        return SessionEntry(**defaults)

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self, store):
        assert await store.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(self, store):
        entry = self._make_entry()
        await store.set(entry.key, entry)
        assert await store.get(entry.key) is entry

    @pytest.mark.asyncio
    async def test_delete_removes_entry(self, store):
        entry = self._make_entry()
        await store.set(entry.key, entry)
        assert await store.delete(entry.key) is True
        assert await store.get(entry.key) is None

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_missing(self, store):
        assert await store.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_touch_updates_last_active_at(self, store):
        entry = self._make_entry(last_active_at=1000.0)
        await store.set(entry.key, entry)
        await store.touch(entry.key)
        updated = await store.get(entry.key)
        assert updated is not None
        assert updated.last_active_at > 1000.0
