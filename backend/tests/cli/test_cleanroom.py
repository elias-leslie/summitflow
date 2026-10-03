from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.utils.heavy_work import HeavyWorkError
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


def test_admission_failure_precedes_snapshot_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_label: str) -> None:
        raise HeavyWorkError("fixture admission unavailable")

    def unexpected_snapshot(*_args: object, **_kwargs: object) -> None:
        pytest.fail("snapshot materialized before heavy-work admission")

    monkeypatch.setattr(cleanroom, "heavy_work", unavailable, raising=False)
    monkeypatch.setattr(cleanroom.tempfile, "mkdtemp", unexpected_snapshot)
    with pytest.raises(HeavyWorkError, match="fixture admission unavailable"):
        cleanroom.run_cleanroom(tmp_path, [sys.executable, "-c", "pass"])


def test_cleanroom_child_inherits_admission_limits_and_lower_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _init_git_repo(project_root)
    before = os.getpriority(os.PRIO_PROCESS, 0)
    monkeypatch.setenv("UV_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("GOMAXPROCS", "99")
    code = (
        "import json,os; print(json.dumps({"
        "'lease':bool(os.environ.get('ST_HEAVY_LEASE')),"
        "'uv':os.environ['UV_CONCURRENT_BUILDS'],"
        "'go':os.environ['GOMAXPROCS'],"
        "'nice':os.getpriority(os.PRIO_PROCESS,0)})); raise SystemExit(23)"
    )
    assert cleanroom.run_cleanroom(project_root, [sys.executable, "-c", code]) == 23
    observed = json.loads(capfd.readouterr().out)
    assert observed == {"lease": True, "uv": "1", "go": "2", "nice": min(19, before + 10)}
    assert os.getpriority(os.PRIO_PROCESS, 0) == before


def test_cleanroom_child_can_reenter_shared_admission(
    tmp_path: Path, capfd: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _init_git_repo(project_root)
    backend = Path(__file__).resolve().parents[2]
    code = (
        "import signal,sys; signal.alarm(5); "
        f"sys.path.insert(0,{str(backend)!r}); "
        "from app.utils.heavy_work import heavy_work\n"
        "with heavy_work('nested cleanroom fixture'): print('nested-admitted')\n"
    )
    assert cleanroom.run_cleanroom(project_root, [sys.executable, "-c", code]) == 0
    assert capfd.readouterr().out.strip() == "nested-admitted"
