"""Tests for task client URL routing."""

from __future__ import annotations

from typing import cast

import httpx

from cli import _client_tasks


class _DummyClient:
    """Minimal client that captures GET calls."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "params": params})
        return self.response


def test_get_task_logs_uses_single_project_prefix() -> None:
    response = httpx.Response(
        200,
        json={"task_id": "task-8297fb88", "entries": [], "count": 0},
        request=httpx.Request("GET", "http://localhost:8001/api/projects/summitflow/tasks/task-8297fb88/logs"),
    )
    dummy_client = _DummyClient(response)

    result = _client_tasks.get_task_logs(
        cast(httpx.Client, dummy_client),
        lambda path: f"http://localhost:8001/api{path}",
        lambda response: response.json(),
        "summitflow",
        "task-8297fb88",
    )

    assert result["count"] == 0
    assert dummy_client.calls == [
        {
            "url": "http://localhost:8001/api/projects/summitflow/tasks/task-8297fb88/logs",
            "params": {"format": "json"},
        }
    ]
