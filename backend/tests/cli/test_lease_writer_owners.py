"""Owner checks (abandon, done, manual st lease) follow writer sets, not file leases.

Leases are advisory and expire after 30 min idle; a contested edit leaves two
leases. Writer sets last until commit or revert, so they decide ownership.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli.commands import lease as lease_command
from cli.commands._abandon_helpers import get_dirty_files, split_owned_dirty_files
from cli.commands.done_task_scope import closeout_paths
from cli.lib import leases


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for name in ("TMUX_PANE", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID", "PI_SESSION_ID", "ST_COORD_HARNESS",
                 "ST_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ST_COORD_ANCHOR", "")
    root = tmp_path / "repo"
    (root / "mine").mkdir(parents=True)
    for name in ("mine/a.py", "mine/b.py"):
        (root / name).write_text("x = 1\n")
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    _git(root, "add", ".")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    for name in ("mine/a.py", "mine/b.py"):
        (root / name).write_text("changed\n")
    return root.resolve()


def _as(monkeypatch, sid: str) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)


def test_abandon_keeps_foreign_writes_after_their_lease_is_gone(repo, monkeypatch):
    _as(monkeypatch, "other-session-1")
    leases.claim("proj", str(repo / "mine" / "a.py"))
    leases.release("proj")  # the lease expired; the write is still theirs
    _as(monkeypatch, "my-session-0001")
    owned, kept = split_owned_dirty_files(
        "task-1", {"files_to_modify": ["mine/"]}, get_dirty_files(str(repo)), project_id="proj", repo_root=str(repo),
    )
    assert owned == ["mine/b.py"]
    assert kept == ["mine/a.py"]


def test_abandon_owns_a_path_whose_only_foreign_mark_is_an_untagged_lease(repo, monkeypatch):
    _as(monkeypatch, "other-session-1")
    leases.acquire("proj", ["mine/**"], project_root=str(repo))  # declared scope, never wrote
    _as(monkeypatch, "my-session-0001")
    leases.claim("proj", str(repo / "mine" / "a.py"))
    owned, kept = split_owned_dirty_files(
        "task-1", {"files_to_modify": ["mine/"]}, get_dirty_files(str(repo)), project_id="proj", repo_root=str(repo),
    )
    assert owned == ["mine/a.py", "mine/b.py"]
    assert kept == []


def test_done_refuses_a_path_another_session_wrote_even_without_a_lease(repo, monkeypatch):
    _as(monkeypatch, "other-session-1")
    leases.record_writes("proj", [str(repo / "mine" / "a.py")])
    _as(monkeypatch, "my-session-0001")
    with pytest.raises(ValueError, match="also written by another session"):
        closeout_paths(str(repo), "task-1", {}, project_id="proj", paths=("mine/a.py",))


def test_done_accepts_an_explicit_path_with_only_an_unknown_writer(repo, monkeypatch):
    _as(monkeypatch, "my-session-0001")
    leases.record_writes("proj", [str(repo / "mine" / "a.py")], unknown="background")
    assert closeout_paths(str(repo), "task-1", {}, project_id="proj", paths=("mine/a.py",)) == ("mine/a.py",)


def test_manual_relative_lease_resolves_against_current_checkout(repo, tmp_path, monkeypatch):
    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(worktree))
    monkeypatch.setattr(lease_command, "get_config_optional",
                        lambda: SimpleNamespace(project_id="proj", project_root=str(repo)))
    monkeypatch.setattr("cli.lib.execution_context.resolve_checkout_project_id", lambda _top: "proj")
    monkeypatch.chdir(worktree / "mine")
    _as(monkeypatch, "my-session-0001")
    result = CliRunner().invoke(lease_command.app, ["mine/**"])
    assert result.exit_code == 0, result.output
    assert [lease.globs for lease in leases.list_active("proj")] == [[f"{worktree.resolve()}/mine/**"]]
