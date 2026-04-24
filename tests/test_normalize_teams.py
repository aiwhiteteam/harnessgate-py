from __future__ import annotations

from datetime import datetime, timezone

from botbuilder.schema import Activity, ChannelAccount, ConversationAccount

from harnessgate.platforms.teams import _normalize_activity, _get_channel_id, _remove_bot_mention


def _make_activity(**overrides) -> Activity:
    defaults = {
        "id": "msg-1",
        "type": "message",
        "text": "hello world",
        "from_property": ChannelAccount(id="user-1", name="Alice"),
        "conversation": ConversationAccount(id="conv-1", conversation_type="personal"),
        "channel_id": "msteams",
        "timestamp": datetime(2023, 11, 14, 12, 0, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return Activity(**defaults)


class TestTeamsNormalize:
    def test_basic_personal_message(self):
        result = _normalize_activity(_make_activity(), "bot-1")
        assert result is not None
        assert result.platform == "teams"
        assert result.channel_id == "conv-1"
        assert result.text == "hello world"
        assert result.sender.id == "user-1"
        assert result.sender.display_name == "Alice"
        assert result.chat_type == "direct"
        assert result.app_id == "bot-1"

    def test_skips_bot_own_messages(self):
        activity = _make_activity(from_property=ChannelAccount(id="bot-1", name="Bot"))
        assert _normalize_activity(activity, "bot-1") is None

    def test_skips_empty_messages(self):
        activity = _make_activity(text="", attachments=None)
        assert _normalize_activity(activity, "bot-1") is None

    def test_group_chat(self):
        activity = _make_activity(
            conversation=ConversationAccount(id="conv-2", conversation_type="groupChat"),
        )
        result = _normalize_activity(activity, "bot-1")
        assert result is not None
        assert result.chat_type == "group"

    def test_channel_conversation(self):
        activity = _make_activity(
            conversation=ConversationAccount(id="conv-3", conversation_type="channel"),
        )
        result = _normalize_activity(activity, "bot-1")
        assert result is not None
        assert result.chat_type == "group"

    def test_removes_bot_mention(self):
        activity = _make_activity(text="<at>MyBot</at> what is the weather?")
        result = _normalize_activity(activity, "bot-1")
        assert result is not None
        assert result.text == "what is the weather?"

    def test_removes_multiple_mentions(self):
        activity = _make_activity(text="<at>Bot1</at> <at>Bot2</at> hello")
        result = _normalize_activity(activity, "bot-1")
        assert result is not None
        assert result.text == "hello"

    def test_timestamp_conversion(self):
        dt = datetime(2023, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
        activity = _make_activity(timestamp=dt)
        result = _normalize_activity(activity, "bot-1")
        assert result is not None
        assert result.timestamp == dt.timestamp()


class TestTeamsHelpers:
    def test_get_channel_id_from_conversation(self):
        activity = _make_activity()
        assert _get_channel_id(activity) == "conv-1"

    def test_get_channel_id_fallback(self):
        activity = _make_activity(conversation=None, channel_id="ch-fallback")
        assert _get_channel_id(activity) == "ch-fallback"

    def test_get_channel_id_unknown(self):
        activity = _make_activity(conversation=None, channel_id=None)
        assert _get_channel_id(activity) == "unknown"

    def test_remove_bot_mention_basic(self):
        assert _remove_bot_mention("<at>MyBot</at> hello") == "hello"

    def test_remove_bot_mention_no_mention(self):
        assert _remove_bot_mention("just text") == "just text"

    def test_remove_bot_mention_empty(self):
        assert _remove_bot_mention("") == ""

    def test_remove_bot_mention_only(self):
        assert _remove_bot_mention("<at>Bot</at>") == ""
