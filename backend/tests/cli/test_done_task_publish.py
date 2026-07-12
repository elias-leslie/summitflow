from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_publish_completed_work_uses_st_commit_and_cleans_jj_bookmark(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from cli.commands import done_task

    commands: list[list[str]] = []
    project_root = tmp_path / "repo"
    (project_root / ".jj").mkdir(parents=True)

    monkeypatch.setattr(done_task.shutil, "which", lambda name: "/usr/bin/st")
    monkeypatch.setattr(
        "app.storage.projects.get_project_root_path",
        lambda project_id: str(project_root),
    )

    def fake_run(
        command: list[str],
        cwd: str,
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"status":"SUCCESS"}',
            stderr="",
        )

    monkeypatch.setattr(done_task.subprocess, "run", fake_run)

    done_task._publish_completed_work("task-1", "summitflow")

    assert commands == [
        [
            "/usr/bin/st",
            "--no-compact",
            "commit",
            "--push",
            "--task",
            "task-1",
            "--message",
            "complete task-1",
        ],
        [
            "/usr/bin/st",
            "jj",
            "push",
            "--delete-bookmark",
            "--task",
            "task-1",
            "--repo",
            str(project_root),
        ],
    ]


def test_publish_completed_work_raises_when_st_commit_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from cli.commands import done_task

    project_root = tmp_path / "repo"
    project_root.mkdir()
    monkeypatch.setattr(done_task.shutil, "which", lambda name: "/usr/bin/st")
    monkeypatch.setattr(
        "app.storage.projects.get_project_root_path",
        lambda project_id: str(project_root),
    )
    monkeypatch.setattr(
        done_task.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout='{"status":"BLOCKED","detail":"push rejected"}',
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="push rejected"):
        done_task._publish_completed_work("task-1", "summitflow")


def test_publish_completed_work_raises_when_result_is_unreadable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from cli.commands import done_task

    project_root = tmp_path / "repo"
    project_root.mkdir()
    monkeypatch.setattr(done_task.shutil, "which", lambda name: "/usr/bin/st")
    monkeypatch.setattr(
        "app.storage.projects.get_project_root_path",
        lambda project_id: str(project_root),
    )
    monkeypatch.setattr(
        done_task.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="not-json", stderr=""
        ),
    )

    with pytest.raises(RuntimeError, match="not-json"):
        done_task._publish_completed_work("task-1", "summitflow")
