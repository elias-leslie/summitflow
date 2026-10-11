from __future__ import annotations

import subprocess
from typing import cast
from unittest.mock import MagicMock, patch

from cli.commands._abandon_helpers import _build_preview_lines, abandon_subtask
from cli.lib.checkpoint_branches import delete_task_branches


def test_abandon_preview_does_not_claim_direct_main_has_task_branch() -> None:
    lines = _build_preview_lines(
        "task-123",
        legacy_local_branches=[],
        remote_branches=[],
        has_snapshot=True,
        snapshot_info={"project_id": "summitflow"},
        unmerged=0,
        dirty_files=[],
    )

    preview = "\n".join(lines)
    assert "Delete branch: task-123/main" not in preview
    assert "Remove checkpoint metadata" in preview
    assert "Task metadata is append-only" in preview


def test_abandon_subtask_no_longer_requires_legacy_branch() -> None:
    client = MagicMock()

    with (
        patch("cli.commands._abandon_helpers.check_branch_exists", return_value=False),
        patch("cli.commands._abandon_helpers.delete_subtask_branch") as mock_delete,
    ):
        result = abandon_subtask(client, "1.1", "task-123")

    client.update_subtask.assert_called_once_with("task-123", "1.1", passes=False)
    mock_delete.assert_not_called()
    assert result["branch_deleted"] is None


def test_delete_task_branches_does_not_switch_head() -> None:
    calls: list[list[str]] = []

    def fake_run_git(
        args: list[str],
        cwd: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(args, 0, "main\n", "")
        if args[:3] == ["git", "branch", "--list"]:
            stdout = "  task-123/main\n" if args[-1] == "task-123/*" else ""
            return subprocess.CompletedProcess(args, 0, stdout, "")
        if args[:2] == ["git", "branch"] and args[2] == "-D":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["git", "for-each-ref"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch("cli.lib.checkpoint_branches._run_git", side_effect=fake_run_git):
        assert delete_task_branches("task-123") is True

    assert not any(args[:2] == ["git", "checkout"] for args in calls)


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _dirty_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "mine").mkdir(parents=True)
    (repo / "mine" / "a.py").write_text("a = 1\n")
    (repo / "other.py").write_text("b = 1\n")
    (repo / "leased.py").write_text("c = 1\n")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base")
    for name in ("mine/a.py", "other.py", "leased.py"):
        (repo / name).write_text("changed\n")
    return repo


def _lease(repo, path: str, task_id: str | None, agent_id: str = "agent-other"):
    from cli.lib.leases import Lease

    return Lease(
        lease_id=f"lease-{path}", agent_id=agent_id, agent_slug="x", session_id="s", provider="p",
        globs=[str(repo / path)], task_id=task_id, acquired_at="", last_heartbeat="",
    )


def test_split_owned_dirty_files_keeps_unowned_and_foreign_leased_paths(tmp_path) -> None:
    from cli.commands._abandon_helpers import get_dirty_files, split_owned_dirty_files

    repo = _dirty_repo(tmp_path)
    leases = [_lease(repo, "leased.py", "task-123"), _lease(repo, "mine/a.py", "task-other")]
    task = {"files_to_modify": ["mine/"]}

    with (
        patch("cli.lib.leases.list_active", return_value=leases),
        patch("cli.lib.leases.identify_agent", return_value=("agent-me", "", "", "")),
    ):
        owned, kept = split_owned_dirty_files(
            "task-123", task, get_dirty_files(str(repo)), project_id="proj", repo_root=str(repo),
        )

    # mine/a.py is declared but another task's live lease covers it; leased.py is this task's lease.
    assert owned == ["leased.py"]
    assert sorted(kept) == ["mine/a.py", "other.py"]


def test_abandon_task_never_restores_paths_it_does_not_own(tmp_path) -> None:
    from cli.commands import _abandon_helpers

    repo = _dirty_repo(tmp_path)
    client = MagicMock()
    client.get_task.return_value = {"project_id": "proj", "files_to_modify": ["mine/a.py"]}

    with (
        patch.object(_abandon_helpers, "get_snapshot_info", return_value=None),
        patch.object(_abandon_helpers, "get_project_root_path", return_value=str(repo)),
        patch.object(_abandon_helpers, "get_task_branches", return_value=[]),
        patch.object(_abandon_helpers, "get_remote_task_branches", return_value=[]),
        patch.object(_abandon_helpers, "confirm_gate") as gate,
        patch.object(_abandon_helpers, "delete_task_branches"),
        patch("cli.lib.leases.list_active", return_value=[]),
    ):
        result = _abandon_helpers.abandon_task(client, "task-123", confirm="token")

    preview = "\n".join(gate.call_args.args[2])
    assert "KEEP 2 tracked change(s)" in preview
    assert result["discarded_paths"] == ["mine/a.py"]
    assert sorted(cast(list[str], result["kept_paths"])) == ["leased.py", "other.py"]
    assert (repo / "mine" / "a.py").read_text() == "a = 1\n"
    assert (repo / "other.py").read_text() == "changed\n"
    assert (repo / "leased.py").read_text() == "changed\n"


def test_abandon_task_without_declared_scope_restores_nothing(tmp_path) -> None:
    from cli.commands import _abandon_helpers

    repo = _dirty_repo(tmp_path)
    client = MagicMock()
    client.get_task.return_value = {"project_id": "proj"}

    with (
        patch.object(_abandon_helpers, "get_snapshot_info", return_value=None),
        patch.object(_abandon_helpers, "get_project_root_path", return_value=str(repo)),
        patch.object(_abandon_helpers, "get_task_branches", return_value=[]),
        patch.object(_abandon_helpers, "get_remote_task_branches", return_value=[]),
        patch.object(_abandon_helpers, "confirm_gate"),
        patch.object(_abandon_helpers, "delete_task_branches"),
        patch("cli.lib.leases.list_active", return_value=[]),
        patch("subprocess.run", wraps=subprocess.run) as run,
    ):
        result = _abandon_helpers.abandon_task(client, "task-123", confirm="token")

    assert result["discarded_paths"] == []
    assert not any("restore" in call.args[0] for call in run.call_args_list if call.args)
    assert (repo / "mine" / "a.py").read_text() == "changed\n"
