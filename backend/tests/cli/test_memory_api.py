"""Tests for Agent Hub memory API error rendering."""

from __future__ import annotations

from cli.commands.memory_api import _format_error_payload


def test_format_error_payload_prefers_message_details_and_hint() -> None:
    rendered = _format_error_payload(
        {
            "error": "validation_error",
            "message": "Content validation failed",
            "details": [{"message": "Header must start with **Mandate**:"}],
            "hint": "Use exact tier headers.",
        },
        "fallback",
    )

    assert rendered == (
        "Content validation failed | Header must start with **Mandate**: | Use exact tier headers."
    )
