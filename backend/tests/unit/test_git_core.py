from __future__ import annotations

import subprocess
from pathlib import Path

from app.api.models.git_models import RepoWorkspaceSummary
from app.utils import _git_core


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


def test_get_repo_status_uses_jj_bookmark_instead_of_detached_head(mocker, tmp_path: Path) -> None:
    from cli.lib.jj import JJRepoStatus

    (tmp_path / ".git").mkdir()
    (tmp_path / ".jj").mkdir()
    mocker.patch(
        "app.utils._git_core._get_jj_status",
        return_value=JJRepoStatus(
            repo="repo",
            path=str(tmp_path),
            branch="main",
            colocated=True,
            state="undescribed",
            described=False,
            conflicted=False,
            unpublished=1,
            change_id="chg",
            commit_id="commit",
        ),
    )
    mocker.patch("app.utils._git_core._get_ahead_behind", return_value=(0, 0))
    mocker.patch("app.utils._git_core._resolve_project_id", return_value="summitflow")
    mocker.patch("app.utils._git_branches.get_all_branches", return_value=[])
    mocker.patch(
        "app.utils._git_branches.build_repo_workspace_summary",
        return_value=RepoWorkspaceSummary(dirty_main_repo=True, needs_cleanup=True),
    )

    status = _git_core.get_repo_status(tmp_path)

    assert status is not None
    assert status.branch == "main"
    assert status.state == "dirty"
    assert status.uncommitted == 1
    assert status.ahead == 1


def test_pull_jj_repository_rebases_clean_head_to_remote_default(mocker, tmp_path: Path) -> None:
    from cli.lib.jj import JJRepoStatus

    (tmp_path / ".git").mkdir()
    (tmp_path / ".jj").mkdir()
    mocker.patch(
        "app.utils._git_core._get_jj_status",
        return_value=JJRepoStatus(
            repo="repo",
            path=str(tmp_path),
            branch="HEAD",
            colocated=True,
            state="clean",
            described=False,
            conflicted=False,
            unpublished=0,
            change_id="chg",
            commit_id="current",
        ),
    )
    mocker.patch("app.utils._git_core._get_ahead_behind", return_value=(0, 0))
    mocker.patch("app.utils._git_core._resolve_project_id", return_value="summitflow")
    mocker.patch("app.utils._git_branches.get_all_branches", return_value=[])
    mocker.patch(
        "app.utils._git_branches.build_repo_workspace_summary",
        return_value=RepoWorkspaceSummary(),
    )
    mocker.patch(
        "app.utils._git_core.run_git",
        return_value=subprocess.CompletedProcess([], 0, "origin/main\n", ""),
    )

    jj_calls: list[list[str]] = []

    def fake_run_jj(_repo: Path, args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        jj_calls.append(args)
        if args[:2] == ["git", "fetch"]:
            return subprocess.CompletedProcess(args, 0, "", "Nothing changed.")
        if args == ["status"]:
            return subprocess.CompletedProcess(args, 0, "The working copy has no changes.\n", "")
        if args[:3] == ["log", "--no-graph", "-r"]:
            revision = args[3]
            commit = {"@": "current", "@-": "oldmain", "main": "newmain"}[revision]
            return subprocess.CompletedProcess(args, 0, f"chg\t{commit}\tempty\tclean\t\n", "")
        if args == ["rebase", "-r", "@", "-d", "main"]:
            return subprocess.CompletedProcess(args, 0, "Rebased 1 commits\n", "")
        msg = f"unexpected jj args: {args}"
        return subprocess.CompletedProcess(args, 1, "", msg)

    mocker.patch("cli.lib.jj.run_jj", side_effect=fake_run_jj)

    result = _git_core.pull_repository(tmp_path)

    assert result.status == "updated"
    assert result.branch == "main"
    assert ["rebase", "-r", "@", "-d", "main"] in jj_calls
