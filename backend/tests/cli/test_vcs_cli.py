from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.commands import vcs
from cli.output_context import OutputContext

runner = CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A registered project checkout with two commits; coordination is out of scope here."""
    import subprocess

    root = tmp_path / "project"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "one"],
                 ["commit", "-q", "--allow-empty", "-m", "two"]):
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args], cwd=root, check=True)
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda project_id: str(root) if project_id == "source" else None)
    monkeypatch.setattr(vcs, "_coord_guard", lambda *_: None)
    monkeypatch.setattr("app.tasks.nightly_publication.publication_hold", lambda _project_id: None)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    return root, head


_DONE = {"publication_complete": True, "evidence_recorded": True, "status": "published"}


def test_publish_resolves_a_short_sha_and_does_no_hygiene(project):
    _root, head = project
    with (
        patch("app.tasks.backup_manual_publish.publish_project_now", return_value=_DONE) as publish,
        patch.object(vcs, "pull_repository") as pull,
        patch.object(vcs, "cleanup_safe_git_residue") as cleanup,
    ):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", head[:9]])
    assert result.exit_code == 0, result.stdout
    publish.assert_called_once_with("source", head, authorized_workflows=())
    pull.assert_not_called()
    cleanup.assert_not_called()


def test_publish_defaults_source_from_cwd_and_sha_from_the_hourly_selection(project):
    root, head = project
    with (
        patch("cli.config.get_config_optional", return_value=MagicMock(project_id="source")),
        patch("app.tasks.nightly_publication.publication_hold", return_value=None),
        patch("app.tasks.nightly_publication.select_candidate", return_value={"action": "publish", "sha": head}) as select,
        patch("app.tasks.backup_manual_publish.publish_project_now", return_value=_DONE) as publish,
    ):
        result = runner.invoke(vcs.app, ["publish", "--now"])  # --now is still accepted
    assert result.exit_code == 0, result.stdout
    assert select.call_args.args[:2] == ("source", root)
    publish.assert_called_once_with("source", head, authorized_workflows=())


@pytest.mark.parametrize(("reason", "code"), [("up_to_date", 0), ("no_accepted_commit", 2)])
def test_publish_with_nothing_selected_explains_why(project, reason, code):
    with (
        patch("app.tasks.nightly_publication.publication_hold", return_value=None),
        patch("app.tasks.nightly_publication.select_candidate", return_value={"action": "skip", "reason": reason}),
        patch("app.tasks.backup_manual_publish.publish_project_now") as publish,
    ):
        result = runner.invoke(vcs.app, ["publish", "--source", "source"])
    assert result.exit_code == code and reason in result.stdout
    publish.assert_not_called()


def test_publish_refuses_unknown_project_or_commit(project):
    with patch("app.tasks.backup_manual_publish.publish_project_now") as publish:
        unknown = runner.invoke(vcs.app, ["publish", "--source", "elsewhere"])
        bad_sha = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", "f" * 12])
    assert unknown.exit_code == 2 and "No registered project" in unknown.stdout
    assert bad_sha.exit_code == 2 and "Unknown commit" in bad_sha.stdout
    publish.assert_not_called()


def test_explicit_sha_cannot_publish_past_an_owner_hold(project, monkeypatch):
    import subprocess

    root, head = project
    released = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    with patch("app.tasks.backup_manual_publish.publish_project_now", return_value=_DONE) as publish:
        monkeypatch.setattr("app.tasks.nightly_publication.publication_hold",
                            lambda _project_id: {"through": None, "reason": "embargo"})
        everything = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", head])
        monkeypatch.setattr("app.tasks.nightly_publication.publication_hold",
                            lambda _project_id: {"through": released, "reason": "embargo"})
        later = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", head])
        allowed = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", released[:10]])
    assert everything.exit_code == 2 and "held (embargo)" in everything.stdout
    assert later.exit_code == 2 and "--release" in later.stdout
    assert allowed.exit_code == 0, allowed.stdout
    publish.assert_called_once_with("source", released, authorized_workflows=())


def test_publish_forwards_workflow_authority(project):
    _root, head = project
    with patch("app.tasks.backup_manual_publish.publish_project_now", return_value=_DONE) as publish:
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", head,
                                         "--authorize-workflow", ".github/workflows/ci.yml"])
    assert result.exit_code == 0
    publish.assert_called_once_with("source", head, authorized_workflows=(".github/workflows/ci.yml",))


def test_publish_never_prints_unexpected_diagnostics(project):
    _root, head = project
    with patch("app.tasks.backup_manual_publish.publish_project_now", side_effect=RuntimeError("private-token-diagnostic")):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", head])
    assert result.exit_code == 2
    assert "private-token-diagnostic" not in result.stdout


def test_pending_publication_is_not_reported_complete(project):
    _root, head = project
    with patch("app.tasks.backup_manual_publish.publish_project_now", return_value={
        "publication_complete": False, "pushed": False, "evidence_recorded": True, "reason": "source_acceptance_required",
    }):
        result = runner.invoke(vcs.app, ["publish", "--source", "source", "--sha", head])
    assert result.exit_code == 2 and "source_acceptance_required" in result.stdout


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


def _git_repo(path: Path):
    import subprocess

    path.mkdir(parents=True)

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (path / "app.py").write_text("before\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    return git


def test_doctor_current_outside_a_managed_repo_errors_instead_of_auditing_another(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(vcs, "_get_managed_repos", lambda: [tmp_path / "first", repo])
    monkeypatch.chdir(elsewhere)
    result = runner.invoke(vcs.app, ["doctor", "--current"], obj=OutputContext(compact=True))
    assert result.exit_code == 2
    assert "not inside one" in result.output


def test_doctor_current_from_a_worktree_audits_its_repo(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    git = _git_repo(repo)
    git("worktree", "add", "-q", "--detach", str(tmp_path / "wt"))
    monkeypatch.setattr(vcs, "_get_managed_repos", lambda: [tmp_path / "first", repo])
    monkeypatch.chdir(tmp_path / "wt")
    assert vcs._target_repos(False) == [repo]


def test_doctor_reports_informal_worktrees_with_location_and_work(tmp_path, monkeypatch) -> None:
    workspaces = tmp_path / "workspaces"
    repo = workspaces / "projects" / "repo"
    git = _git_repo(repo)
    clean = workspaces / "worktrees" / "clean"
    git("worktree", "add", "-q", "--detach", str(clean))
    outside = tmp_path / "scratch" / "wt"
    git("worktree", "add", "-q", "-b", "side", str(outside))
    (outside / "app.py").write_text("unlanded\n")
    subprocess_git = ["git", "-C", str(outside)]
    import subprocess

    subprocess.run([*subprocess_git, "commit", "-qam", "side work"], check=True, capture_output=True)
    (outside / "notes.txt").write_text("dirty\n")
    gone = workspaces / "worktrees" / "gone"
    git("worktree", "add", "-q", "--detach", str(gone))
    import shutil

    shutil.rmtree(gone)
    monkeypatch.setattr("cli.lib.workspace_paths.get_workspaces_root", lambda: workspaces)

    rows = {Path(row["path"]).name: row for row in vcs._worktree_rows([repo])}
    assert rows["clean"] | {"path": ""} == {"repo": "repo", "path": "", "branch": "detached", "outside_workspace": False,
                                            "prunable": False, "dirty": 0, "unlanded": 0}
    assert rows["wt"]["branch"] == "side" and rows["wt"]["outside_workspace"] is True
    assert rows["wt"]["dirty"] == 1 and rows["wt"]["unlanded"] == 1
    assert rows["gone"]["prunable"] is True

    issues = vcs._issues([], _cleanup_payload(), [], [], list(rows.values()))
    details = sorted(issue.detail for issue in issues)
    assert details == sorted([f"missing:{gone}", f"{outside} dirty:1 unlanded:1 outside_workspace"])
    assert {issue.kind for issue in issues} == {"worktree"}
