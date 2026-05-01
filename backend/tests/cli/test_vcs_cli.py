from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands import vcs
from cli.output_context import OutputContext

runner = CliRunner()


def _cleanup_payload(needs_cleanup: bool = False) -> dict[str, object]:
    return {
        "summary": {
            "repos": 1,
            "repos_needing_cleanup": 1 if needs_cleanup else 0,
            "active_checkpoints": 0,
            "dirty_checkpoints": 0,
            "stale_checkpoints": 0,
            "snapshot_residue": 0,
            "orphan_task_branches": 0,
            "prunable_task_branches": 0,
        },
        "repositories": [
            {
                "project_id": "repo",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "stale_checkpoints": 0,
                "snapshot_residue": 0,
                "orphan_task_branches": 0,
                "prunable_task_branches": 0,
                "needs_cleanup": needs_cleanup,
            }
        ],
    }


def test_doctor_prints_one_compact_ok_line(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with (
        patch.object(vcs, "_target_repos", return_value=[repo]),
        patch.object(vcs, "_fetch_jj_repos", return_value=[]),
        patch.object(
            vcs,
            "_status_rows",
            return_value=[
                {
                    "name": "repo",
                    "path": str(repo),
                    "uncommitted": 0,
                    "ahead": 0,
                    "behind": 0,
                }
            ],
        ),
        patch.object(vcs, "_jj_rows", return_value=[]),
        patch.object(vcs, "_cleanup_payload", return_value=_cleanup_payload(False)),
        patch.object(vcs, "_discover_unmanaged_repos", return_value=[]),
        patch.object(vcs, "_safe_task_ref_rows", return_value=[]),
    ):
        result = runner.invoke(vcs.app, ["doctor"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    assert result.stdout.splitlines()[0].startswith("VCS:OK repos=1")
    assert len(result.stdout.splitlines()) == 1


def test_doctor_exits_two_with_exact_blockers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with (
        patch.object(vcs, "_target_repos", return_value=[repo]),
        patch.object(vcs, "_fetch_jj_repos", return_value=[]),
        patch.object(
            vcs,
            "_status_rows",
            return_value=[
                {
                    "name": "repo",
                    "path": str(repo),
                    "uncommitted": 1,
                    "ahead": 0,
                    "behind": 0,
                }
            ],
        ),
        patch.object(vcs, "_jj_rows", return_value=[]),
        patch.object(vcs, "_cleanup_payload", return_value=_cleanup_payload(True)),
        patch.object(vcs, "_discover_unmanaged_repos", return_value=[tmp_path / "extra"]),
        patch.object(
            vcs,
            "_safe_task_ref_rows",
            return_value=[{"repo": "repo", "kind": "local", "name": "task/task-1"}],
        ),
    ):
        result = runner.invoke(vcs.app, ["doctor"], obj=OutputContext(compact=True))

    assert result.exit_code == 2
    assert "VCS:ISSUES" in result.stdout
    assert "BLOCKER:repo:dirty:uncommitted:1" in result.stdout
    assert "BLOCKER:repo:cleanup:" in result.stdout
    assert "BLOCKER:repo:task_refs:safe_local:1 safe_remote:0" in result.stdout
    assert "BLOCKER:extra:unmanaged:" in result.stdout


def test_reconcile_runs_safe_steps_then_reports_doctor_result(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sync_result = MagicMock()
    sync_result.model_dump.return_value = {"repo": "repo", "status": "up_to_date"}
    with (
        patch.object(vcs, "_target_repos", return_value=[repo]),
        patch.object(vcs, "_register_unmanaged", return_value=[{"repo": "extra", "status": "registered"}]),
        patch.object(vcs, "pull_repository", return_value=sync_result) as mock_pull,
        patch.object(vcs, "_cleanup_stale_checkpoint_metadata", return_value=1),
        patch.object(vcs, "cleanup_safe_git_residue", return_value=(1, 2, 3, 4, 5, 6)),
        patch.object(
            vcs,
            "_run_doctor",
            return_value=(
                {
                    "summary": {
                        "repos": 1,
                        "dirty": 0,
                        "ahead": 0,
                        "behind": 0,
                        "unpublished": 0,
                        "conflicts": 0,
                        "cleanup": 0,
                        "unmanaged": 0,
                        "task_refs": 0,
                    }
                },
                [],
                tmp_path / "details.txt",
            ),
        ),
    ):
        result = runner.invoke(vcs.app, ["reconcile"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    mock_pull.assert_called_once_with(repo)
    assert "VCS-RECONCILE:OK repos=1" in result.stdout
