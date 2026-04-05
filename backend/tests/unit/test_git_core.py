from __future__ import annotations

from pathlib import Path

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
    canonical_aterm = tmp_path / "srv" / "workspaces" / "projects" / "aterm"
    shadow_aterm = tmp_path / "home" / "kasadis" / "aterm"
    config_repo = tmp_path / "home" / "kasadis" / ".claude"

    for repo in (canonical_aterm, shadow_aterm, config_repo):
        (repo / ".git").mkdir(parents=True)

    mocker.patch("app.utils._git_core._collect_db_repos", return_value=[canonical_aterm])
    mocker.patch("app.utils._git_core._collect_db_extra_repos", return_value=[])
    mocker.patch(
        "app.utils._git_core._registered_project_roots",
        return_value={"aterm": canonical_aterm.resolve()},
    )
    mocker.patch(
        "app.utils._git_core._load_repo_paths_from_file",
        return_value=[shadow_aterm, config_repo],
    )

    repos = _git_core.get_managed_repos()

    assert repos == [canonical_aterm, config_repo]
