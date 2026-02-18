"""Shared fixtures for storage tests."""

from __future__ import annotations

from typing import Any, Generator

import pytest

from app.storage import tasks as task_store
from app.storage.connection import get_connection


@pytest.fixture
def project_id() -> Generator[str, None, None]:
    """Ensure test project exists."""
    project_id = "test-project"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_id, "SummitFlow", "http://localhost:3001"),
        )
        conn.commit()
    yield project_id


@pytest.fixture
def test_task(project_id: str) -> Generator[dict[str, Any], None, None]:
    """Create and cleanup a test task."""
    task = task_store.create_task(
        project_id=project_id,
        title="Test Task",
        description="Created by test fixture",
    )

    yield task

    task_store.delete_task(task["id"])
