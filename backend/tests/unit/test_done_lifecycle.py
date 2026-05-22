from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_task_work_touched_frontend_detects_frontend_diff(monkeypatch) -> None:
    from cli.commands.done_lifecycle import _task_work_touched_frontend

    monkeypatch.setattr(
        "cli.commands.done_lifecycle.get_project_root_path",
        lambda project_id: "/repo",
    )
    monkeypatch.setattr(
        "cli.commands.done_lifecycle.load_services_config",
        lambda project_root: SimpleNamespace(get_service=lambda name: SimpleNamespace(cwd="frontend")),
    )
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="frontend/app/page.tsx\nbackend/app.py\n"))
    monkeypatch.setattr("cli.commands.done_lifecycle.subprocess.run", run)

    assert _task_work_touched_frontend("task-123", "summitflow", base_branch="main") is True


def test_task_work_touched_frontend_ignores_backend_only_diff(monkeypatch) -> None:
    from cli.commands.done_lifecycle import _task_work_touched_frontend

    monkeypatch.setattr(
        "cli.commands.done_lifecycle.get_project_root_path",
        lambda project_id: "/repo",
    )
    monkeypatch.setattr(
        "cli.commands.done_lifecycle.load_services_config",
        lambda project_root: SimpleNamespace(get_service=lambda name: SimpleNamespace(cwd="frontend")),
    )
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="backend/app.py\ndocs/notes.md\n"))
    monkeypatch.setattr("cli.commands.done_lifecycle.subprocess.run", run)

    assert _task_work_touched_frontend("task-123", "summitflow", base_branch="main") is False


def test_task_work_touched_frontend_skips_projects_without_frontend_service(monkeypatch) -> None:
    from cli.commands.done_lifecycle import _task_work_touched_frontend

    monkeypatch.setattr(
        "cli.commands.done_lifecycle.get_project_root_path",
        lambda project_id: "/repo",
    )
    monkeypatch.setattr(
        "cli.commands.done_lifecycle.load_services_config",
        lambda project_root: SimpleNamespace(get_service=lambda name: None),
    )

    assert _task_work_touched_frontend("task-123", "summitflow", base_branch="main") is False