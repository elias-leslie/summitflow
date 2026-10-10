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
    from app.utils import heavy_work as guard

    # The child must reenter the (test-private) lane its parent admitted on.
    code = (
        "import signal,sys; signal.alarm(5); "
        f"sys.path.insert(0,{str(backend)!r}); "
        "from pathlib import Path; from app.utils import heavy_work as guard; "
        f"guard._LOCK_DIRECTORY = Path({str(guard._LOCK_DIRECTORY)!r})\n"
        "with guard.heavy_work('nested cleanroom fixture'): print('nested-admitted')\n"
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
    kept, prune = captured.err.strip().splitlines()[-2:]
    job = Path(kept.removeprefix("CLEANROOM:kept:"))
    try:
        assert prune == "CLEANROOM:prune:st cleanup cleanrooms --project project --older-than 24h"
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


# --- --deps / --collect -----------------------------------------------------


def _deps_project(tmp_path: Path, *, backend_dir: str = "backend", frontend_dir: str = "frontend") -> Path:
    project = _project(tmp_path)
    (project / "project.identity.json").write_text(json.dumps(
        {"runtime": {"backend_dir": backend_dir, "frontend_dir": frontend_dir}},
    ))
    backend = project if backend_dir == "." else project / backend_dir
    frontend = project if frontend_dir == "." else project / frontend_dir
    backend.mkdir(exist_ok=True)
    frontend.mkdir(exist_ok=True)
    (backend / "pyproject.toml").write_text(
        "[project]\nname='x'\nversion='0'\n[project.optional-dependencies]\ndev=['a']\nrelease=['b']\n",
    )
    (backend / "uv.lock").write_text("version = 1\n")
    (frontend / "package.json").write_text("{}\n")
    (frontend / "package-lock.json").write_text("{}\n")
    return project


class _RecordingWork:
    """Stands in for heavy_work: records every spawned command in order."""

    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.fail = fail

    def __enter__(self) -> _RecordingWork:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def run(self, command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), Path(cwd)))
        if command[0] == "build":
            (Path(cwd) / "out").mkdir()
            (Path(cwd) / "out" / "App.AppImage").write_text("binary")
            (Path(cwd) / "out" / "linux-unpacked").mkdir()
            (Path(cwd) / "out" / "linux-unpacked" / "app").write_text("x")
        code = 7 if self.fail and command[0] == self.fail else 0
        return subprocess.CompletedProcess(command, code)


def _use_recording_work(monkeypatch: pytest.MonkeyPatch, work: _RecordingWork, parent: Path) -> None:
    parent.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setenv("TMPDIR", str(parent))
    monkeypatch.setattr(cleanroom, "heavy_work", lambda _label: work)


def test_deps_install_backend_then_frontend_before_command_with_extras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _deps_project(tmp_path)
    work = _RecordingWork()
    _use_recording_work(monkeypatch, work, tmp_path / "parent")
    options = cleanroom.CleanroomOptions(deps=True, extras=("release", "release"), share_caches=False)
    assert cleanroom.run_cleanroom(project, ["build"], options=options) == 0
    commands = [command for command, _cwd in work.calls]
    assert commands == [
        ["uv", "sync", "--locked", "--extra", "dev", "--extra", "release"],
        ["npm", "ci"],
        ["build"],
    ]
    cwds = [cwd for _command, cwd in work.calls]
    snapshot = cwds[2]
    assert cwds[0] == snapshot / "backend"
    assert cwds[1] == snapshot / "frontend"
    assert list((tmp_path / "parent").iterdir()) == []


def test_deps_use_identity_root_dirs_and_pnpm_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _deps_project(tmp_path, backend_dir=".", frontend_dir="web")
    (project / "web" / "package-lock.json").unlink()
    (project / "pnpm-workspace.yaml").write_text("packages: [web]\n")
    work = _RecordingWork()
    _use_recording_work(monkeypatch, work, tmp_path / "parent")
    assert cleanroom.run_cleanroom(
        project, ["build"], options=cleanroom.CleanroomOptions(deps=True, share_caches=False),
    ) == 0
    snapshot = work.calls[-1][1]
    assert work.calls[:2] == [
        (["uv", "sync", "--locked", "--extra", "dev"], snapshot),
        (["pnpm", "install", "--frozen-lockfile"], snapshot),
    ]


def test_deps_failure_skips_command_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _deps_project(tmp_path)
    work = _RecordingWork(fail="uv")
    _use_recording_work(monkeypatch, work, tmp_path / "parent")
    options = cleanroom.CleanroomOptions(deps=True, share_caches=False)
    assert cleanroom.run_cleanroom(project, ["build"], options=options) == 7
    assert [command[0] for command, _cwd in work.calls] == ["uv"]
    assert list((tmp_path / "parent").iterdir()) == []


def test_unknown_extra_is_rejected_with_exit_2_before_any_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    project = _deps_project(tmp_path)
    work = _RecordingWork()
    _use_recording_work(monkeypatch, work, tmp_path / "parent")
    code = cleanroom.main([
        "--project-root", str(project), "--deps", "--extra", "nope", "--", "build",
    ])
    assert code == 2
    assert "unknown backend extra(s): nope (declared: dev, release)" in capfd.readouterr().err
    assert work.calls == []
    assert list((tmp_path / "parent").iterdir()) == []


def test_extra_without_deps_is_a_usage_error(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    assert cleanroom.main(["--project-root", str(tmp_path), "--extra", "release", "--", "true"]) == 2
    assert "--extra requires --deps" in capfd.readouterr().err


def test_collect_copies_artifacts_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    project = _deps_project(tmp_path)
    work = _RecordingWork()
    _use_recording_work(monkeypatch, work, tmp_path / "parent")
    destination = tmp_path / "artifacts"
    options = cleanroom.CleanroomOptions(
        collect=("out/*.AppImage", "out/linux-unpacked"), collect_to=destination,
    )
    assert cleanroom.run_cleanroom(project, ["build"], options=options) == 0
    assert (destination / "out" / "App.AppImage").read_text() == "binary"
    assert (destination / "out" / "linux-unpacked" / "app").read_text() == "x"
    assert f"CLEANROOM:collected:2:{destination}" in capfd.readouterr().err
    assert list((tmp_path / "parent").iterdir()) == []
    assert not (project / "out").exists()


def test_collect_defaults_to_project_dev_tools_and_flags_empty_globs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    project = _deps_project(tmp_path)
    work = _RecordingWork()
    _use_recording_work(monkeypatch, work, tmp_path / "parent")
    options = cleanroom.CleanroomOptions(collect=("out/*.AppImage", "dist/*.zip"))
    assert cleanroom.run_cleanroom(project, ["build"], options=options) == 1
    err = capfd.readouterr().err
    assert "CLEANROOM:collect-empty:dist/*.zip" in err
    (stamp,) = (project / ".dev-tools" / "cleanroom-artifacts").iterdir()
    assert (stamp / "out" / "App.AppImage").is_file()


@pytest.mark.parametrize("pattern", ["/etc/*", "../outside/*", ""])
def test_collect_rejects_patterns_outside_snapshot(tmp_path: Path, pattern: str) -> None:
    with pytest.raises(cleanroom.CleanroomUsageError):
        cleanroom.run_cleanroom(
            tmp_path, ["true"], options=cleanroom.CleanroomOptions(collect=(pattern,)),
        )


def test_install_env_shares_only_existing_download_caches(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "uv").mkdir(parents=True)
    env = cleanroom._install_env(
        {"HOME": "/isolated", "UV_PROJECT_ENVIRONMENT": "/elsewhere"}, {"HOME": str(home)},
    )
    assert env["UV_CACHE_DIR"] == str(home / ".cache" / "uv")
    assert "npm_config_cache" not in env
    assert "UV_PROJECT_ENVIRONMENT" not in env
    assert env["HOME"] == "/isolated"
