"""Changed-file selection must not hide Python regressions."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cli.commands.check_changed import (
    _changed_args,
    _pytest_requires_full_scope,
    _skip_reason,
)
from cli.commands.check_constants import _TOOL_SELECTIONS
from cli.commands.check_execution import adjusted_tool_args
from cli.main import app as main_app

VITEST: dict[str, object] = {
    "label": "VITEST", "binary": "vitest", "args": "run --cache=false", "working_dir": "frontend",
}


def test_python_changes_select_direct_importing_tests(tmp_path: Path) -> None:
    for path in ("backend/app/service.py", "backend/tests/test_service.py", "backend/tests/conftest.py"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    (tmp_path / "backend/tests/test_service.py").write_text(
        "from app import service\n"
    )
    config: dict[str, object] = {"pass_path": False}
    changed = ["backend/app/service.py"]
    args = _changed_args("pytest", tmp_path, tmp_path / "backend", config, changed)
    assert args == ["tests/test_service.py"]
    assert _skip_reason(
        "pytest", config, changed_only=True, changed_files=changed, scoped_args=args
    ) is None


def test_dependency_mapping_never_promotes_conftest_to_full_suite(tmp_path: Path) -> None:
    source = tmp_path / "backend/app/facade.pyi"
    conftest = tmp_path / "backend/tests/conftest.py"
    source.parent.mkdir(parents=True)
    conftest.parent.mkdir(parents=True)
    source.write_text("def exported() -> str: ...\n")
    conftest.write_text("from app import facade\n")

    assert _changed_args(
        "pytest",
        tmp_path,
        tmp_path / "backend",
        {"pass_path": False},
        ["backend/app/facade.pyi"],
    ) == []


@pytest.mark.parametrize(
    "changed",
    [
        ["backend/pytest.ini", "backend/tests/test_service.py"],
        ["backend/tests/conftest.py", "backend/tests/test_service.py"],
        ["backend/tests/test_deleted.py", "backend/tests/test_service.py"],
        ["backend/app/deleted.py", "backend/tests/test_service.py"],
    ],
)
def test_cross_cutting_or_deleted_python_changes_retain_full_scope(
    tmp_path: Path, changed: list[str]
) -> None:
    for path in ("backend/tests/test_service.py", "backend/tests/conftest.py"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    assert _changed_args(
        "pytest", tmp_path, tmp_path / "backend", {"pass_path": False}, changed
    ) == ["."]
    assert _pytest_requires_full_scope(tmp_path, changed)


def test_quick_cross_cutting_change_keeps_directly_changed_tests(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "backend/tests/test_service.py"
    test_file.parent.mkdir(parents=True)
    test_file.touch()
    changed = ["pyproject.toml", "backend/tests/test_service.py"]

    assert _changed_args(
        "pytest",
        tmp_path,
        tmp_path / "backend",
        {"pass_path": False},
        changed,
        defer_full_pytest=True,
    ) == ["tests/test_service.py"]


def test_quick_cross_cutting_change_without_direct_test_requires_acceptance(
    tmp_path: Path,
) -> None:
    changed = ["pyproject.toml"]
    args = _changed_args(
        "pytest",
        tmp_path,
        tmp_path / "backend",
        {"pass_path": False},
        changed,
        defer_full_pytest=True,
    )

    assert args == []
    assert _skip_reason(
        "pytest",
        {"pass_path": False},
        changed_only=True,
        changed_files=changed,
        scoped_args=args,
        deferred_full_pytest=True,
    ) == "requires_full_acceptance:cross_cutting_config"


def test_unmapped_implementation_skips_quick_suite_with_explicit_direction(
    tmp_path: Path,
) -> None:
    source = tmp_path / "backend/app/unmapped.py"
    source.parent.mkdir(parents=True)
    source.touch()
    changed = ["backend/app/unmapped.py"]
    args = _changed_args(
        "pytest", tmp_path, tmp_path / "backend", {"pass_path": False}, changed
    )
    assert args == []
    assert _skip_reason(
        "pytest",
        {"pass_path": False},
        changed_only=True,
        changed_files=changed,
        scoped_args=args,
    ) == "no_deterministic_focused_tests;run_targeted_pytest_or_full_acceptance"


def test_changed_tests_are_retained_when_an_implementation_is_unmapped(
    tmp_path: Path,
) -> None:
    source = tmp_path / "backend/app/unmapped.py"
    changed_test = tmp_path / "backend/tests/test_feature.py"
    source.parent.mkdir(parents=True)
    changed_test.parent.mkdir(parents=True)
    source.touch()
    changed_test.write_text("def test_feature():\n    assert True\n")
    changed = ["backend/app/unmapped.py", "backend/tests/test_feature.py"]

    args = _changed_args(
        "pytest", tmp_path, tmp_path / "backend", {"pass_path": False}, changed
    )

    assert args == ["tests/test_feature.py"]
    assert _skip_reason(
        "pytest",
        {"pass_path": False},
        changed_only=True,
        changed_files=changed,
        scoped_args=args,
    ) is None


def test_existing_tests_only_can_target_files(tmp_path: Path) -> None:
    target = tmp_path / "backend/tests/test_service.py"
    target.parent.mkdir(parents=True)
    target.touch()
    assert _changed_args(
        "pytest", tmp_path, tmp_path / "backend", {"pass_path": False},
        ["README.md", "backend/tests/test_service.py"],
    ) == ["tests/test_service.py"]


def test_docs_only_skip_unless_explicit_test_args() -> None:
    assert _skip_reason(
        "pytest", {"pass_path": False}, changed_only=True,
        changed_files=["README.md"], scoped_args=[],
    ) == "no_relevant_changed_paths"
    assert _skip_reason(
        "pytest", {"pass_path": False}, changed_only=True,
        changed_files=["README.md"], scoped_args=[], explicit_args=True,
    ) is None


def _quick_vitest(tmp_path: Path, changed: list[str], mode: str = "--quick") -> tuple[str, list[list[str]]]:
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    (frontend / "src/tray.ts").touch()
    calls: list[list[str]] = []

    def run_tool(name: str, config: dict[str, object], extra: list[str]) -> int:
        calls.append([name, *extra])
        return 0

    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value={"vitest": VITEST}),
        patch("cli.commands.check._changed_files", return_value=changed),
        patch("cli.commands.check._run_tool", side_effect=run_tool),
    ):
        result = CliRunner().invoke(main_app, ["check", mode, "--changed-only"])
    assert result.exit_code == 0, result.output
    return result.output, calls


def test_quick_selection_includes_vitest() -> None:
    assert "vitest" in _TOOL_SELECTIONS["--quick"][0]
    assert "vitest" in _TOOL_SELECTIONS["-q"][0]


def test_quick_changed_ts_runs_related_vitest_relative_to_frontend(tmp_path: Path) -> None:
    _, calls = _quick_vitest(tmp_path, ["backend/app/x.py", "frontend/src/tray.ts", "other/y.ts"])
    assert calls == [["vitest", "related", "src/tray.ts", "--run"]]


def test_related_vitest_replaces_configured_leading_run() -> None:
    base, extra = adjusted_tool_args("vitest", ["run", "--cache=false"], ["related", "src/tray.ts", "--run"])
    assert [*base, *extra] == ["related", "src/tray.ts", "--run", "--cache=false"]


def test_quick_without_frontend_source_changes_skips_vitest(tmp_path: Path) -> None:
    output, calls = _quick_vitest(tmp_path, ["backend/app/x.py", "README.md"])
    assert calls == []
    assert "VITEST:SKIP:vitest:no_frontend_source_changes" in output


def test_quick_vitest_config_change_defers_full_suite(tmp_path: Path) -> None:
    output, calls = _quick_vitest(tmp_path, ["frontend/vitest.config.ts"])
    assert calls == []
    assert "VITEST:DEFER:vitest:requires_full_acceptance:cross_cutting_config" in output
    assert "VITEST:SKIP:vitest:requires_full_acceptance:cross_cutting_config" in output


def test_quick_lockfile_change_defers_but_keeps_related_sources(tmp_path: Path) -> None:
    output, calls = _quick_vitest(tmp_path, ["pnpm-lock.yaml", "frontend/src/tray.ts"])
    assert "VITEST:DEFER:vitest:requires_full_acceptance:cross_cutting_config" in output
    assert calls == [["vitest", "related", "src/tray.ts", "--run"]]


def test_check_vitest_config_change_runs_full_suite(tmp_path: Path) -> None:
    _, calls = _quick_vitest(tmp_path, ["frontend/package.json", "frontend/src/tray.ts"], mode="--check")
    assert calls == [["vitest"]]


def test_quick_package_script_frontend_test_is_deferred(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value={"vitest": VITEST}),
        patch("cli.commands.check._changed_files", return_value=["frontend/a.ts"]),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = CliRunner().invoke(main_app, ["check", "--quick", "--changed-only"])
    assert result.exit_code == 0, result.output
    assert "TEST:DEFER:frontend-test:requires_full_acceptance:package_script" in result.output
    run_tool.assert_not_called()
