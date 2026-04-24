from __future__ import annotations

from harnessgate import split_text


class TestSplitText:
    def test_short_text(self):
        assert split_text("hello", 100) == ["hello"]

    def test_text_at_limit(self):
        text = "a" * 50
        assert split_text(text, 50) == [text]

    def test_splits_at_newline(self):
        text = "line one\nline two\nline three"
        parts = split_text(text, 15)
        assert parts[0] == "line one"
        assert len(parts) > 1

    def test_splits_at_space(self):
        text = "word1 word2 word3 word4"
        parts = split_text(text, 12)
        assert parts[0] == "word1 word2"
        assert parts[1] == "word3 word4"

    def test_hard_splits(self):
        text = "a" * 20
        parts = split_text(text, 10)
        assert parts == ["a" * 10, "a" * 10]

    def test_empty_string(self):
        assert split_text("", 100) == [""]

    def test_trims_leading_whitespace(self):
        text = "hello world"
        parts = split_text(text, 6)
        assert parts[0] == "hello"
        assert parts[1] == "world"
