"""Integration test for parallel task execution.

Tests that 2 non-conflicting tasks execute simultaneously via AgentPool.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.agent_pool import AgentPool, FileOverlapDetector


@pytest.fixture
def task_a() -> dict[str, Any]:
    return {
        "id": "task-a",
        "title": "Update frontend styles",
        "files_to_modify": ["frontend/styles.css", "frontend/components/Button.tsx"],
    }


@pytest.fixture
def task_b() -> dict[str, Any]:
    return {
        "id": "task-b",
        "title": "Add backend API",
        "files_to_modify": ["backend/routes.py", "backend/models.py"],
    }


@pytest.fixture
def task_c_conflicts_a() -> dict[str, Any]:
    return {
        "id": "task-c",
        "title": "Refactor button",
        "files_to_modify": ["frontend/components/Button.tsx", "frontend/components/Icon.tsx"],
    }


class TestFileOverlapDetector:
    """Test file overlap detection logic."""

    def test_no_overlap_detected(self, task_a: dict[str, Any], task_b: dict[str, Any]) -> None:
        """Tasks modifying different files should not conflict."""
        detector = FileOverlapDetector()
        detector.register_task_files(task_a["id"], task_a["files_to_modify"])
        has_overlap = detector.has_conflict(task_b["files_to_modify"])
        assert has_overlap is False

    def test_overlap_detected(self, task_a: dict[str, Any], task_c_conflicts_a: dict[str, Any]) -> None:
        """Tasks modifying the same file should conflict."""
        detector = FileOverlapDetector()
        detector.register_task_files(task_a["id"], task_a["files_to_modify"])
        has_overlap = detector.has_conflict(task_c_conflicts_a["files_to_modify"])
        assert has_overlap is True


class TestAgentPool:
    """Test AgentPool parallel execution management."""

    def test_parallel_execution_non_conflicting(
        self, task_a: dict[str, Any], task_b: dict[str, Any]
    ) -> None:
        """Non-conflicting tasks should be allowed to run in parallel."""
        pool = AgentPool(max_concurrent=3)

        pool.enqueue(task_a["id"], "test-project", files_to_modify=task_a["files_to_modify"])
        pool.enqueue(task_b["id"], "test-project", files_to_modify=task_b["files_to_modify"])

        next_task = pool.get_next_safe()
        assert next_task is not None

        next_task2 = pool.get_next_safe()
        assert next_task2 is not None

    def test_conflicting_task_waits(
        self, task_a: dict[str, Any], task_c_conflicts_a: dict[str, Any]
    ) -> None:
        """Conflicting task should wait until first completes."""
        pool = AgentPool(max_concurrent=3)

        pool.enqueue(task_a["id"], "test-project", files_to_modify=task_a["files_to_modify"])
        pool.enqueue(
            task_c_conflicts_a["id"],
            "test-project",
            files_to_modify=task_c_conflicts_a["files_to_modify"],
        )

        next_task = pool.get_next_safe()
        assert next_task is not None
        assert next_task.task_id == task_a["id"]

        conflicting = pool.get_next_safe()
        assert conflicting is None

    def test_pool_size_limit(self, task_a: dict[str, Any], task_b: dict[str, Any]) -> None:
        """Pool should enforce max concurrent limit."""
        pool = AgentPool(max_concurrent=1)

        pool.enqueue(task_a["id"], "test-project", files_to_modify=task_a["files_to_modify"])
        pool.enqueue(task_b["id"], "test-project", files_to_modify=task_b["files_to_modify"])

        next_task = pool.get_next_safe()
        assert next_task is not None

        blocked = pool.get_next_safe()
        assert blocked is None
