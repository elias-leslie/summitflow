"""Unit tests for git snapshot helpers."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from app.utils._git_diff import list_snapshots


def _result(*, stdout: str, returncode: int = 0) -> CompletedProcess[str]:
    return CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


def test_list_snapshots_prefers_internal_refs_and_keeps_legacy_fallback(mocker) -> None:
    repo_path = Path("/tmp/repo")

    def fake_run_git(args: list[str], cwd: Path) -> CompletedProcess[str]:
        assert cwd == repo_path
        if args[:1] == ["for-each-ref"]:
            return _result(
                stdout=(
                    "refs/summitflow/snapshots/pre-merge/task-1\t"
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\t"
                    "aaaaaaa\t2026-04-09T00:00:00+00:00\n"
                )
            )
        if args[:3] == ["tag", "-l", "snapshot/pre-merge/*"]:
            return _result(
                stdout=(
                    "snapshot/pre-merge/task-1\t"
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\t"
                    "bbbbbbb\t2026-04-08T00:00:00+00:00\n"
                    "snapshot/pre-merge/task-2\t"
                    "cccccccccccccccccccccccccccccccccccccccc\t"
                    "ccccccc\t2026-04-07T00:00:00+00:00\n"
                )
            )
        if args == ["rev-parse", "HEAD"]:
            return _result(stdout="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")
        if args == ["rev-list", "--count", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa..HEAD"]:
            return _result(stdout="0\n")
        if args == ["rev-list", "--count", "cccccccccccccccccccccccccccccccccccccccc..HEAD"]:
            return _result(stdout="2\n")
        raise AssertionError(f"Unexpected git args: {args}")

    mocker.patch("app.utils._git_diff.run_git", side_effect=fake_run_git)

    snapshots = list_snapshots(repo_path)

    assert [snapshot.task_id for snapshot in snapshots] == ["task-1", "task-2"]
    assert snapshots[0].sha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert snapshots[0].is_current is True
    assert snapshots[1].sha == "cccccccccccccccccccccccccccccccccccccccc"
    assert snapshots[1].commits_ahead == 2
