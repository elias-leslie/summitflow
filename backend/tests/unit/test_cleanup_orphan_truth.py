from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.api.models.git_models import BranchInfo
from app.utils._git_branch_cleanup import OrphanBranchAssessment, assess_orphan_task_branches
from app.utils.git_helpers import build_repo_workspace_summary
from cli.commands.cleanup import app as cleanup_app
from cli.commands.cleanup import build_cleanup_status_payload
from cli.commands.cleanup_salvage import validate_salvage_candidate

runner = CliRunner()
REPO_PATH = Path("/tmp/test-project")
EXISTING_TASK_ID = "task-d530fc1f"
MISSING_TASK_ID = "task-missing000"
EXISTING_BRANCH = f"{EXISTING_TASK_ID}/main"
MISSING_BRANCH = f"{MISSING_TASK_ID}/main"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


@pytest.fixture
def orphan_branches() -> list[BranchInfo]:
    return [
        BranchInfo(
            name=EXISTING_BRANCH,
            is_current=False,
            has_checkpoint=False,
            repo_name="test-project",
            project_id="test-project",
            task_id=EXISTING_TASK_ID,
        ),
        BranchInfo(
            name=MISSING_BRANCH,
            is_current=False,
            has_checkpoint=False,
            repo_name="test-project",
            project_id="test-project",
            task_id=MISSING_TASK_ID,
        ),
    ]


@pytest.fixture
def patch_orphan_git(mocker, orphan_branches: list[BranchInfo]):
    git_branches = mocker.Mock()
    git_branches._detect_base_branch.return_value = "main"
    git_branches.get_all_branches.return_value = orphan_branches
    git_branches.get_active_checkpoints.return_value = []
    git_branches._get_merged_branches.return_value = []
    git_branches.list_equivalent_orphan_task_branches.return_value = []
    git_branches.list_prunable_task_branches.return_value = []
    git_branches.assess_orphan_task_branches.side_effect = assess_orphan_task_branches
    git_branches._branch_commits_ahead.return_value = 1
    git_branches._branch_commits_behind.return_value = 2
    git_branches._branch_ahead_diff_paths.return_value = ["backend/app.py"]
    git_branches._branch_diff_paths.return_value = ["backend/app.py"]
    mocker.patch("app.utils._git_branch_cleanup._git_branches_module", return_value=git_branches)
    return git_branches


def _assessment_by_task(items: list[OrphanBranchAssessment]) -> dict[str, OrphanBranchAssessment]:
    return {item.task_id: item for item in items}


def test_branch_ahead_diff_paths_exclude_base_only_drift(tmp_path: Path) -> None:
    from app.utils._git_branches import (
        _branch_ahead_diff_paths,
        _branch_commits_ahead,
        _branch_commits_behind,
        _branch_diff_paths,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _git(repo, "checkout", "-b", EXISTING_BRANCH)
    (repo / "task.txt").write_text("task\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "task work")

    _git(repo, "checkout", "main")
    (repo / "main.txt").write_text("main drift\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "main drift")

    assert _branch_commits_ahead(repo, EXISTING_BRANCH, "main") == 1
    assert _branch_commits_behind(repo, EXISTING_BRANCH, "main") == 1
    assert sorted(_branch_diff_paths(repo, EXISTING_BRANCH, "main")) == ["main.txt", "task.txt"]
    assert sorted(_branch_ahead_diff_paths(repo, EXISTING_BRANCH, "main")) == ["task.txt"]


def test_assess_orphan_task_branches_marks_existing_and_unreadable_tasks_for_review(
    mocker,
    orphan_branches: list[BranchInfo],
    patch_orphan_git,
) -> None:
    task_payloads = {
        EXISTING_TASK_ID: {"id": EXISTING_TASK_ID, "status": "in_progress"},
        MISSING_TASK_ID: None,
        "task-invalid-status": {"id": "task-invalid-status"},
        "task-bad-shape": object(),
    }

    extra_branches = [
        *orphan_branches,
        BranchInfo(
            name="task-invalid-status/main",
            is_current=False,
            has_checkpoint=False,
            repo_name="test-project",
            project_id="test-project",
            task_id="task-invalid-status",
        ),
        BranchInfo(
            name="task-bad-shape/main",
            is_current=False,
            has_checkpoint=False,
            repo_name="test-project",
            project_id="test-project",
            task_id="task-bad-shape",
        ),
        BranchInfo(
            name="task-error/main",
            is_current=False,
            has_checkpoint=False,
            repo_name="test-project",
            project_id="test-project",
            task_id="task-error",
        ),
    ]
    patch_orphan_git.get_all_branches.return_value = extra_branches

    def fake_get_task(task_id: str):
        if task_id == "task-error":
            raise RuntimeError("boom")
        return task_payloads.get(task_id)

    mocker.patch("app.storage.tasks.get_task", side_effect=fake_get_task)

    assessments = _assessment_by_task(assess_orphan_task_branches(REPO_PATH, branches=extra_branches, base_branch="main"))

    assert assessments[EXISTING_TASK_ID].resolution == "review"
    assert assessments[EXISTING_TASK_ID].task_status == "in_progress"
    assert assessments[EXISTING_TASK_ID].task_token == "task:in_progress"
    assert assessments[EXISTING_TASK_ID].commits_ahead == 1
    assert assessments[EXISTING_TASK_ID].commits_behind == 2
    assert assessments[EXISTING_TASK_ID].files_changed == 1
    assert assessments[MISSING_TASK_ID].resolution == "salvage"
    assert assessments[MISSING_TASK_ID].task_status is None
    assert assessments[MISSING_TASK_ID].task_token == "task:missing"
    assert assessments["task-invalid-status"].resolution == "review"
    assert assessments["task-invalid-status"].task_status is None
    assert assessments["task-invalid-status"].task_token == "task:unreadable"
    assert assessments["task-bad-shape"].resolution == "review"
    assert assessments["task-bad-shape"].task_status is None
    assert assessments["task-bad-shape"].task_token == "task:unreadable"
    assert assessments["task-error"].resolution == "review"
    assert assessments["task-error"].task_status is None
    assert assessments["task-error"].task_token == "task:unreadable"


def test_build_repo_workspace_summary_uses_shared_orphan_assessment_truth(
    mocker,
    orphan_branches: list[BranchInfo],
    patch_orphan_git,
) -> None:
    mocker.patch(
        "app.storage.tasks.get_task",
        side_effect=lambda task_id: {"id": task_id, "status": "in_progress"} if task_id == EXISTING_TASK_ID else None,
    )
    mocker.patch("app.utils._git_branch_cleanup.git_core.has_uncommitted_changes", return_value=False)

    summary = build_repo_workspace_summary(REPO_PATH, branches=orphan_branches, active_checkpoints=[])

    assert summary.orphan_branch_names == [EXISTING_BRANCH, MISSING_BRANCH]
    assert summary.salvage_task_ids == [MISSING_TASK_ID]
    assert summary.review_orphan_task_ids == [EXISTING_TASK_ID]
    assert EXISTING_TASK_ID not in summary.salvage_task_ids
    assert set(summary.salvage_task_ids).isdisjoint(summary.review_orphan_task_ids)
    assert summary.orphan_details[0].commits_ahead == 1
    assert summary.orphan_details[0].commits_behind == 2
    assert summary.orphan_details[0].files_changed == 1


def test_build_cleanup_status_payload_keeps_existing_task_orphans_out_of_salvage(
    mocker,
    orphan_branches: list[BranchInfo],
    patch_orphan_git,
) -> None:
    mocker.patch("cli.commands.cleanup.get_project_id", return_value="test-project")
    mocker.patch("cli.commands.cleanup.get_active_checkpoints", return_value=[])
    mocker.patch("cli.commands.cleanup._iter_target_repos", return_value=[REPO_PATH])
    mocker.patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[])
    mocker.patch("cli.commands.cleanup.find_snapshot_residue", return_value=[])
    mocker.patch("app.utils._git_branch_cleanup.git_core.has_uncommitted_changes", return_value=False)
    mocker.patch("app.storage.tasks.get_task", side_effect=lambda task_id: {"id": task_id, "status": "in_progress"} if task_id == EXISTING_TASK_ID else None)

    from app.utils._git_branch_cleanup import (
        build_repo_workspace_summary as real_build_repo_workspace_summary,
    )

    mocker.patch(
        "cli.commands.cleanup.build_repo_workspace_summary",
        side_effect=lambda repo_path: real_build_repo_workspace_summary(
            repo_path,
            branches=orphan_branches,
            active_checkpoints=[],
        ),
    )

    payload = build_cleanup_status_payload(False, project_id_override="test-project")

    repo = payload["repositories"][0]
    assert repo["orphan_branch_names"] == [EXISTING_BRANCH, MISSING_BRANCH]
    assert repo["salvage_task_ids"] == [MISSING_TASK_ID]
    assert repo["review_orphan_task_ids"] == [EXISTING_TASK_ID]
    assert EXISTING_TASK_ID not in repo["salvage_task_ids"]
    assert set(repo["salvage_task_ids"]).isdisjoint(repo["review_orphan_task_ids"])


def test_cleanup_inspect_orphans_and_salvage_follow_shared_assessment_truth(mocker) -> None:
    assessments = [
        OrphanBranchAssessment(
            branch_name=EXISTING_BRANCH,
            task_id=EXISTING_TASK_ID,
            resolution="review",
            task_status="in_progress",
            task_token="task:in_progress",
            commits_ahead=1,
            files_changed=1,
            has_node_modules_artifact=False,
        ),
        OrphanBranchAssessment(
            branch_name=MISSING_BRANCH,
            task_id=MISSING_TASK_ID,
            resolution="salvage",
            task_status=None,
            task_token="task:missing",
            commits_ahead=1,
            files_changed=1,
            has_node_modules_artifact=False,
        ),
        OrphanBranchAssessment(
            branch_name="task-unreadable/main",
            task_id="task-unreadable",
            resolution="review",
            task_status=None,
            task_token="task:unreadable",
            commits_ahead=1,
            files_changed=1,
            has_node_modules_artifact=False,
        ),
    ]
    mocker.patch("cli.commands.cleanup._iter_target_repos", return_value=[REPO_PATH])
    mocker.patch("cli.commands.cleanup.assess_orphan_task_branches", return_value=assessments)
    mock_recover = mocker.patch("cli.commands.cleanup.recover_orphan_task")

    inspect_result = runner.invoke(cleanup_app, ["inspect-orphans"])

    assert inspect_result.exit_code == 0
    assert f"test-project {EXISTING_TASK_ID} branch:{EXISTING_BRANCH} resolution:review task:in_progress" in inspect_result.stdout
    assert f"test-project {MISSING_TASK_ID} branch:{MISSING_BRANCH} resolution:salvage task:missing" in inspect_result.stdout
    assert "task-unreadable branch:task-unreadable/main resolution:review task:unreadable" in inspect_result.stdout

    reject_result = runner.invoke(cleanup_app, ["salvage", EXISTING_TASK_ID])

    assert reject_result.exit_code == 1
    assert "task record still exists" in reject_result.stderr
    assert "task context/manual reconcile" in reject_result.stderr
    mock_recover.assert_not_called()

    accept_result = runner.invoke(cleanup_app, ["salvage", MISSING_TASK_ID])

    assert accept_result.exit_code == 0
    mock_recover.assert_called_once()


def test_validate_salvage_candidate_rejects_existing_and_unreadable_tasks(capsys) -> None:
    assert not validate_salvage_candidate(
        OrphanBranchAssessment(
            branch_name=EXISTING_BRANCH,
            task_id=EXISTING_TASK_ID,
            resolution="review",
            task_status="queued",
            task_token="task:queued",
            commits_ahead=1,
            files_changed=1,
            has_node_modules_artifact=False,
        ),
        EXISTING_TASK_ID,
    )
    existing_output = capsys.readouterr()
    assert "task record still exists" in existing_output.err
    assert "task context/manual reconcile" in existing_output.err

    assert not validate_salvage_candidate(
        OrphanBranchAssessment(
            branch_name="task-unreadable/main",
            task_id="task-unreadable",
            resolution="review",
            task_status=None,
            task_token="task:unreadable",
            commits_ahead=1,
            files_changed=1,
            has_node_modules_artifact=False,
        ),
        "task-unreadable",
    )
    unreadable_output = capsys.readouterr()
    assert "task record still exists" in unreadable_output.err
    assert "task context/manual reconcile" in unreadable_output.err
