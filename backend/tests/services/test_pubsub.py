"""Tests for Redis pub/sub helpers."""

from __future__ import annotations

from app.services.pubsub import _parse_message


def test_parse_message_accepts_text_payload() -> None:
    assert _parse_message('{"type":"log","data":{"message":"ok"}}') == {
        "type": "log",
        "data": {"message": "ok"},
    }


def test_parse_message_rejects_non_json_payload() -> None:
    assert _parse_message(object()) is None
