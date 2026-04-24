from __future__ import annotations

from harnessgate.platforms.slack import _normalize_message


def _make_event(**overrides):
    return {
        "type": "message",
        "text": "hello",
        "user": "U123",
        "channel": "C456",
        "ts": "1700000000.000100",
        **overrides,
    }


class TestSlackNormalize:
    def test_basic_channel_message(self):
        result = _normalize_message(_make_event(), "app-1")
        assert result is not None
        assert result.platform == "slack"
        assert result.channel_id == "C456"
        assert result.text == "hello"
        assert result.sender.id == "U123"
        assert result.chat_type == "group"
        assert result.app_id == "app-1"

    def test_returns_none_for_empty(self):
        assert _normalize_message(_make_event(text="", files=[]), "app-1") is None

    def test_detects_dm(self):
        result = _normalize_message(_make_event(channel_type="im"), "app-1")
        assert result is not None
        assert result.chat_type == "direct"

    def test_detects_thread(self):
        result = _normalize_message(
            _make_event(thread_ts="1699999999.000000", ts="1700000000.000100"),
            "app-1",
        )
        assert result is not None
        assert result.chat_type == "thread"
        assert result.thread_id == "1699999999.000000"

    def test_parent_message_not_thread(self):
        ts = "1700000000.000100"
        result = _normalize_message(_make_event(thread_ts=ts, ts=ts), "app-1")
        assert result is not None
        assert result.chat_type == "group"

    def test_converts_ts_to_float_timestamp(self):
        result = _normalize_message(_make_event(ts="1700000000.000100"), "app-1")
        assert result is not None
        assert result.timestamp == 1700000000.000100

    def test_normalizes_file_attachments(self):
        result = _normalize_message(
            _make_event(files=[
                {"id": "F1", "name": "report.pdf", "mimetype": "application/pdf", "url_private": "https://files.slack.com/report.pdf"},
            ]),
            "app-1",
        )
        assert result is not None
        assert len(result.attachments) == 1
        assert result.attachments[0].type == "file"
        assert result.attachments[0].filename == "report.pdf"
        assert result.attachments[0].url == "https://files.slack.com/report.pdf"

    def test_files_only_no_text(self):
        result = _normalize_message(
            _make_event(text="", files=[{"id": "F1", "name": "a.png", "mimetype": "image/png"}]),
            "app-1",
        )
        assert result is not None
        assert result.text == ""
        assert len(result.attachments) == 1
