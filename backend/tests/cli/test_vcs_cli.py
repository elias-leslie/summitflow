from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands import vcs
from cli.output_context import OutputContext

runner = CliRunner()


def test_publish_requires_explicit_now():
    with patch("app.tasks.backup_manual_publish.publish_project_now") as publish:
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", "a" * 40])
    assert result.exit_code == 2
    assert "requires --now" in result.stdout
    publish.assert_not_called()


def test_publish_exact_source_only_and_no_hygiene_actions():
    with (
        patch("app.tasks.backup_manual_publish.publish_project_now", return_value={
            "publication_complete": True, "evidence_recorded": True, "health": {"state": "verified"},
        }) as publish,
        patch.object(vcs, "pull_repository") as pull,
        patch.object(vcs, "cleanup_safe_git_residue") as cleanup,
    ):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", "a" * 40, "--now"])
    assert result.exit_code == 0
    publish.assert_called_once_with("source", "a" * 40)
    pull.assert_not_called()
    cleanup.assert_not_called()


def test_retained_findings_do_not_relabel_successful_explicit_publication():
    with patch("app.tasks.backup_manual_publish.publish_project_now", return_value={
        "publication_complete": True, "evidence_recorded": True, "health": {"state": "blocked"},
    }):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", "a" * 40, "--now"])
    assert result.exit_code == 0


def test_publish_never_prints_unexpected_diagnostics():
    with patch("app.tasks.backup_manual_publish.publish_project_now", side_effect=RuntimeError("private-token-diagnostic")):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", "a" * 40, "--now"])
    assert result.exit_code == 2
    assert "private-token-diagnostic" not in result.stdout


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
        patch.object(vcs, "fetch_repository") as fetch,
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
        patch.object(vcs, "_cleanup_payload", return_value=_cleanup_payload(False)),
        patch.object(vcs, "_discover_unmanaged_repos", return_value=[]),
        patch.object(vcs, "_safe_task_ref_rows", return_value=[]),
    ):
        result = runner.invoke(vcs.app, ["doctor"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    assert result.stdout.splitlines()[0].startswith("VCS:OK repos=1")
    assert len(result.stdout.splitlines()) == 1
    fetch.assert_not_called()


def test_unpublished_local_history_is_information_not_a_blocker() -> None:
    git_rows = [{"name": "repo", "path": "/repo", "ahead": 12, "behind": 0, "uncommitted": 0}]
    assert vcs._issues(git_rows, _cleanup_payload(), [], []) == []


def test_doctor_exits_two_with_exact_blockers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with (
        patch.object(vcs, "_target_repos", return_value=[repo]),
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


def test_discover_unmanaged_repos_ignores_config_mirrors(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    extra = projects / "extra"
    claude_config = projects / "claude-config"
    codex_config = projects / "codex-config"
    for repo in (extra, claude_config, codex_config):
        (repo / ".git").mkdir(parents=True)

    with patch.object(vcs, "get_projects_base_dir", return_value=projects):
        assert vcs._discover_unmanaged_repos([]) == [extra]


def test_pending_publication_is_not_reported_complete():
    with patch("app.tasks.backup_manual_publish.publish_project_now", return_value={
        "publication_complete": False, "pushed": True, "evidence_recorded": True, "ci": {"state": "pending"},
    }):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", "a" * 40, "--now"])
    assert result.exit_code == 2


def test_doctor_fetches_git_only_when_requested(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    fetched = MagicMock()
    fetched.model_dump.return_value = {"name": "repo", "status": "updated"}
    with (
        patch.object(vcs, "_target_repos", return_value=[repo]),
        patch.object(vcs, "fetch_repository", return_value=fetched) as fetch,
        patch.object(vcs, "_status_rows", return_value=[]),
        patch.object(vcs, "_cleanup_payload", return_value=_cleanup_payload()),
        patch.object(vcs, "_discover_unmanaged_repos", return_value=[]),
        patch.object(vcs, "_safe_task_ref_rows", return_value=[]),
    ):
        result = runner.invoke(vcs.app, ["doctor", "--fetch"], obj=OutputContext(compact=True))
    assert result.exit_code == 0
    fetch.assert_called_once_with(repo)


def test_publish_now_honors_mirror_mode_and_workflow_authority():
    with (
        patch("app.tasks.nightly_publication.publication_mode", return_value="mirror"),
        patch("app.tasks.backup_manual_publish.publish_project_now", return_value={
            "publication_complete": True, "evidence_recorded": True, "health": {"state": "verified"},
        }) as publish,
    ):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", "a" * 40, "--now",
                                         "--authorize-workflow", ".github/workflows/ci.yml"])
    assert result.exit_code == 0
    publish.assert_called_once_with("source", "a" * 40, authorized_workflows=(".github/workflows/ci.yml",),
                                    publication_mode="mirror")


def test_publication_reobserve_replays_retained_receipt_only_on_request():
    config = MagicMock(project_id="project")
    health = {"project_id": "project", "state": "verified", "source_commit": "a" * 40, "observed_at": "now",
              "ci_state": "success", "reason": "source_publication_verified", "repair_task_id": None}
    with (
        patch("cli.config.get_config_optional", return_value=config),
        patch("app.tasks.nightly_publication.publication_mode", return_value="nightly"),
        patch("app.tasks.nightly_publication.publication_hold", return_value=None),
        patch("app.services.publication_health.get_project_publication_health", return_value=health),
        patch("app.services.publication_health.reobserve_retained_publication", return_value={
            "state": "verified", "source_commit": "a" * 40, "evidence": "/receipt.json"}) as replay,
    ):
        plain = runner.invoke(vcs.app, ["publication"])
        replay.assert_not_called()
        result = runner.invoke(vcs.app, ["publication", "--reobserve"])
    assert plain.exit_code == 0 and result.exit_code == 0
    replay.assert_called_once_with("project")
    assert "Reobserved: verified; source=aaaaaaaaaaaa; evidence=/receipt.json" in result.stdout
