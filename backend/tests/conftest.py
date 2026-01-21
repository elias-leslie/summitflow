"""Test configuration and fixtures.

Provides FastAPI TestClient and database cleanup fixtures.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage.connection import get_connection


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def test_project_id():
    """Return a test project ID (monkey-fight exists in dev DB)."""
    return "monkey-fight"


@pytest.fixture
def cleanup_task():
    """Fixture that returns a cleanup function for tasks."""
    created_tasks = []

    def _cleanup_task(task_id: str):
        created_tasks.append(task_id)

    yield _cleanup_task

    # Cleanup after test
    if created_tasks:
        with get_connection() as conn, conn.cursor() as cur:
            for task_id in created_tasks:
                # Delete in order: steps -> subtasks -> spirit -> labels -> deps -> task
                cur.execute(
                    "DELETE FROM task_subtask_steps WHERE subtask_id IN (SELECT id FROM task_subtasks WHERE task_id = %s)",
                    (task_id,),
                )
                cur.execute("DELETE FROM task_subtasks WHERE task_id = %s", (task_id,))
                cur.execute("DELETE FROM task_spirit WHERE task_id = %s", (task_id,))
                cur.execute("DELETE FROM task_labels WHERE task_id = %s", (task_id,))
                cur.execute(
                    "DELETE FROM task_dependencies WHERE task_id = %s OR depends_on_task_id = %s",
                    (task_id, task_id),
                )
                cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            conn.commit()
