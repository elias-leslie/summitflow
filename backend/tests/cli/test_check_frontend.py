"""Aggregate frontend checks follow declared tests, without inventing Vitest."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import typer

from cli.commands import check

CONFIG: dict[str, object] = {
    "label": "VITEST", "binary": "vitest", "args": "run", "working_dir": "frontend",
}


def manifest(root: Path, scripts: dict[str, str] | None = None, **fields: object) -> None:
    (root / "package.json").write_text(json.dumps({"scripts": scripts or {}, **fields}))


def aggregate(root: Path, runner: Mock | None = None) -> int:
    with patch.object(check, "_resolve_repo_root", return_value=root), patch.object(
        check, "run_architecture_check", return_value=0
    ):
        if runner is None:
            return check._run_selected(["vitest"], {"vitest": CONFIG}, fix=False, changed_only=False)
        with patch.object(check, "_run_tool", runner):
            return check._run_selected(["vitest"], {"vitest": CONFIG}, fix=False, changed_only=False)


@pytest.mark.parametrize("script", ["vitest", "vitest run"])
def test_existing_vitest_projects_keep_full_suite(tmp_path: Path, script: str) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    manifest(frontend, {"test": script}, devDependencies={"vitest": "^4.1.6"})
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    assert runner.call_args.args[0] == "vitest"
    assert runner.call_args.args[1]["args"] == "run"
    assert runner.call_args.args[2] == []


def test_monkey_fight_routes_declared_tsx_test(tmp_path: Path) -> None:
    manifest(tmp_path, {"test": "tsx --test tests/runtime-contracts.ts"}, packageManager="pnpm@10.28.0")
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    assert runner.call_args.args[0] == "frontend-test"
    assert runner.call_args.args[1]["binary"] == "pnpm"
    assert runner.call_args.args[1]["args"] == "run test"


@pytest.mark.parametrize("exit_code", [0, 7])
def test_node_test_script_really_executes_and_propagates_failure(tmp_path: Path, exit_code: int) -> None:
    manifest(tmp_path, {"test": "node --test contract.cjs"}, packageManager="npm@10.0.0")
    (tmp_path / "contract.cjs").write_text(
        "require('node:fs').writeFileSync('ran', process.env.CI + ':' + process.env.NODE_ENV);"
        f"process.exit({exit_code});"
    )
    assert aggregate(tmp_path) == int(exit_code != 0)
    assert (tmp_path / "ran").read_text() == "true:test"


def test_no_declared_tests_truthfully_skip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest(tmp_path, {"build": "vite build"})
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    runner.assert_not_called()
    assert "no_declared_tests" in capsys.readouterr().out


def test_vitest_dependency_without_script_still_runs(tmp_path: Path) -> None:
    manifest(tmp_path, devDependencies={"vitest": "^4"})
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    assert runner.call_args.args[0] == "vitest"


@pytest.mark.parametrize("script", ["node --test --watch contract.cjs", "vitest --watch", "vitest --ui"])
def test_interactive_scripts_fail_honestly(tmp_path: Path, script: str) -> None:
    manifest(tmp_path, {"test": script})
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 1
    runner.assert_not_called()


def test_ci_script_takes_precedence_over_watch(tmp_path: Path) -> None:
    manifest(tmp_path, {"test": "vitest --watch", "test:ci": "node --test contract.cjs"})
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    assert runner.call_args.args[1]["args"] == "run test:ci"


def test_malformed_manifest_fails(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{")
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 1
    runner.assert_not_called()


@pytest.mark.parametrize("name", ["vitest", "frontend-test"])
def test_missing_test_executable_never_skips(tmp_path: Path, name: str) -> None:
    with patch.object(check, "_resolve_repo_root", return_value=tmp_path), patch.object(
        check.subprocess, "run", side_effect=FileNotFoundError("missing")
    ):
        assert check._run_tool(name, {"binary": "missing"}, []) == 127


def test_missing_script_dependency_fails(tmp_path: Path) -> None:
    manifest(tmp_path, {"test": "nonexistent-test-tool-965831"})
    assert aggregate(tmp_path) == 1


def test_frontend_script_timeout_is_failure(tmp_path: Path) -> None:
    with patch.object(check, "_resolve_repo_root", return_value=tmp_path), patch.object(
        check, "_FRONTEND_TEST_TIMEOUT", 0.1
    ):
        assert check._run_tool("frontend-test", {"binary": "sh", "args": "-c 'sleep 60 & wait'"}, []) == 124


def test_custom_tests_run_conservatively_for_changed_inputs(tmp_path: Path) -> None:
    manifest(tmp_path, {"test": "node --test contract.cjs"})
    with patch.object(check, "_resolve_repo_root", return_value=tmp_path), patch.object(
        check, "run_architecture_check", return_value=0
    ), patch.object(check, "_changed_files", return_value=["fixtures/input.json"]), patch.object(
        check, "_run_tool", return_value=0
    ) as runner:
        assert check._run_selected(["vitest"], {"vitest": CONFIG}, fix=False, changed_only=True) == 0
    assert runner.call_args.args[0] == "frontend-test"


def test_vitest_package_hooks_are_preserved(tmp_path: Path) -> None:
    manifest(tmp_path, {"pretest": "node prepare.cjs", "test": "vitest", "posttest": "node verify.cjs"})
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    assert runner.call_args.args[0] == "frontend-test"
    assert runner.call_args.args[1]["args"] == "run test -- --run"


def test_explicit_vitest_does_not_route_to_package_script(tmp_path: Path) -> None:
    manifest(tmp_path, {"test": "node --test contract.cjs"})
    with patch.object(check, "_resolve_repo_root", return_value=tmp_path), patch.object(
        check, "_run_tool", return_value=127
    ) as runner:
        assert check._run_named_tool("vitest", ["vitest"], {"vitest": CONFIG}, changed_only=False, fix=False) == 127
    runner.assert_called_once_with("vitest", CONFIG, [])


def test_explicit_project_root_beats_actual_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli import config
    from cli.commands.check_runner import _resolve_repo_root

    cwd = tmp_path / "cwd"
    selected = tmp_path / "selected"
    cwd.mkdir()
    selected.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(config, "_project_override", "selected")
    with patch.object(config, "_fetch_projects_with_retry", return_value=[{"id": "selected", "root_path": str(selected)}]):
        assert _resolve_repo_root() == selected


def test_unknown_explicit_project_cannot_check_wrong_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli import config
    from cli.commands.check_runner import _resolve_repo_root

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_project_override", "missing")
    with patch.object(config, "_fetch_projects_with_retry", return_value=[]), pytest.raises(typer.BadParameter, match="registered root"):
        _resolve_repo_root()


def test_default_root_keeps_actual_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli import config
    from cli.commands.check_runner import _resolve_repo_root

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_project_override", None)
    assert _resolve_repo_root() == tmp_path
