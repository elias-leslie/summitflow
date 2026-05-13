from __future__ import annotations

from unittest.mock import MagicMock

from app.tasks.autonomous.exec_modules.pristine_validation import validate_pristine_codebase


def test_validate_pristine_codebase_does_not_block_on_project_baseline(monkeypatch) -> None:
    emit_log = MagicMock()
    monkeypatch.setattr("app.tasks.autonomous.exec_modules.pristine_validation.emit_log", emit_log)

    assert validate_pristine_codebase("task-123", "summitflow") is True

    emit_log.assert_called_once_with(
        "task-123",
        "info",
        "Skipping baseline quality pre-check; execution will verify task-scoped changes.",
        project_id="summitflow",
    )
