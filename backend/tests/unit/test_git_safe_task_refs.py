from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.utils._git_branches import list_safe_task_refs, prune_safe_task_refs


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
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")


def test_safe_task_ref_cleanup_deletes_merged_local_and_remote_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    _init_repo(repo)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "branch", "task/task-merged")
    _git(repo, "push", "origin", "task/task-merged")

    refs = list_safe_task_refs(repo)

    assert {(ref.name, ref.kind, ref.reason) for ref in refs} == {
        ("task/task-merged", "local", "merged"),
        ("task/task-merged", "remote", "merged"),
    }

    assert prune_safe_task_refs(repo) == (1, 1)
    branches = _git(repo, "branch", "--all", "--format=%(refname:short)").stdout
    assert "task/task-merged" not in branches


def test_safe_task_ref_cleanup_keeps_unmerged_task_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "checkout", "-b", "task/task-open")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "checkout", "main")

    assert list_safe_task_refs(repo) == []
    assert prune_safe_task_refs(repo) == (0, 0)
    branches = _git(repo, "branch", "--format=%(refname:short)").stdout
    assert "task/task-open" in branches
