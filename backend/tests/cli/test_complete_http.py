"""Tests for complete HTTP payload construction."""

from __future__ import annotations

from cli.commands._complete_http import build_payload


def test_build_payload_includes_explicit_false_for_use_memory() -> None:
    payload = build_payload(
        "Lean run",
        "summitflow",
        "persona",
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        1,
        False,
        None,
    )

    assert payload["use_memory"] is False


def test_build_payload_includes_task_type_when_set() -> None:
    payload = build_payload(
        "Lean run",
        "summitflow",
        "persona",
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        "heartbeat",
        1,
        False,
        None,
    )

    assert payload["task_type"] == "heartbeat"
