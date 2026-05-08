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


def test_build_payload_includes_agentic_metadata_when_set() -> None:
    payload = build_payload(
        "Inspect only",
        "portfolio-ai",
        "explorer",
        None,
        "/repo",
        None,
        None,
        "trace-1",
        True,
        True,
        None,
        5000,
        False,
        None,
        parent_session_id="parent-1",
        read_only=True,
    )

    assert payload["execute_tools"] is True
    assert payload["max_turns"] == 5000
    assert payload["working_dir"] == "/repo"
    assert payload["parent_session_id"] == "parent-1"
    assert payload["read_only"] is True
