from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app.utils.heavy_work import HeavyWorkError
from cli.lib import cleanroom


@pytest.fixture(autouse=True)
def isolated_temp_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixtures never allocate work under the host's actual scratch mount."""
    monkeypatch.setattr(cleanroom, "_SCRATCH_ROOT", tmp_path / "absent-scratch")
    monkeypatch.delenv("TMPDIR", raising=False)


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
    monkeypatch.setattr(cleanroom, "_cleanroom_temp_parent", unexpected_snapshot)
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


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    return project


@pytest.mark.parametrize("returncode", [0, 23])
def test_cleanroom_routes_checkout_and_child_tmp_to_private_mounted_scratch_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
    returncode: int,
) -> None:
    project = _project(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    monkeypatch.setattr(cleanroom, "_SCRATCH_ROOT", scratch)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == scratch)
    code = (
        "import json,os,tempfile; from pathlib import Path; "
        "job=Path.cwd().parent; temporary=Path(tempfile.mkdtemp()); "
        "print(json.dumps({'job':str(job),'temporary':str(temporary),"
        "'home':os.environ['HOME'],'private':oct(job.stat().st_mode & 0o777)})); "
        f"raise SystemExit({returncode})"
    )
    assert cleanroom.run_cleanroom(project, [sys.executable, "-c", code]) == returncode
    observed = json.loads(capfd.readouterr().out)
    parent = scratch / f"st-cleanrooms-{os.getuid()}"
    job = Path(observed["job"])
    assert job.parent == parent
    assert Path(observed["temporary"]).parent == job / "tmp"
    assert Path(observed["home"]) == job / "home"
    assert observed["private"] == "0o700"
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert list(parent.iterdir()) == []


def test_explicit_tmpdir_beats_scratch_and_cached_python_tempdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    project = _project(tmp_path)
    explicit = tmp_path / "explicit"
    cached = tmp_path / "cached"
    scratch = tmp_path / "unmounted-scratch"
    explicit.mkdir(mode=0o700)
    cached.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)
    monkeypatch.setattr(cleanroom, "_SCRATCH_ROOT", scratch)
    monkeypatch.setenv("TMPDIR", str(explicit))
    monkeypatch.setattr(cleanroom.tempfile, "tempdir", str(cached))
    code = "from pathlib import Path; print(Path.cwd().parent)"
    assert cleanroom.run_cleanroom(project, [sys.executable, "-c", code]) == 0
    assert Path(capfd.readouterr().out.strip()).parent == explicit
    assert list(explicit.iterdir()) == []
    assert list(cached.iterdir()) == []


def test_cleanroom_keeps_requested_directory_and_explicit_child_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    project = _project(tmp_path)
    parent = tmp_path / "parent"
    child_tmp = tmp_path / "child"
    parent.mkdir(mode=0o700)
    child_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(parent))
    assert cleanroom.run_cleanroom(
        project, [sys.executable, "-c", "import os; print(os.environ['TMPDIR'])"],
        env_overrides={"TMPDIR": str(child_tmp)}, keep_dir=True,
    ) == 0
    captured = capfd.readouterr()
    job = Path(captured.err.strip().removeprefix("CLEANROOM:kept:"))
    try:
        assert captured.out.strip() == str(child_tmp)
        assert job.parent == parent
        assert (job / "repo" / ".git").is_dir()
        assert (job / "home").is_dir()
        assert (job / "tmp").is_dir()
    finally:
        shutil.rmtree(job)


@pytest.mark.parametrize("failure", ["snapshot", "mkdir", "launch"])
def test_cleanroom_removes_owned_job_when_preparation_or_launch_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    project = _project(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(parent))
    if failure == "snapshot":
        def unavailable_snapshot(*_args: object) -> None:
            raise OSError("fixture snapshot failure")
        monkeypatch.setattr(cleanroom, "create_snapshot", unavailable_snapshot)
    elif failure == "mkdir":
        original_mkdir = Path.mkdir

        def unavailable_repo(
            path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False,
        ) -> None:
            if path.name == "repo" and path.parent.parent == parent:
                raise OSError("fixture mkdir failure")
            original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        monkeypatch.setattr(Path, "mkdir", unavailable_repo)
    command = ["/cleanroom-fixture-missing-command"] if failure == "launch" else [sys.executable, "-c", "pass"]
    with pytest.raises(OSError):
        cleanroom.run_cleanroom(project, command)
    assert list(parent.iterdir()) == []


def test_cleanroom_portable_fallback_when_host_scratch_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    project = _project(tmp_path)
    parent = tmp_path / "portable"
    parent.mkdir()
    monkeypatch.setattr(cleanroom.tempfile, "tempdir", str(parent))
    assert cleanroom.run_cleanroom(
        project, [sys.executable, "-c", "from pathlib import Path; print(Path.cwd().parent)"],
    ) == 0
    assert Path(capfd.readouterr().out.strip()).parent == parent
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("unsafe", ["unmounted", "symlink", "shared", "private-mode", "private-link"])
def test_cleanroom_rejects_unsafe_host_scratch_before_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    monkeypatch.setattr(cleanroom, "_SCRATCH_ROOT", scratch)
    monkeypatch.setattr(Path, "is_mount", lambda _path: unsafe != "unmounted")
    private = scratch / f"st-cleanrooms-{os.getuid()}"
    if unsafe == "symlink":
        link = tmp_path / "link"
        link.symlink_to(scratch)
        monkeypatch.setattr(cleanroom, "_SCRATCH_ROOT", link)
    elif unsafe == "shared":
        scratch.chmod(0o777)
    elif unsafe == "private-mode":
        private.mkdir(mode=0o755)
    elif unsafe == "private-link":
        private.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Cleanroom"):
        cleanroom.run_cleanroom(tmp_path, [sys.executable, "-c", "pass"])
    assert not list(scratch.glob("*-cleanroom-*"))


def test_temp_parent_rejects_another_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "selected"
    selected.mkdir(mode=0o700)
    monkeypatch.setattr(cleanroom.os, "getuid", lambda: selected.stat().st_uid + 1)
    with pytest.raises(ValueError, match="owner-controlled"):
        cleanroom._validate_temp_parent(selected)


@pytest.mark.parametrize("unsafe", ["missing", "relative", "symlink", "shared", "file"])
def test_cleanroom_rejects_invalid_explicit_tmpdir_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str,
) -> None:
    selected = tmp_path / "selected"
    if unsafe == "relative":
        selected = Path("relative")
    elif unsafe == "symlink":
        selected.symlink_to(tmp_path, target_is_directory=True)
    elif unsafe == "file":
        selected.touch()
    elif unsafe != "missing":
        selected.mkdir()
        selected.chmod(0o777)
    monkeypatch.setenv("TMPDIR", str(selected))
    with pytest.raises((ValueError, OSError)):
        cleanroom.run_cleanroom(tmp_path, [sys.executable, "-c", "pass"])


def test_explicit_tmpdir_accepts_sticky_shared_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "namespace-tmp"
    selected.mkdir()
    selected.chmod(0o1777)
    monkeypatch.setenv("TMPDIR", str(selected))
    assert cleanroom._cleanroom_temp_parent() == selected
