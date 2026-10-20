"""Acceptance runs a project's tests the way its CI workflow does."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.commands import check
from cli.lib import ci_parity

WORKFLOW = """\
name: CI
on:
  push:
    branches: [main]
env:
  SHARED: top
jobs:
  backend:
    runs-on: ubuntu-24.04
    services:
      postgres:
        image: postgres:16
        env: {POSTGRES_USER: app, POSTGRES_PASSWORD: test, POSTGRES_DB: app_test}
        ports: ["5432:5432"]
    env:
      APP_DB_URL: postgresql://app:test@localhost:5432/app_test
      CONFIG_ROOT: ${{ github.workspace }}/.ci-config
      TOKEN: ${{ secrets.TOKEN }}
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@abc # v8
      - run: uv sync --locked --all-extras --dev
      - name: Migrate test database
        run: uv run alembic upgrade head
      - run: uv run pytest --run-integration -m "not private"
  frontend:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/setup-node@abc
      - run: pnpm exec vitest run
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    bin_dir = root / "backend" / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("pytest", "alembic"):
        (bin_dir / name).write_text("#!/bin/sh\n")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW)
    return root


def test_the_pytest_job_is_derived_from_the_workflow(project: Path) -> None:
    job = ci_parity.pytest_job(project, project / "backend")
    assert job is not None and (job.workflow, job.name) == ("ci.yml", "backend")
    venv = project / "backend" / ".venv" / "bin"
    assert job.tests == [[str(venv / "pytest"), "--run-integration", "-m", "not private"]]
    assert job.setup == [[str(venv / "alembic"), "upgrade", "head"]]  # uv sync is preparation, not a CI step to mirror
    # Literal values and the workspace path only; secrets never resolve locally.
    assert job.env == {"SHARED": "top", "APP_DB_URL": "postgresql://app:test@localhost:5432/app_test",
                       "CONFIG_ROOT": f"{project}/.ci-config"}
    assert {"uv", "git"} <= job.tools and "node" not in job.tools
    assert ci_parity.pytest_job(project, project) is None


def test_environment_is_scrubbed_to_the_workflow_and_ci_tools(project: Path, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    for name in ("st", "uv"):
        tool = home / ".local" / "bin" / name
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
    monkeypatch.setattr(ci_parity.pwd, "getpwuid", lambda _uid: Mock(pw_dir=str(home)))
    (project / ".st-check.toml").write_text('[acceptance]\npass_env = ["KEEP"]\nhost_tools = ["extra"]\n')
    job = ci_parity.pytest_job(project, project / "backend")
    scratch = tmp_path / "scratch"
    env = ci_parity.environment(project, tool_dirs=[project / "backend" / ".venv" / "bin"], job=job, scratch=scratch,
                                base={"KEEP": "1", "SECRET_FROM_ENV_LOCAL": "x", "PATH": "/host/only"})
    assert "SECRET_FROM_ENV_LOCAL" not in env and env["KEEP"] == "1"
    assert env["CI"] == "true" and env["HOME"] == str(scratch / "home") and env["SHARED"] == "top"
    path = env["PATH"].split(os.pathsep)
    assert "/host/only" not in path and "/usr/local/bin" not in path
    aliases = scratch / "bin"
    assert (aliases / "uv").resolve() == (home / ".local" / "bin" / "uv").resolve()
    assert not (aliases / "st").exists()  # host-only: CI has no st


def test_tool_lookup_ignores_the_callers_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The nightly worker's PATH carries SummitFlow's own venv; an owner shell's
    # does not. Both must resolve the same gate binaries.
    leaked = tmp_path / "worker-venv" / "bin"
    leaked.mkdir(parents=True)
    (leaked / "pytest").write_text("#!/bin/sh\n")
    (leaked / "pytest").chmod(0o755)
    monkeypatch.setenv("PATH", f"{leaked}:/usr/bin:/bin")
    monkeypatch.setattr(ci_parity.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    resolved = check._resolve_command("pytest", tmp_path, tmp_path, [], search_path=ci_parity.canonical_tool_path())
    assert resolved[0] != str(leaked / "pytest")
    assert check._resolve_command("pytest", tmp_path, tmp_path, [])[0] == str(leaked / "pytest")


def test_seed_pins_order_only_where_ci_randomizes(project: Path) -> None:
    pytest_bin = str(project / "backend" / ".venv" / "bin" / "pytest")
    assert ci_parity.seeded([pytest_bin, "-q"], 7) == [pytest_bin, "-q"]
    site = project / "backend" / ".venv" / "lib" / "python3.13" / "site-packages" / "pytest_randomly"
    site.mkdir(parents=True)
    assert ci_parity.seeded([pytest_bin, "-q"], 7) == [pytest_bin, "-q", "--randomly-seed=7"]
    assert ci_parity.seeded([pytest_bin, "-p", "no:randomly"], 7) == [pytest_bin, "-p", "no:randomly"]
    assert ci_parity.repro_command(7) == "st check --ci-repro --seed 7"


@pytest.mark.parametrize(("command", "expected"), [
    ("uv run --locked pytest -q", ["pytest", "-q"]),
    ("uv run --extra dev pytest", ["pytest"]),
    (".venv/bin/pytest", ["pytest"]),
    ("uv run pytest && echo done", None),
    ("uv run --unknown pytest", None),
])
def test_translate_runs_the_prepared_executable_without_syncing(project: Path, command: str,
                                                                expected: list[str] | None) -> None:
    workdir = project / "backend"
    argv = ci_parity.translate(command, project, workdir)
    if expected is None:
        assert argv is None
    else:
        assert argv == [str(workdir / ".venv" / "bin" / expected[0]), *expected[1:]]


def test_parity_pytest_runs_ci_migrations_then_the_ci_test_command(project: Path, capsys: pytest.CaptureFixture[str],
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ci_parity.SEED_VAR, "42")
    job = ci_parity.pytest_job(project, project / "backend")
    assert job is not None
    calls: list[list[str]] = []
    work = Mock(run=lambda argv, **_: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "ok", ""))
    result = check._run_parity_pytest(work, project / "backend", ["pytest"], [], job, {}, None, ["postgres"])
    assert result.returncode == 0
    assert [Path(argv[0]).name for argv in calls] == ["alembic", "pytest"]
    line = capsys.readouterr().out
    assert "CI_PARITY:pytest|job:ci.yml:backend|seed:42|services:postgres|repro:st check --ci-repro --seed 42" in line


def test_failed_migration_stops_before_tests(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ci_parity.SEED_VAR, raising=False)
    job = ci_parity.pytest_job(project, project / "backend")
    calls: list[list[str]] = []
    work = Mock(run=lambda argv, **_: calls.append(argv) or subprocess.CompletedProcess(argv, 3, "", "boom"))
    assert check._run_parity_pytest(work, project / "backend", ["pytest"], [], job, {}, None, []).returncode == 3
    assert len(calls) == 1


def test_service_urls_point_at_the_fresh_container(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job = ci_parity.CiJob("ci.yml", "backend", ".", {}, {"postgres": {"image": "postgres:16", "env": {
        "POSTGRES_USER": "app", "POSTGRES_PASSWORD": "test", "POSTGRES_DB": "app_test"}}}, [], [["pytest"]])
    commands: list[list[str]] = []

    def run(argv, **_):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, "container\n", "")

    monkeypatch.setattr(ci_parity, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(ci_parity.os, "access", lambda *_: True)
    monkeypatch.setattr(ci_parity, "_free_port", lambda: 55432)
    monkeypatch.setattr(ci_parity.subprocess, "run", run)
    env = {"APP_DB_URL": "postgresql://app:test@localhost:5432/app_test", "OTHER": "localhost:5432"}
    with ci_parity.services(job, env) as names:
        assert names == ["postgres"]
        assert env == {"APP_DB_URL": "postgresql://app:test@127.0.0.1:55432/app_test", "OTHER": "localhost:5432",
                       "PGHOST": "127.0.0.1", "PGPORT": "55432"}
        assert "--tmpfs" in commands[0] and "127.0.0.1:55432:5432" in commands[0]
    assert commands[-1][:3] == ["/usr/bin/docker", "rm", "-f"]


def test_a_user_without_docker_runs_ci_services_in_its_own_podman(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job = ci_parity.CiJob("ci.yml", "backend", ".", {}, {"postgres": {"image": "postgres:16"}}, [], [["pytest"]])
    commands: list[list[str]] = []
    client_runtimes: list[Path] = []

    def run(argv, **kwargs):
        commands.append(argv)
        if argv[0] == "/usr/bin/podman":
            runtime = Path(kwargs["env"]["XDG_RUNTIME_DIR"])
            assert runtime != tmp_path
            (runtime / "libpod").mkdir()  # the remote client writes here even with an explicit socket URL
            client_runtimes.append(runtime)
        else:
            assert kwargs["env"]["XDG_RUNTIME_DIR"] == str(tmp_path)  # manager discovery retains its real runtime
        return subprocess.CompletedProcess(argv, 0, "container\n", "")

    (tmp_path / "podman").mkdir()
    (tmp_path / "podman" / "podman.sock").touch()
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(ci_parity, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(ci_parity.os, "access", lambda *_: False)  # the docker socket is not this user's
    monkeypatch.setattr(ci_parity, "_free_port", lambda: 55432)
    monkeypatch.setattr(ci_parity.subprocess, "run", run)
    remote = ["/usr/bin/podman", "--remote", "--url", f"unix://{tmp_path}/podman/podman.sock"]
    with ci_parity.services(job, {}):
        assert commands[0] == ["/usr/bin/systemctl", "--user", "--no-ask-password", "start", "podman.socket"]
        assert commands[1][:5] == [*remote, "run"] and commands[1][-1] == "docker.io/library/postgres:16"
    assert commands[-1][:6] == [*remote, "rm", "-f"]
    assert len(client_runtimes) == 3  # run, readiness exec, cleanup
    assert all(not runtime.exists() for runtime in client_runtimes)
    assert os.environ["XDG_RUNTIME_DIR"] == str(tmp_path)


def test_podman_discovery_derives_own_runtime_without_changing_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = Path("/run/user/12345")
    sock = runtime / "podman" / "podman.sock"
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/99999/bus")
    monkeypatch.setattr(ci_parity.os, "getuid", lambda: 12345)
    monkeypatch.setattr(ci_parity.os, "access", lambda *_: False)
    monkeypatch.setattr(ci_parity, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(ci_parity.Path, "is_dir", lambda path: path == runtime)
    monkeypatch.setattr(ci_parity.Path, "exists", lambda path: path == sock)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["env"]["XDG_RUNTIME_DIR"] == str(runtime)
        assert kwargs["env"]["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={runtime}/bus"
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(ci_parity.subprocess, "run", run)
    assert ci_parity.container_cli() == (["/usr/bin/podman", "--remote", "--url", f"unix://{sock}"], True)
    assert calls == [["/usr/bin/systemctl", "--user", "--no-ask-password", "start", "podman.socket"]]
    assert "XDG_RUNTIME_DIR" not in os.environ
    assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/99999/bus"


@pytest.mark.parametrize("image,full", [("postgres:16", "docker.io/library/postgres:16"),
                                        ("pgvector/pgvector:pg16", "docker.io/pgvector/pgvector:pg16"),
                                        ("ghcr.io/o/i:1", "ghcr.io/o/i:1"), ("localhost/x", "localhost/x")])
def test_image_names_get_docker_hubs_implicit_registry(image: str, full: str) -> None:
    assert ci_parity.qualified_image(image) == full


def test_step_level_working_directory_and_shell_database_setup(tmp_path: Path) -> None:
    # jobinator/portfolio-ai: per-step working-directory and a multi-line createuser/createdb step.
    root = tmp_path / "p"
    (root / "backend" / ".venv" / "bin").mkdir(parents=True)
    (root / "backend" / ".venv" / "bin" / "pytest").write_text("")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "on: [push]\njobs:\n  t:\n    env: {DB: x}\n    steps:\n"
        "      - name: Create database\n        env: {PGPASSWORD: test}\n"
        "        run: |\n          createuser -h localhost -U postgres app\n          createdb -h localhost app_test\n"
        "      - run: uv run pytest\n        working-directory: backend\n")
    job = ci_parity.pytest_job(root, root / "backend")
    assert job is not None and job.env == {"DB": "x"}
    assert job.setup[0][:3] == ["/usr/bin/env", "PGPASSWORD=test", "bash"] and "createdb" in job.setup[0][-1]


def test_ci_that_only_runs_the_st_gate_still_supplies_its_env_and_services(tmp_path: Path,
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    # neri: one job runs `"$ST_CANONICAL_BIN" check --check` against a postgres service.
    root = tmp_path / "p"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "on: [push]\nenv: {NERI_DB_URL: 'postgresql://app:x@127.0.0.1:5432/app_test'}\njobs:\n  quality:\n"
        "    services:\n      postgres: {image: postgres:16}\n    steps:\n"
        "      - run: '\"$ST_CANONICAL_BIN\" check actionlint'\n"
        "      - run: '\"$ST_CANONICAL_BIN\" check --check'\n")
    job = ci_parity.pytest_job(root, root / "backend")
    assert job is not None and job.gate and not job.tests
    assert job.env == {"NERI_DB_URL": "postgresql://app:x@127.0.0.1:5432/app_test"} and list(job.services) == ["postgres"]
    calls: list[list[str]] = []
    work = Mock(run=lambda argv, **_: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "ok", ""))
    assert check._run_parity_pytest(work, root / "backend", ["pytest", "-q"], [], job, {}, None, ["postgres"]).returncode == 0
    assert [argv[:2] for argv in calls] == [["pytest", "-q"]]
    assert "job:ci.yml:quality" in capsys.readouterr().out
    (root / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW)
    assert ci_parity.pytest_job(root, root / "backend") is None  # a pytest job elsewhere, no gate job


def test_lookup_path_uses_the_account_home_not_a_redirected_home(monkeypatch: pytest.MonkeyPatch) -> None:
    import pwd

    monkeypatch.setenv("HOME", "/sandbox/home")
    assert ci_parity.canonical_tool_path().split(os.pathsep)[0] == f"{pwd.getpwuid(os.getuid()).pw_dir}/.local/bin"


def test_tsc_without_project_typescript_skips_instead_of_running_a_cached_npx_package(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "tsconfig.json").write_text("{}")
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check, "heavy_work", Mock(side_effect=AssertionError("npx ran")))
    config: dict[str, object] = {"label": "TSC", "binary": "npx", "args": "tsc --noEmit", "working_dir": "frontend"}
    assert check._run_tool("tsc", config, []) == 0
    assert "TSC:SKIP:tsc:no_package_manifest" in capsys.readouterr().out
    # A manifest that could install TypeScript makes missing node_modules a broken environment.
    (tmp_path / "package.json").write_text('{"devDependencies": {"typescript": "5"}}')
    assert check._run_tool("tsc", config, []) == 0
    assert "TSC:SKIP:tsc:tool_not_installed" in capsys.readouterr().out


def test_scratch_uses_managed_scratch_not_the_read_only_isolated_home(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolated acceptance mounts / (and the account home) read-only.
    monkeypatch.setattr(ci_parity.pwd, "getpwuid", lambda _uid: Mock(pw_dir="/nonexistent-read-only-home"))
    monkeypatch.setattr(ci_parity, "managed_temp_parent", lambda namespace, **_: tmp_path)
    with ci_parity.scratch_directory() as scratch:
        assert scratch.parent == tmp_path and scratch.is_dir()
    assert not scratch.exists()
