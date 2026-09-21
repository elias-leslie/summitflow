"""Changed-file selection must not hide Python regressions."""

from pathlib import Path

import pytest

from cli.commands.check_changed import _changed_args, _skip_reason


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
