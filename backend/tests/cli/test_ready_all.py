"""Tests for `st ready-all` output classification."""

from __future__ import annotations

import pytest

from cli.commands.tasks_ready_all import list_ready_all


class _DummyClient:
    def __init__(self) -> None:
        self.base_url = "http://test/api"
        self._responses: dict[str, object] = {}
        self._sessions: dict[str, list[dict[str, object]]] = {}

    @staticmethod
    def _global_url(path: str) -> str:
        return f"http://test/api{path}"

    def get(self, url: str) -> object:
        return self._responses[url]

    def list_sessions(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        limit: int = 20,
        page: int = 1,
        agent_slug: str | None = None,
        parent_session_id: str | None = None,
    ) -> list[dict[str, object]]:
        assert status == "active"
        assert limit == 100
        assert page == 1
        assert agent_slug is None
        assert parent_session_id is None
        return list(self._sessions.get(project_id or "", []))


@pytest.fixture
def dummy_client() -> _DummyClient:
    client = _DummyClient()
    client._responses = {
        "http://test/api/projects": [{"id": "agent-hub", "name": "agent-hub"}],
        "http://test/api/projects/agent-hub/tasks/ready?limit=5": {"tasks": [], "total": 0},
        "http://test/api/projects/agent-hub/tasks?status=blocked&limit=5": {"tasks": [], "total": 0},
        "http://test/api/projects/agent-hub/tasks/blocked?limit=5": {"tasks": [], "total": 0},
        "http://test/api/projects/agent-hub/tasks?status=running&limit=100": {
            "tasks": [
                {
                    "id": "task-live",
                    "priority": 1,
                    "task_type": "task",
                    "title": "Live lane task",
                    "execution_mode": "manual",
                    "status": "running",
                },
                {
                    "id": "task-stale",
                    "priority": 1,
                    "task_type": "task",
                    "title": "Stale lane task",
                    "execution_mode": "manual",
                    "status": "running",
                },
            ],
            "total": 2,
        },
        "http://test/api/projects/agent-hub/tasks?status=pending&limit=100": {"tasks": [], "total": 0},
    }
    client._sessions = {
        "agent-hub": [
            {
                "id": "sess-1",
                "external_id": "task-live",
                "current_branch": "task-live/main",
            }
        ]
    }
    return client


def test_ready_all_running_tasks_classifies_as_active_or_stale(
    dummy_client: _DummyClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    list_ready_all(5, dummy_client)

    output = capsys.readouterr().out

    assert "READY-ALL[0 ready, 0 blocked, 1 active, 1 stale across 1 projects]" in output
    assert "agent-hub (0 ready, 1 active, 1 stale)" in output
    assert "~ task-live" in output
    assert "? task-stale" in output
    assert "[stale-running]" in output


def test_ready_all_uses_branch_prefix_when_external_id_missing(
    dummy_client: _DummyClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dummy_client._sessions["agent-hub"] = [
        {
            "id": "sess-2",
            "external_id": None,
            "current_branch": "task-stale/main",
        }
    ]

    list_ready_all(5, dummy_client)

    output = capsys.readouterr().out

    assert "READY-ALL[0 ready, 0 blocked, 1 active, 1 stale across 1 projects]" in output
    assert "~ task-stale" in output
    assert "? task-live" in output
