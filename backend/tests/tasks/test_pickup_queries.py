"""Tests for autonomous pickup stage selection."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.tasks.autonomous import pickup_queries


def _patch_stage_dependencies(
    monkeypatch: Any,
    *,
    task: dict[str, Any] | None = None,
    spirit: dict[str, Any] | None = None,
    subtasks: list[dict[str, Any]] | None = None,
    readiness: SimpleNamespace | None = None,
) -> None:
    monkeypatch.setattr(
        pickup_queries.task_store,
        "get_task",
        lambda _task_id: task or {"id": "task-1", "description": "Fix it", "labels": []},
    )
    monkeypatch.setattr(pickup_queries, "get_task_spirit", lambda _task_id: spirit)
    monkeypatch.setattr(pickup_queries, "get_subtasks_for_task", lambda _task_id: subtasks or [])
    monkeypatch.setattr(
        pickup_queries,
        "load_task_execution_readiness",
        lambda _task_id: readiness
        or SimpleNamespace(ready=False, missing_fields=["subtasks"]),
    )
    monkeypatch.setattr(
        pickup_queries,
        "get_second_opinion_entry",
        lambda _spirit: {},
    )


def test_draft_plan_without_subtask_rows_reenters_planning(monkeypatch: Any) -> None:
    _patch_stage_dependencies(
        monkeypatch,
        spirit={"plan_status": "draft", "done_when": ["Tests pass"], "context": {}},
        subtasks=[],
    )

    assert pickup_queries.determine_next_stage("task-1") == "planning"


def test_draft_plan_missing_done_when_reenters_planning(monkeypatch: Any) -> None:
    _patch_stage_dependencies(
        monkeypatch,
        spirit={"plan_status": "draft", "context": {"subtasks": [{"description": "Fix"}]}},
        subtasks=[{"id": "subtask-1", "passes": False}],
        readiness=SimpleNamespace(ready=False, missing_fields=["done_when"]),
    )

    assert pickup_queries.determine_next_stage("task-1") == "planning"
