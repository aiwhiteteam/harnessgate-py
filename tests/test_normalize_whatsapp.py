from __future__ import annotations

from harnessgate.platforms.whatsapp import _normalize_webhook


def _make_payload(messages, contacts=None):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "entry-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+1234567890",
                                "phone_number_id": "phone-1",
                            },
                            "contacts": contacts or [],
                            "messages": messages,
                        },
                    }
                ],
            }
        ],
    }


class TestWhatsAppNormalize:
    def test_text_message(self):
        results = _normalize_webhook(
            _make_payload(
                [{"from": "5511999999999", "id": "wamid.1", "timestamp": "1700000000", "type": "text", "text": {"body": "Hello"}}],
                [{"profile": {"name": "Bob"}, "wa_id": "5511999999999"}],
            ),
            "phone-1",
        )
        assert len(results) == 1
        assert results[0].platform == "whatsapp"
        assert results[0].text == "Hello"
        assert results[0].channel_id == "5511999999999"
        assert results[0].sender.id == "5511999999999"
        assert results[0].sender.display_name == "Bob"
        assert results[0].chat_type == "direct"
        assert results[0].timestamp == 1700000000000

    def test_empty_messages(self):
        payload = _make_payload([])
        payload["entry"][0]["changes"][0]["value"]["messages"] = None
        assert _normalize_webhook(payload, "phone-1") == []

    def test_skips_non_messages_field(self):
        payload = _make_payload([])
        payload["entry"][0]["changes"][0]["field"] = "statuses"
        assert _normalize_webhook(payload, "phone-1") == []

    def test_image_with_caption(self):
        results = _normalize_webhook(
            _make_payload([{
                "from": "111", "id": "wamid.2", "timestamp": "1700000000",
                "type": "image",
                "image": {"id": "media-1", "mime_type": "image/jpeg", "caption": "Look"},
            }]),
            "phone-1",
        )
        assert len(results) == 1
        assert results[0].text == "Look"
        assert len(results[0].attachments) == 1
        assert results[0].attachments[0].type == "image"
        assert results[0].attachments[0].url == "whatsapp://media/media-1"

    def test_document(self):
        results = _normalize_webhook(
            _make_payload([{
                "from": "111", "id": "wamid.3", "timestamp": "1700000000",
                "type": "document",
                "document": {"id": "media-2", "mime_type": "application/pdf", "filename": "report.pdf"},
            }]),
            "phone-1",
        )
        assert len(results) == 1
        assert results[0].attachments[0].type == "file"
        assert results[0].attachments[0].filename == "report.pdf"

    def test_audio(self):
        results = _normalize_webhook(
            _make_payload([{
                "from": "111", "id": "wamid.4", "timestamp": "1700000000",
                "type": "audio",
                "audio": {"id": "media-3", "mime_type": "audio/ogg"},
            }]),
            "phone-1",
        )
        assert len(results) == 1
        assert results[0].attachments[0].type == "audio"

    def test_multiple_messages(self):
        results = _normalize_webhook(
            _make_payload([
                {"from": "111", "id": "w1", "timestamp": "1700000000", "type": "text", "text": {"body": "msg1"}},
                {"from": "222", "id": "w2", "timestamp": "1700000001", "type": "text", "text": {"body": "msg2"}},
            ]),
            "phone-1",
        )
        assert len(results) == 2
        assert results[0].text == "msg1"
        assert results[1].text == "msg2"

    def test_skips_location(self):
        results = _normalize_webhook(
            _make_payload([{"from": "111", "id": "w1", "timestamp": "1700000000", "type": "location"}]),
            "phone-1",
        )
        assert len(results) == 0

    def test_missing_contacts(self):
        results = _normalize_webhook(
            _make_payload(
                [{"from": "111", "id": "w1", "timestamp": "1700000000", "type": "text", "text": {"body": "hi"}}],
            ),
            "phone-1",
        )
        assert results[0].sender.display_name is None
