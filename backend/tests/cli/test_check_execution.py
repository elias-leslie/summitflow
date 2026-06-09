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

from pathlib import Path

from cli.commands.check_execution import (
    adjusted_tool_args,
    read_pytest_no_cov,
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


def test_adjusted_tool_args_unchanged_for_non_pytest(tmp_path: Path) -> None:
    _base, extra = adjusted_tool_args("ruff", [], ["check", "."], root=tmp_path)
    assert extra == ["check", "."]
