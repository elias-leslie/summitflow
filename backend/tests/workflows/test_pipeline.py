from __future__ import annotations

from unittest.mock import MagicMock


def test_dispatch_callback_logs_unknown_stage(mocker) -> None:
    from app.workflows.pipeline import _make_dispatch_callback

    logger = mocker.patch("app.workflows.pipeline.logger")
    dispatch = _make_dispatch_callback()

    dispatch("missing-stage", "task-123", "project-123")

    logger.exception.assert_called_once_with(
        "dispatch_callback_failed",
        stage="missing-stage",
        task_id="task-123",
    )
