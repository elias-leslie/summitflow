"""Changed-file selection must not hide Python regressions."""

from pathlib import Path

import pytest

from cli.commands.check_changed import _changed_args, _skip_reason


@pytest.mark.parametrize(
    "changed",
    [
        ["backend/app/service.py"],
        ["backend/app/service.py", "backend/tests/test_service.py"],
        ["backend/pytest.ini", "backend/tests/test_service.py"],
        ["backend/tests/conftest.py", "backend/tests/test_service.py"],
        ["backend/tests/test_deleted.py", "backend/tests/test_service.py"],
        ["backend/app/deleted.py", "backend/tests/test_service.py"],
    ],
)
def test_python_changes_retain_full_pytest_scope(tmp_path: Path, changed: list[str]) -> None:
    for path in ("backend/app/service.py", "backend/tests/test_service.py", "backend/tests/conftest.py"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    config: dict[str, object] = {"pass_path": False}
    args = _changed_args("pytest", tmp_path, tmp_path / "backend", config, changed)
    assert args == []
    assert _skip_reason(
        "pytest", config, changed_only=True, changed_files=changed, scoped_args=args
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
