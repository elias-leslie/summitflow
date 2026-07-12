"""Tests for collision-resistant human-readable storage identifiers."""

from __future__ import annotations

from types import SimpleNamespace

from app.storage import connection


def test_generate_prefixed_id_uses_64_bits_of_uuid_entropy(monkeypatch) -> None:
    monkeypatch.setattr(
        connection.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="0123456789abcdef0123456789abcdef"),
    )

    generated = connection.generate_prefixed_id("task")

    assert generated == "task-0123456789abcdef"
    assert len(generated.removeprefix("task-")) == connection.PREFIXED_ID_HEX_LENGTH
