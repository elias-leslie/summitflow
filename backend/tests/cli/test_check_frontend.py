"""Aggregate frontend checks follow declared tests, without inventing Vitest."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import typer

from app.utils.heavy_work import HeavyWork
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


def installed_vitest(root: Path) -> tuple[Path, Path]:
    """A local CLI declaring the same loader capability as prepared Vitest."""
    modules = root / "node_modules"
    package = modules / "vitest"
    chunks = package / "dist" / "chunks"
    chunks.mkdir(parents=True)
    (package / "package.json").write_text('{"name":"vitest"}')
    (chunks / "cac.fixture.js").write_text(
        'configLoader: { description: "Use bundle or runner", argument: "<loader>" }'
        'cache: { description: "Enable cache", default: true }'
    )
    binary = package / "vitest.mjs"
    binary.write_text(
        f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
        "assert sys.argv[1:] == ['run','--configLoader','runner','--cache=false']\n"
        "Path('executed-argv.json').write_text(json.dumps(sys.argv[1:]))\n"
    )
    binary.chmod(0o755)
    (modules / ".bin").mkdir()
    (modules / ".bin" / "vitest").symlink_to("../vitest/vitest.mjs")
    vite = modules / "vite"
    (vite / "dist" / "node" / "chunks").mkdir(parents=True)
    (vite / "package.json").write_text('{"name":"vite"}')
    (vite / "dist" / "node" / "chunks" / "config.js").write_text(
        'configLoader === "runner" ? runnerImportConfigFile(resolvedPath) : bundleConfigFile()'
    )
    return package, vite


def test_supported_vitest_executes_cache_free_loader_without_preparing_cache(tmp_path: Path) -> None:
    manifest(tmp_path, {"test": "vitest run"})
    installed_vitest(tmp_path)
    assert aggregate(tmp_path) == 0
    assert json.loads((tmp_path / "executed-argv.json").read_text()) == [
        "run", "--configLoader", "runner", "--cache=false",
    ]
    assert not (tmp_path / "node_modules" / ".vite-temp").exists()
    assert not (tmp_path / "node_modules" / ".vite").exists()


@pytest.mark.parametrize("unavailable", ["cli-option", "cache-option", "vite-loader", "vitest-manifest", "vite-manifest"])
def test_unsupported_vitest_keeps_existing_command(tmp_path: Path, unavailable: str) -> None:
    manifest(tmp_path, {"test": "vitest run"})
    package, vite = installed_vitest(tmp_path)
    if unavailable == "cli-option":
        (package / "dist" / "chunks" / "cac.fixture.js").write_text("run: {}")
    elif unavailable == "cache-option":
        (package / "dist" / "chunks" / "cac.fixture.js").write_text('configLoader: { description: "Use runner" }')
    elif unavailable == "vite-loader":
        (vite / "dist" / "node" / "chunks" / "config.js").write_text("bundleConfigFile()")
    else:
        ((package if unavailable == "vitest-manifest" else vite) / "package.json").write_text("{")
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    assert runner.call_args.args[1]["args"] == "run"


@pytest.mark.parametrize("script,hooks", [
    ("vitest run --configLoader bundle", {}),
    ("vitest run", {"pretest": "node prepare.cjs"}),
])
def test_supported_loader_preserves_declared_script_and_hooks(tmp_path: Path, script: str, hooks: dict[str, str]) -> None:
    manifest(tmp_path, {"test": script, **hooks})
    installed_vitest(tmp_path)
    runner = Mock(return_value=0)
    assert aggregate(tmp_path, runner) == 0
    assert runner.call_args.args[0] == "frontend-test"
    assert runner.call_args.args[1]["args"] == "run test"


def test_supported_loader_preserves_custom_check_arguments(tmp_path: Path) -> None:
    from cli.commands.check_frontend import frontend_test_config

    manifest(tmp_path, {"test": "vitest run"})
    installed_vitest(tmp_path)
    configured = {**CONFIG, "args": "run --cache=true --configLoader bundle"}
    assert frontend_test_config(tmp_path, tmp_path, configured) == ("vitest", configured)


def test_supported_loader_resolves_pnpm_vite_dependency(tmp_path: Path) -> None:
    from cli.commands.check_frontend import frontend_test_config

    manifest(tmp_path, {"test": "vitest run"})
    package, vite = installed_vitest(tmp_path)
    sibling = tmp_path / "node_modules" / ".pnpm" / "vitest-prepared" / "node_modules"
    sibling.mkdir(parents=True)
    package.rename(sibling / "vitest")
    vite.rename(sibling / "vite")
    package.symlink_to(".pnpm/vitest-prepared/node_modules/vitest", target_is_directory=True)
    vite.symlink_to(".pnpm/vitest-prepared/node_modules/vite", target_is_directory=True)
    selected = frontend_test_config(tmp_path, tmp_path, CONFIG)
    assert selected is not None
    assert selected[1]["args"] == "run --configLoader runner --cache=false"


@pytest.mark.parametrize("bound_launcher", [True, False])
def test_supported_loader_handles_pnpm_virtual_store_shim(tmp_path: Path, bound_launcher: bool) -> None:
    from cli.commands.check_frontend import frontend_test_config

    manifest(tmp_path, {"test": "vitest run"})
    package, vite = installed_vitest(tmp_path)
    sibling = tmp_path / "node_modules" / ".pnpm" / "vitest@4.1.11_vite@7.3.6" / "node_modules"
    sibling.mkdir(parents=True)
    package.rename(sibling / "vitest")
    vite.rename(sibling / "vite")
    package.symlink_to(".pnpm/vitest@4.1.11_vite@7.3.6/node_modules/vitest", target_is_directory=True)
    vite.symlink_to(".pnpm/vitest@4.1.11_vite@7.3.6/node_modules/vite", target_is_directory=True)
    binary = tmp_path / "node_modules" / ".bin" / "vitest"
    binary.unlink()
    if not bound_launcher:
        alternate = tmp_path / "node_modules" / ".pnpm" / "vitest@other" / "node_modules" / "vitest"
        alternate.mkdir(parents=True)
        (alternate / "vitest.mjs").write_text("// Different installed CLI\n")
    store_name = "vitest@4.1.11_vite@7.3.6" if bound_launcher else "vitest@other"
    binary.write_text(
        f'#!/bin/sh\nexec node "$basedir/../.pnpm/{store_name}/node_modules/vitest/vitest.mjs" "$@"\n'
    )

    selected = frontend_test_config(tmp_path, tmp_path, CONFIG)
    assert selected is not None
    assert selected[1]["args"] == ("run --configLoader runner --cache=false" if bound_launcher else "run")


@pytest.mark.parametrize("package_relative", [True, False])
def test_supported_loader_handles_pnpm_shell_shim_without_global_fallback(tmp_path: Path, package_relative: bool) -> None:
    from cli.commands.check_frontend import frontend_test_config

    manifest(tmp_path, {"test": "vitest run"})
    installed_vitest(tmp_path)
    binary = tmp_path / "node_modules" / ".bin" / "vitest"
    binary.unlink()
    target = '$basedir/../vitest/vitest.mjs' if package_relative else '/ambient/vitest.mjs'
    binary.write_text(f'#!/bin/sh\nexec node "{target}" "$@"\n')
    selected = frontend_test_config(tmp_path, tmp_path, CONFIG)
    assert selected is not None
    assert selected[1]["args"] == ("run --configLoader runner --cache=false" if package_relative else "run")


def test_implicit_tsc_skips_python_only_repository(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = Mock(return_value=0)
    tsc_config: dict[str, object] = {"label": "TSC", "args": "tsc --noEmit", "working_dir": "frontend"}
    with patch.object(check, "_resolve_repo_root", return_value=tmp_path), patch.object(
        check, "run_architecture_check", return_value=0
    ), patch.object(check, "_run_tool", runner):
        assert check._run_selected(["tsc"], {"tsc": tsc_config}, fix=False, changed_only=False) == 0
    runner.assert_not_called()
    assert "TSC:SKIP:tsc:no_tsconfig" in capsys.readouterr().out


def test_implicit_tsc_runs_when_root_config_exists(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "tsconfig.json").write_text("{}")
    runner = Mock(return_value=1)
    tsc_config: dict[str, object] = {"label": "TSC", "args": "tsc --noEmit", "working_dir": "frontend"}
    with patch.object(check, "_resolve_repo_root", return_value=tmp_path), patch.object(
        check, "run_architecture_check", return_value=0
    ), patch.object(check, "_run_tool", runner):
        assert check._run_selected(["tsc"], {"tsc": tsc_config}, fix=False, changed_only=False) == 1
    runner.assert_called_once()


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
        HeavyWork, "run", side_effect=FileNotFoundError("missing")
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
