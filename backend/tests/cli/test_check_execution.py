"""Tests for st check tool-execution env helpers.

Regression coverage for the fleet-wide vitest breakage: when st check inherits
NODE_ENV=production (e.g. launched from an electron-vite/npm prod context),
vitest loads the production React build where React.act is undefined and
@testing-library throws "React.act is not a function". tool_env must normalize
NODE_ENV to "test" for vitest so every project's frontend suite runs correctly
without per-project vitest.config drift.

Also covers the .st-check.toml opt-in declaration mechanism: when a project
declares its venv path, tool_env uses that path and only that path (no
fallback to the default candidate list).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.utils import heavy_work as guard
from cli.commands import check
from cli.commands.check_execution import (
    adjusted_tool_args,
    read_pytest_no_cov,
    read_pytest_workers,
    read_tool_paths,
    tool_env,
)


def test_tool_env_forces_node_env_test_for_vitest(tmp_path: Path) -> None:
    env = tool_env(tmp_path, {"NODE_ENV": "production"}, "vitest")
    assert env["NODE_ENV"] == "test"


def test_tool_env_sets_node_env_test_for_vitest_when_unset(tmp_path: Path) -> None:
    env = tool_env(tmp_path, {}, "vitest")
    assert env["NODE_ENV"] == "test"


def test_tool_env_leaves_node_env_untouched_for_other_tools(tmp_path: Path) -> None:
    env = tool_env(tmp_path, {"NODE_ENV": "production"}, "pytest")
    assert env["NODE_ENV"] == "production"


def test_tool_env_no_name_is_path_only(tmp_path: Path) -> None:
    env = tool_env(tmp_path, {"NODE_ENV": "production"})
    assert env["NODE_ENV"] == "production"


# --- .st-check.toml declaration tests ---------------------------------------


def test_read_tool_paths_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_tool_paths(tmp_path) == {}


def test_read_tool_paths_valid_table_returns_paths(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text('[paths]\npytest = "venv/bin"\nruff = ".venv/bin"\n')
    assert read_tool_paths(tmp_path) == {"pytest": "venv/bin", "ruff": ".venv/bin"}


def test_read_tool_paths_empty_file_returns_empty(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text("")
    assert read_tool_paths(tmp_path) == {}


def test_read_tool_paths_no_paths_table_returns_empty(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text('[other]\nkey = "value"\n')
    assert read_tool_paths(tmp_path) == {}


def test_read_tool_paths_malformed_toml_returns_empty(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text("this is not valid = toml ===\n")
    assert read_tool_paths(tmp_path) == {}


def test_read_tool_paths_skips_non_string_values(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text(
        '[paths]\npytest = "venv/bin"\nruff = 42\nbiome = ["list", "of", "paths"]\n'
    )
    assert read_tool_paths(tmp_path) == {"pytest": "venv/bin"}


def test_tool_env_uses_declared_venv_path(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text('[paths]\npytest = "venv/bin"\n')
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    env = tool_env(tmp_path, {}, "pytest")
    assert env["PATH"].startswith(str(tmp_path / "venv" / "bin") + ":")


def test_tool_env_declared_path_takes_precedence_over_dotvenv(tmp_path: Path) -> None:
    # .st-check.toml names a non-default venv; the declared path is the only
    # one added to PATH, so a stray .venv/ does not silently win.
    (tmp_path / ".st-check.toml").write_text('[paths]\npytest = "venv/bin"\n')
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    env = tool_env(tmp_path, {}, "pytest")
    path_entries = env["PATH"].split(":")
    assert str(tmp_path / "venv" / "bin") in path_entries
    assert str(tmp_path / ".venv" / "bin") not in path_entries


def test_tool_env_declared_path_not_present_omits_from_path(tmp_path: Path) -> None:
    # .st-check.toml declares a path that doesn't exist on disk; tool_env
    # silently drops it (same behavior as missing default candidates).
    (tmp_path / ".st-check.toml").write_text('[paths]\npytest = "venv/bin"\n')
    env = tool_env(tmp_path, {"PATH": "/usr/bin"}, "pytest")
    path_entries = env["PATH"].split(":")
    assert str(tmp_path / "venv" / "bin") not in path_entries


def test_tool_env_falls_back_to_defaults_when_undeclared(tmp_path: Path) -> None:
    # .st-check.toml exists but doesn't mention pytest; defaults apply.
    (tmp_path / ".st-check.toml").write_text('[paths]\nruff = "venv/bin"\n')
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    env = tool_env(tmp_path, {}, "pytest")
    assert env["PATH"].startswith(str(tmp_path / ".venv" / "bin") + ":")


def test_tool_env_falls_back_to_defaults_when_no_config(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    env = tool_env(tmp_path, {}, "pytest")
    assert env["PATH"].startswith(str(tmp_path / ".venv" / "bin") + ":")


# --- [pytest] no_cov knob tests --------------------------------------------


def test_read_pytest_no_cov_default_is_true(tmp_path: Path) -> None:
    # No .st-check.toml present: historic behavior is preserved.
    assert read_pytest_no_cov(tmp_path) is True


def test_read_pytest_no_cov_explicit_true(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text("[pytest]\nno_cov = true\n")
    assert read_pytest_no_cov(tmp_path) is True


def test_read_pytest_no_cov_explicit_false(tmp_path: Path) -> None:
    # Project without pytest-cov installed: opt out of the auto-injection.
    (tmp_path / ".st-check.toml").write_text("[pytest]\nno_cov = false\n")
    assert read_pytest_no_cov(tmp_path) is False


def test_read_pytest_no_cov_malformed_toml_returns_default(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text("garbage ===\n")
    assert read_pytest_no_cov(tmp_path) is True


def test_adjusted_tool_args_injects_no_cov_by_default(tmp_path: Path) -> None:
    _base, extra = adjusted_tool_args("pytest", [], ["tests/foo.py"], root=tmp_path)
    assert extra == ["--no-cov", "tests/foo.py"]


def test_adjusted_tool_args_respects_no_cov_false(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text("[pytest]\nno_cov = false\n")
    _base, extra = adjusted_tool_args("pytest", [], ["tests/foo.py"], root=tmp_path)
    assert extra == ["tests/foo.py"]


def test_adjusted_tool_args_skips_no_cov_when_user_passed_it(tmp_path: Path) -> None:
    _base, extra = adjusted_tool_args(
        "pytest", [], ["--cov=foo", "tests/foo.py"], root=tmp_path
    )
    assert "--no-cov" not in extra
    assert "--cov=foo" in extra


def test_configured_workers_parallelize_only_full_pytest_runs(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text("[pytest]\nworkers = 8\n")
    assert read_pytest_workers(tmp_path) == 8
    assert adjusted_tool_args("pytest", [], ["-q"], root=tmp_path)[1] == ["-n", "8", "-q"]
    assert adjusted_tool_args("pytest", [], ["tests/foo.py"], root=tmp_path)[1] == ["--no-cov", "tests/foo.py"]
    assert adjusted_tool_args("pytest", [], ["--numprocesses=2"], root=tmp_path)[1] == ["--numprocesses=2"]
    assert adjusted_tool_args("pytest", [], ["-pno:xdist"], root=tmp_path)[1] == ["-pno:xdist"]


def test_workers_default_to_serial(tmp_path: Path) -> None:
    assert read_pytest_workers(tmp_path) is None
    (tmp_path / ".st-check.toml").write_text("[pytest]\nworkers = 1\n")
    assert adjusted_tool_args("pytest", [], [], root=tmp_path)[1] == []


def test_adjusted_tool_args_unchanged_for_non_pytest(tmp_path: Path) -> None:
    _base, extra = adjusted_tool_args("ruff", [], ["check", "."], root=tmp_path)
    assert extra == ["check", "."]


@pytest.mark.parametrize(("name", "binary", "expected"), [
    ("ruff", "ruff", "light"), ("ruff", "sh", "heavy"),
    ("pytest", "pytest", "heavy"), ("biome", "biome", "light"),
    ("types", "ty", "heavy"), ("unknown", "ruff", "heavy"),
    ("actionlint", "actionlint", "light"), ("shellcheck", "shellcheck", "light"),
    ("squawk", "squawk", "light"), ("biome", "sh", "heavy"),
    ("tsc", "tsc", "heavy"), ("sqlfluff", "sqlfluff", "heavy"),
])
def test_only_direct_fast_linters_use_light_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    name: str, binary: str, expected: str,
) -> None:
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", tmp_path / "lane")
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    admitted = []

    def run(work: guard.HeavyWork, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        admitted.append(work.work_class)
        return subprocess.CompletedProcess(command, 0, "fixture complete", "")

    monkeypatch.setattr(guard.HeavyWork, "run", run)
    assert check._run_tool(name, {"binary": binary}, []) == 0
    assert admitted == [expected]
    result_line = capsys.readouterr().out.splitlines()[-1]
    assert "|queue_ms:" in result_line and "|execution_ms:" in result_line


@pytest.mark.parametrize(("measured", "expected"), [
    (None, "heavy"),
    ({"execution_ms": 6701.8, "max_rss_kb": 164524}, "light"),
    ({"execution_ms": 95_000.0, "max_rss_kb": 164524}, "heavy"),
    ({"execution_ms": 6701.8, "max_rss_kb": 3 * 1024 * 1024}, "heavy"),
])
def test_vitest_lane_follows_its_last_measured_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, measured: dict | None, expected: str,
) -> None:
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", tmp_path / "lane")
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    (tmp_path / ".git" / "st").mkdir(parents=True)
    store = tmp_path / ".git" / "st" / "lane-measurements.json"
    if measured is not None:
        store.write_text(json.dumps({"vitest": measured}))
    admitted = []

    def run(work: guard.HeavyWork, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        admitted.append(work.work_class)
        return subprocess.CompletedProcess(command, 0, "fixture complete", "")

    monkeypatch.setattr(guard.HeavyWork, "run", run)
    monkeypatch.setattr(check, "_resolve_command", lambda binary, *_args: [binary])
    check._run_tool("vitest", {"binary": "vitest"}, [])
    assert admitted == [expected]
    recorded = json.loads(store.read_text())["vitest"]
    assert recorded["execution_ms"] >= 0 and recorded["max_rss_kb"] >= 0
