from __future__ import annotations

import subprocess


def test_publish_completed_work_uses_st_git_commit(monkeypatch) -> None:
    from cli.commands import done_task

    commands: list[list[str]] = []

    monkeypatch.setattr(done_task.shutil, "which", lambda name: "/usr/bin/st")
    monkeypatch.setattr(
        "app.storage.projects.get_project_root_path",
        lambda project_id: "/repo",
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
            stdout='{"repos":[{"status":"SUCCESS"}]}',
            stderr="",
        )

    monkeypatch.setattr(done_task.subprocess, "run", fake_run)

    done_task._publish_completed_work("task-1", "summitflow")

    assert commands == [
        [
            "/usr/bin/st",
            "git",
            "commit",
            "--current",
            "--push",
            "--task",
            "task-1",
            "--json",
        ]
    ]
