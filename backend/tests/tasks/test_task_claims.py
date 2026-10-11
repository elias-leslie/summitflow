"""Stale-claim reset: only expired running claims return to pending."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.tasks.task_claims import reset_expired_task_claims


def _claimable_task(project_id: str, cleanup_task: Callable[[str], None], title: str) -> dict[str, Any]:
    task = task_store.create_task(project_id=project_id, title=title, description="claim expiry test")
    cleanup_task(task["id"])
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO task_spirit (task_id, plan_status, complexity)
            VALUES (%s, 'approved', 'SIMPLE')
            ON CONFLICT (task_id) DO UPDATE SET plan_status = 'approved'
            """,
            (task["id"],),
        )
        conn.commit()
    return task


def test_reset_releases_expired_claims_and_keeps_live_ones(
    ensure_test_project: str, cleanup_task: Callable[[str], None]
) -> None:
    expired = _claimable_task(ensure_test_project, cleanup_task, "expired claim")
    live = _claimable_task(ensure_test_project, cleanup_task, "live claim")
    assert task_store.claim_task(expired["id"], "stale-worker", lock_duration_minutes=-1)
    assert task_store.claim_task(live["id"], "live-worker", lock_duration_minutes=30)

    result = reset_expired_task_claims()

    assert result["error"] is None
    assert result["reset_count"] >= 1
    reset = task_store.get_task(expired["id"])
    assert reset is not None
    assert (reset["status"], reset["claimed_by"], reset["lock_expires_at"]) == ("pending", None, None)
    kept = task_store.get_task(live["id"])
    assert kept is not None
    assert (kept["status"], kept["claimed_by"]) == ("running", "live-worker")
    assert kept["lock_expires_at"] is not None


def test_reset_reports_storage_failure_without_raising() -> None:
    with patch("app.tasks.task_claims.task_store.reset_expired_claims", side_effect=RuntimeError("db down")):
        assert reset_expired_task_claims() == {"reset_count": 0, "error": "db down"}


@pytest.mark.parametrize("count", [0, 3])
def test_reset_returns_storage_count(count: int) -> None:
    with patch("app.tasks.task_claims.task_store.reset_expired_claims", return_value=count):
        assert reset_expired_task_claims() == {"reset_count": count, "error": None}
