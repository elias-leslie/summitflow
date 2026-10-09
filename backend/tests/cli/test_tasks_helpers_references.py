"""Agent Hub reference-trigger fetches must identify the ST client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cli.commands.tasks_helpers import (
    fetch_phase_triggered_references,
    fetch_triggered_references,
)


def _ok(references: list[dict[str, str]]) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = {"references": references}
    return response


def test_triggered_references_send_client_identity() -> None:
    with (
        patch("cli.lib.credentials.load_credentials", return_value=("client-1", "st-context")),
        patch("httpx.get", return_value=_ok([{"id": "ref-1"}])) as get,
    ):
        refs = fetch_triggered_references("database")

    assert refs == [{"id": "ref-1"}]
    assert get.call_args.kwargs["params"] == {"task_type": "database"}
    assert get.call_args.kwargs["headers"] == {
        "X-Client-Id": "client-1",
        "X-Request-Source": "st-context",
    }


def test_phase_references_return_empty_on_rejection() -> None:
    with (
        patch("cli.lib.credentials.load_credentials", return_value=("client-1", "st-context")),
        patch("httpx.get", return_value=MagicMock(status_code=400)) as get,
    ):
        refs = fetch_phase_triggered_references("implementation")

    assert refs == []
    assert get.call_args.kwargs["params"] == {"phase": "implementation"}
    assert get.call_args.kwargs["headers"]["X-Client-Id"] == "client-1"
