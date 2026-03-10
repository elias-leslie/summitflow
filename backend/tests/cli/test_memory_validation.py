"""Tests for memory format validation rules."""

from __future__ import annotations

import pytest
import typer

from cli.commands.memory_validation import validate_content_format


def test_validate_content_format_accepts_tier_specific_header() -> None:
    validate_content_format(
        "**Mandate**: Use dt for all quality checks. Never run raw pytest or ruff.",
        "Use dt for checks",
        "mandate",
    )


def test_validate_content_format_rejects_wrong_header_for_tier() -> None:
    with pytest.raises(typer.Exit):
        validate_content_format(
            "**Reference**: Use dt for all quality checks.",
            "Use dt for checks",
            "mandate",
        )


def test_validate_content_format_rejects_conversational_language() -> None:
    with pytest.raises(typer.Exit):
        validate_content_format(
            "**Guardrail**: Please remember to grep before deleting code.",
            "Grep before deletion",
            "guardrail",
        )


def test_validate_content_format_warns_but_allows_long_single_rule(capsys) -> None:
    validate_content_format(
        (
            "**Reference**: Use exact tier headers for memory episodes so retrieval and citation stay precise. "
            "Prefer keeping each rule compact even when a slightly longer explanation is clearer than splitting one rule into multiple entries across fragmented memories and retrieval paths that dilute authority cues."
        ),
        "Use exact tier headers",
        "reference",
    )

    err = capsys.readouterr().err
    assert "prefer 280 or fewer" in err.lower()
