"""Review revisions and task links use one per-dependency lock."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.storage import dependency_reviews


def test_task_link_acquires_revision_lock_before_latest_check() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (
        42, "summitflow", "python/backend/fastapi", 2, "digest", {},
        "update", "0.141.1", "Reviewed release", "task-123", datetime.now(UTC),
    )
    with patch.object(dependency_reviews, "get_connection", return_value=connection):
        linked = dependency_reviews.attach_task(
            "summitflow", "python/backend/fastapi", 42, "task-123",
        )
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "pg_advisory_xact_lock" in statements[0]
    assert "MAX(revision)" in statements[1]
    assert linked["task_id"] == "task-123"
    connection.commit.assert_called_once()
