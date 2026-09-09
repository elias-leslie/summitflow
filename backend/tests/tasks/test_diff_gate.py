"""Missing Git evidence must never count as successful completion."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.tasks.autonomous.exec_modules.diff_gate import check_diff_gate


def test_non_repository_blocks_completion(tmp_path: Path) -> None:
    result = check_diff_gate(str(tmp_path))
    assert result.passed is False
    assert result.files_changed == 0


@pytest.mark.parametrize("failure", [None, OSError("Git unavailable")])
def test_unreadable_diff_blocks_completion(failure: Exception | None) -> None:
    with (
        patch("app.tasks.autonomous.exec_modules.diff_gate.normalize_base_branch", return_value="main"),
        patch("app.tasks.autonomous.exec_modules.diff_gate._get_merge_base", return_value="base"),
        patch("app.tasks.autonomous.exec_modules.diff_gate._get_diff_stats", return_value=None, side_effect=failure),
    ):
        assert check_diff_gate("/workspace/project").passed is False


def test_observed_changes_pass_completion() -> None:
    with (
        patch("app.tasks.autonomous.exec_modules.diff_gate.normalize_base_branch", return_value="main"),
        patch("app.tasks.autonomous.exec_modules.diff_gate._get_merge_base", return_value="base"),
        patch("app.tasks.autonomous.exec_modules.diff_gate._get_diff_stats", return_value=(1, 2, 3)),
    ):
        result = check_diff_gate("/workspace/project")
    assert result.passed is True
    assert (result.files_changed, result.insertions, result.deletions) == (1, 2, 3)
