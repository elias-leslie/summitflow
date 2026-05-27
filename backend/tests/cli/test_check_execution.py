"""Tests for st check tool-execution env helpers.

Regression coverage for the fleet-wide vitest breakage: when st check inherits
NODE_ENV=production (e.g. launched from an electron-vite/npm prod context),
vitest loads the production React build where React.act is undefined and
@testing-library throws "React.act is not a function". tool_env must normalize
NODE_ENV to "test" for vitest so every project's frontend suite runs correctly
without per-project vitest.config drift.
"""

from __future__ import annotations

from pathlib import Path

from cli.commands.check_execution import tool_env


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
