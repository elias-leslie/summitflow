from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cli.lib import cleanroom


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=path,
        check=True,
    )


def test_build_cleanroom_env_scrubs_project_keys_and_isolates_home(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    snapshot_root = tmp_path / "snapshot"
    home_root = tmp_path / "home"
    project_root.mkdir()
    snapshot_root.mkdir()
    (project_root / ".env.example").write_text("DATABASE_URL=postgresql://placeholder\n")

    env = cleanroom.build_cleanroom_env(
        project_root,
        snapshot_root,
        home_root,
        base_env={
            "DATABASE_URL": "postgresql://stale-shell",
            "BASH_ENV": "/tmp/bash-command-guard.sh",
            "PATH": "/usr/bin",
            "PYTHONPATH": "/tmp/stale",
        },
        env_overrides={"CUSTOM_FLAG": "enabled"},
    )

    assert "DATABASE_URL" not in env
    assert "BASH_ENV" not in env
    assert "PYTHONPATH" not in env
    assert env["HOME"] == str(home_root)
    assert env["PWD"] == str(snapshot_root)
    assert env["CUSTOM_FLAG"] == "enabled"
    assert env["PATH"] == "/usr/bin"
    assert env["SF_COMMAND_GUARD_DISABLE"] == "1"


def test_run_cleanroom_uses_working_tree_not_head_and_skips_ignored_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _init_git_repo(project_root)

    (project_root / ".env.example").write_text("DATABASE_URL=postgresql://placeholder\n")
    (project_root / ".gitignore").write_text("ignored.txt\n")
    (project_root / "value.txt").write_text("old\n")
    subprocess.run(["git", "add", ".env.example", ".gitignore", "value.txt"], cwd=project_root, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=project_root, check=True)

    (project_root / "value.txt").write_text("new\n")
    (project_root / "note.txt").write_text("untracked\n")
    (project_root / "ignored.txt").write_text("ignored\n")

    monkeypatch.setenv("DATABASE_URL", "postgresql://stale-shell")

    exit_code = cleanroom.run_cleanroom(
        project_root,
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "import os",
                    "from pathlib import Path",
                    "print(Path('value.txt').read_text().strip())",
                    "print(Path('note.txt').exists())",
                    "print(Path('ignored.txt').exists())",
                    "print(os.environ.get('DATABASE_URL', 'MISSING'))",
                ]
            ),
        ],
    )

    assert exit_code == 0
    lines = capfd.readouterr().out.strip().splitlines()
    assert lines == ["new", "True", "False", "MISSING"]


def test_parse_env_assignments_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="invalid env assignment"):
        cleanroom.parse_env_assignments(["BROKEN"])
