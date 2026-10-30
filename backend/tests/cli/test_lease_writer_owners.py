"""Owner checks (abandon, done, manual st lease) follow writer sets, which outlive leases.

Leases are advisory and expire after 30 min idle. Writer sets last until commit
or revert. Abandon still honours a foreign live lease too: Agent Hub tools write
without the hook, so their lease is the only mark, and a revert is destructive.
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
from cli.lib import coord, leases


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


def test_abandon_keeps_a_path_under_an_unhooked_agents_live_lease(repo, monkeypatch):
    monkeypatch.setenv("AGENT_HUB_SESSION_ID", "hub-session-1")  # write_file never records a writer
    monkeypatch.setenv("AGENT_HUB_AGENT_SLUG", "worker-agent")
    leases.acquire("proj", ["mine/a.py"], project_root=str(repo))
    monkeypatch.delenv("AGENT_HUB_SESSION_ID")
    monkeypatch.delenv("AGENT_HUB_AGENT_SLUG")
    _as(monkeypatch, "my-session-0001")
    assert leases.writers("proj") == {}
    owned, kept = split_owned_dirty_files(
        "task-1", {"files_to_modify": ["mine/"]}, get_dirty_files(str(repo)), project_id="proj", repo_root=str(repo),
    )
    assert owned == ["mine/b.py"]
    assert kept == ["mine/a.py"]


def test_abandon_owns_paths_under_its_own_untagged_lease(repo, monkeypatch):
    _as(monkeypatch, "my-session-0001")
    leases.acquire("proj", ["mine/**"], project_root=str(repo))
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


def test_foreign_writers_match_the_real_path_behind_a_symlinked_checkout(repo, tmp_path, monkeypatch):
    linked = tmp_path / "linked"
    linked.symlink_to(repo)
    _as(monkeypatch, "other-session-1")
    leases.record_writes("proj", [str(repo / "mine" / "a.py")])
    _as(monkeypatch, "my-session-0001")
    assert list(coord.foreign_writers("proj", linked, ["mine/a.py", "mine/b.py"])) == ["mine/a.py"]


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


def test_check_claims_like_the_edit_hook_for_unhooked_writers(repo, monkeypatch):
    """Agent Hub write_file runs st lease --check: it warns, exits 0 and joins the writer set."""
    monkeypatch.setattr("cli.lib.execution_context.resolve_checkout_project_id", lambda _top: "proj")
    monkeypatch.setattr(lease_command, "get_config_optional",
                        lambda: SimpleNamespace(project_id="proj", project_root=str(repo)))
    monkeypatch.chdir(repo)
    _as(monkeypatch, "other-session-1")
    leases.acquire("proj", ["mine/a.py"], project_root=str(repo))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.setenv("AGENT_HUB_SESSION_ID", "hub-session-1")
    monkeypatch.setenv("AGENT_HUB_AGENT_SLUG", "worker-agent")
    result = CliRunner().invoke(lease_command.app, ["--check", "mine/a.py"])
    assert result.exit_code == 0, result.output
    assert "WARNING: " in result.output and "leased by cc:other-" in result.output
    writers = leases.writers("proj")[str(repo / "mine" / "a.py")]
    assert [entry["agent_id"] for entry in writers] == [leases.identify_agent()[0]]
