from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from app.tasks.nightly_deep_lane import clean_env_green_since, skip_reason
from cli.lib import deep_lane
from cli.lib.deep_lane import DeepLaneError, _run, clean_env_applies, deep_stages

SLOW_INI = "[pytest]\nmarkers =\n    slow: long tests\n    unit: fast\n"


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"pytest.ini": SLOW_INI}, ["pytest-slow"]),
        ({"backend/pytest.ini": SLOW_INI}, ["pytest-slow"]),
        ({"pyproject.toml": '[tool.pytest.ini_options]\nmarkers = ["slow: long"]\n'}, ["pytest-slow"]),
        ({"setup.cfg": "[tool:pytest]\nmarkers =\n    slow\n"}, ["pytest-slow"]),
        ({"pytest.ini": "[pytest]\nmarkers =\n    slowish: no\n"}, []),
        ({"go.mod": "module x\n", "a_test.go": "//go:build slow\n\npackage x\n"}, ["go-slow"]),
        ({"go.mod": "module x\n", "a_test.go": "package x\n"}, []),
        ({"pytest.ini": SLOW_INI,
          ".st-check.toml": '[[deep.stages]]\nid = "fixture"\nargv = ["run", "deep"]\n'}, ["fixture"]),
    ],
)
def test_deep_stages_follow_opt_in_conventions(tmp_path: Path, files: dict[str, str], expected: list[str]) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, content in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    assert [stage["id"] for stage in deep_stages(tmp_path)] == expected


@pytest.mark.parametrize("declaration", [
    "[deep]\n",
    '[[deep.stages]]\nid = "x"\nargv = []\n',
    '[[deep.stages]]\nid = "x"\nargv = ["a"]\ncwd = "../elsewhere"\n',
])
def test_invalid_deep_declaration_is_refused(tmp_path: Path, declaration: str) -> None:
    (tmp_path / ".st-check.toml").write_text(declaration)
    with pytest.raises(DeepLaneError):
        deep_stages(tmp_path)


@pytest.mark.parametrize(
    ("code", "none_ok", "state"),
    [(0, False, "pass"), (5, True, "pass"), (5, False, "fail"), (1, True, "fail")],
)
def test_stage_outcome_tolerates_only_an_empty_opt_in(tmp_path: Path, code: int, none_ok: bool, state: str) -> None:
    stage = {"id": "s", "argv": ["sh", "-c", f"exit {code}"], "cwd": ".", "timeout_seconds": 10,
             "admitted": True, "none_ok": none_ok}
    assert _run(tmp_path, stage, {"PATH": "/usr/bin:/bin"})["state"] == state


HEAD, OTHER = "a" * 40, "b" * 40


@pytest.mark.parametrize(
    ("prior", "skipped"),
    [
        ({}, False),
        ({"date": "2026-10-12", "sha": OTHER, "state": "fail"}, True),
        ({"date": "2026-10-10", "sha": HEAD, "state": "pass"}, True),
        ({"date": "2026-10-10", "sha": HEAD, "state": "fail"}, False),
        ({"date": "2026-10-10", "sha": OTHER, "state": "pass"}, False),
        ({"date": "2026-09-01", "sha": HEAD, "state": "pass"}, False),
    ],
)
def test_nightly_runs_each_project_once_a_day_unless_its_head_recently_passed(prior: dict, skipped: bool) -> None:
    assert (skip_reason(prior, HEAD, date(2026, 10, 12)) is not None) is skipped


def _ci_workflow(root: Path, command: str = "uv run pytest") -> None:
    """A CI job in backend/ whose test step is ``command``, with the local pytest it maps to."""
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "on: [push]\njobs:\n  backend:\n    runs-on: ubuntu-24.04\n"
        "    defaults:\n      run:\n        working-directory: backend\n"
        f"    steps:\n      - run: '{command}'\n")
    (root / "backend" / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
    (root / "backend" / ".venv" / "bin" / "pytest").write_text("")


@pytest.mark.parametrize(
    ("files", "ci", "applies"),
    [
        ({"backend/alembic.ini": "[alembic]\n"}, "uv run pytest", True),
        ({"migrations/0001_init.sql": "select 1;\n"}, "uv run pytest", True),
        ({"pnpm-workspace.yaml": "packages: [web]\n"}, "uv run pytest", True),
        ({"pyproject.toml": "[tool.uv.workspace]\nmembers = ['pkgs/*']\n"}, "uv run pytest", True),
        ({"pyproject.toml": "[project]\nname = 'x'\n", "web/package.json": "{}\n"}, "uv run pytest", False),
        # No CI workflow (learn-o-tron) or CI that only calls the st gate (neri):
        # ci_parity has no job env or service database to give the gate.
        ({"backend/alembic.ini": "[alembic]\n"}, None, False),
        ({"backend/alembic.ini": "[alembic]\n"}, '"$ST_CANONICAL_BIN" check --check', False),
    ],
)
def test_clean_env_runs_only_for_repos_with_migrations_or_workspace_packages_and_a_ci_pytest_job(
        tmp_path: Path, files: dict[str, str], ci: str | None, applies: bool) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, content in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(content)
    if ci is not None:
        _ci_workflow(tmp_path, ci)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    assert clean_env_applies(tmp_path) is applies


def test_clean_env_gates_a_fresh_clone_of_head_with_fresh_deps_and_ci_parity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / "project.identity.json").write_text('{"runtime": {"backend_extras": ["compression"]}}')
    _ci_workflow(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "x"],
                   cwd=tmp_path, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True,
                          check=True).stdout.strip()
    ran: list[dict] = []

    envs: dict[str, dict] = {}

    def record(_root: Path, stage: dict, env: dict) -> dict:
        ran.append(stage)
        envs[stage["id"]] = env
        return {"id": stage["id"], "state": "pass"}

    monkeypatch.setattr(deep_lane, "_run", record)
    assert deep_lane.run_deep(tmp_path)["state"] == "pass"
    assert [stage["id"] for stage in ran] == ["gate", "clean-env"]
    # Only the gate runs without reuse; later stages (slow tests) must not inherit the flag.
    assert envs["gate"]["ST_NATIVE_NO_REUSE"] == "1" and "ST_NATIVE_NO_REUSE" not in envs["clean-env"]
    argv = ran[-1]["argv"]
    split = argv.index("--")
    # Deps match the managed checkout's gate environment: dev plus the identity's backend extras.
    assert argv[argv.index("cleanroom"):argv.index("cleanroom") + 6] == [
        "cleanroom", "--clone", head, "--deps", "--extra", "compression"]
    assert "ST_CHECK_CI_PARITY=1" in argv[:split] and "ST_NATIVE_NO_REUSE=1" in argv[:split]
    assert argv[split + 1:][-2:] == ["check", "--check"]
    # The gate keeps the cleanroom's private HOME; only st's settings file is copied in.
    assert not any(arg.startswith("HOME=") for arg in argv)
    assert argv[split + 1] == "/bin/sh" and argv[split + 4].endswith("/.env.local")


@pytest.mark.parametrize(
    ("prior", "clean_env", "expected"),
    [
        ({}, "pass", "2026-10-12"),
        ({"clean_env_green_since": "2026-10-01"}, "pass", "2026-10-01"),
        ({"clean_env_green_since": "2026-10-01"}, "fail", None),
        ({}, None, None),
    ],
)
def test_clean_env_green_streak_start_resets_on_a_clean_env_failure(
        prior: dict, clean_env: str | None, expected: str | None) -> None:
    outcome = {"state": "pass", **({"clean_env": clean_env} if clean_env else {})}
    assert clean_env_green_since(prior, outcome, date(2026, 10, 12)) == expected


def test_clean_env_green_streak_ends_when_the_whole_lane_times_out() -> None:
    # The timeout outcome carries no stage results, so a hung clean-env never counts as green.
    outcome = {"state": "fail", "reason": "deep_lane_timeout"}
    assert clean_env_green_since({"clean_env_green_since": "2026-10-01"}, outcome, date(2026, 10, 12)) is None
