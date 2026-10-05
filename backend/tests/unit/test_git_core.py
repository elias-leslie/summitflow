from __future__ import annotations

import subprocess
from pathlib import Path

from app.api.models.git_models import RepoWorkspaceSummary
from app.utils import _git_core


def test_run_git_uses_posix_spawn_friendly_command(mocker, tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess([], 0, "", "")
    run = mocker.patch("app.utils._git_core.safe_subprocess.run", return_value=completed)

    assert _git_core.run_git(["status", "--porcelain"], tmp_path) is completed

    run.assert_called_once_with(
        ["git", "-C", str(tmp_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_resolve_project_id_uses_git_core_collaborators(mocker) -> None:
    mocker.patch(
        "app.utils._git_core._query_db_project_roots",
        return_value=[("summitflow", "/repos/summitflow")],
    )
    translate_path = mocker.patch(
        "app.utils._git_core._translate_path",
        side_effect=lambda raw: Path(raw),
    )

    project_id = _git_core._resolve_project_id(Path("/repos/summitflow"))

    assert project_id == "summitflow"
    translate_path.assert_called_once_with("/repos/summitflow")


def test_get_managed_repos_skips_shadowed_project_entries_from_fallback(mocker, tmp_path: Path) -> None:
    canonical_a_term = tmp_path / "srv" / "workspaces" / "projects" / "a-term"
    shadow_a_term = tmp_path / "home" / "kasadis" / "a-term"
    config_repo = tmp_path / "home" / "kasadis" / ".claude"

    for repo in (canonical_a_term, shadow_a_term, config_repo):
        (repo / ".git").mkdir(parents=True)

    mocker.patch("app.utils._git_core._collect_db_repos", return_value=[canonical_a_term])
    mocker.patch("app.utils._git_core._collect_db_extra_repos", return_value=[])
    mocker.patch(
        "app.utils._git_core._registered_project_roots",
        return_value={"a-term": canonical_a_term.resolve()},
    )
    mocker.patch(
        "app.utils._git_core._load_repo_paths_from_file",
        return_value=[shadow_a_term, config_repo],
    )

    repos = _git_core.get_managed_repos()

    assert repos == [canonical_a_term, config_repo]


def test_detached_status_uses_actual_git_head(mocker, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    # Legacy metadata must neither invoke an external VCS nor override Git state.
    (tmp_path / ".jj").mkdir()
    mocker.patch("app.utils._git_core._get_current_branch", return_value="HEAD")
    mocker.patch("app.utils._git_core._count_uncommitted", return_value=0)
    mocker.patch("app.utils._git_core._get_ahead_behind", return_value=(2, 0))
    mocker.patch("app.utils._git_core._resolve_project_id", return_value="fixture")
    mocker.patch("app.utils._git_branches.get_all_branches", return_value=[])
    mocker.patch("app.utils._git_branches.build_repo_workspace_summary", return_value=RepoWorkspaceSummary())
    status = _git_core.get_repo_status(tmp_path)
    assert status is not None
    assert (status.branch, status.ahead, status.uncommitted, status.state) == ("HEAD", 2, 0, "ahead")


def test_detached_pull_refuses_before_transport(mocker, tmp_path: Path) -> None:
    from app.api.models.git_models import RepoStatus
    mocker.patch("app.utils._git_core.get_repo_status", return_value=RepoStatus(
        path=str(tmp_path), name="fixture", branch="HEAD", ahead=2, behind=0,
        uncommitted=0, state="ahead"))
    run = mocker.patch("app.utils._git_core.run_git")
    result = _git_core.pull_repository(tmp_path)
    assert result.status == "failed"
    assert result.error is not None
    assert "detached HEAD" in result.error
    run.assert_not_called()


def test_detached_ahead_count_uses_remote_default_and_actual_head(mocker, tmp_path: Path) -> None:
    run = mocker.patch("app.utils._git_core.run_git", side_effect=[
        subprocess.CompletedProcess([], 0, "origin/main\n", ""),
        subprocess.CompletedProcess([], 0, "2\t0\n", ""),
    ])
    assert _git_core._get_ahead_behind(tmp_path, "HEAD") == (2, 0)
    assert run.call_args.args[0] == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]


def test_clean_git_pull_fast_forwards(mocker, tmp_path: Path) -> None:
    from app.api.models.git_models import RepoStatus
    mocker.patch("app.utils._git_core.get_repo_status", return_value=RepoStatus(
        path=str(tmp_path), name="fixture", branch="main", ahead=0, behind=1,
        uncommitted=0, state="behind"))
    run = mocker.patch("app.utils._git_core.run_git", return_value=subprocess.CompletedProcess([], 0, "updated", ""))
    assert _git_core.pull_repository(tmp_path).status == "updated"
    run.assert_called_once_with(["pull", "--ff-only"], tmp_path)


def test_detached_ahead_count_uses_established_base_when_origin_head_missing(mocker, tmp_path: Path) -> None:
    mocker.patch("app.utils.git_base.detect_base_branch", return_value="main")
    run = mocker.patch("app.utils._git_core.run_git", side_effect=[
        subprocess.CompletedProcess([], 1, "", ""),
        subprocess.CompletedProcess([], 0, "2\t0\n", ""),
    ])
    assert _git_core._get_ahead_behind(tmp_path, "HEAD") == (2, 0)
    assert run.call_args.args[0] == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]
