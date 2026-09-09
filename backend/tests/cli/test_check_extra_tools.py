"""Scope optional workflow, shell, and Go checks without scanning vendored files."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.commands import check_dispatch
from cli.commands.check_runner import _workdir


def run_scoped(tmp_path: Path, name: str, changed: list[str], explicit: list[str] | None = None):
    runtime = Mock(spec=list(check_dispatch.CheckRuntime.__dataclass_fields__))
    runtime.resolve_repo_root.return_value = tmp_path
    runtime.changed_files.return_value = changed
    runtime.run_tool.return_value = 0
    result = check_dispatch.run_scoped_quality_tool(
        name, {"label": name.upper()}, explicit or [], changed_only=True, runtime=runtime
    )
    return result, runtime


@pytest.mark.parametrize(
    ("name", "included", "excluded"),
    [
        ("actionlint", ".github/workflows/ci.yml", "docker/compose.yml"),
        ("shellcheck", "scripts/build.sh", "vendor/scripts/build.sh"),
        ("shellcheck", "docker/scripts/build.sh", "scripts/generated/build.sh"),
    ],
)
def test_scoped_existing_files(tmp_path: Path, name: str, included: str, excluded: str) -> None:
    for rel in (included, excluded):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    result, runtime = run_scoped(tmp_path, name, [included, excluded, "scripts/deleted.sh"])
    assert result == 0
    assert runtime.run_tool.call_args.args[2] == [included]


def test_unrelated_changes_skip(tmp_path: Path) -> None:
    result, runtime = run_scoped(tmp_path, "actionlint", ["README.md"])
    assert result == 0
    runtime.run_tool.assert_not_called()


def test_explicit_arguments_override_scope(tmp_path: Path) -> None:
    result, runtime = run_scoped(tmp_path, "shellcheck", ["README.md"], ["custom.sh"])
    assert result == 0
    assert runtime.run_tool.call_args.args[2] == ["custom.sh"]


def test_go_changes_select_nearest_modules_including_deleted_sources(tmp_path: Path) -> None:
    for rel in ("hub/go.mod", "hub/nested/go.mod", "vendor/dependency/go.mod"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    result, runtime = run_scoped(tmp_path, "govulncheck", [
        "hub/pkg/deleted.go", "hub/go.sum", "hub/nested/main.go", "vendor/dependency/main.go",
    ])
    assert result == 0
    assert [call.args[1]["working_directory"] for call in runtime.run_tool.call_args_list] == ["hub", "hub/nested"]
    assert all(call.args[2] == ["./..."] for call in runtime.run_tool.call_args_list)


def test_module_workdir_is_used_and_confined_to_project(tmp_path: Path) -> None:
    module = tmp_path / "hub"
    module.mkdir()
    assert _workdir(tmp_path, {"working_directory": "hub"}) == module
    with pytest.raises(ValueError, match="inside the project"):
        _workdir(tmp_path, {"working_directory": ".."})
