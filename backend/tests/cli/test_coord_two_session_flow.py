"""Two simulated sessions through lease conflict, handshake, ack and release.

No LLM and no mocks of the coordination code: each session is a different
native session identity, and every step goes through the same `st` commands
and library calls the agents use, against disposable git repos and a private
lease/ledger store (see the autouse isolation fixture in conftest).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.lib import coord, leases
from cli.lib.commit_workflow import CommitError, commit_git_revision
from cli.main import app

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _as(monkeypatch: pytest.MonkeyPatch, session: str) -> str:
    """Become one Claude Code session; returns its coordination agent id."""
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    return leases.identify_agent()[0]


def _st(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"st {' '.join(args)} -> {result.exit_code}: {result.output}"
    return result.output


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("TMUX_PANE", "CLAUDE_SESSION_ID", "PI_SESSION_ID", "ANTIGRAVITY_CONVERSATION_ID", "ST_COORD_HARNESS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ST_COORD_ANCHOR", "")
    root = tmp_path / "pairrepo"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "a.py").write_text("a = 1\n")
    (root / "backend" / "b.py").write_text("b = 1\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    monkeypatch.chdir(root)
    monkeypatch.setenv("ST_PROJECT_ID", "pairrepo")
    return root


def test_lease_conflict_handshake_ack_and_release_between_two_sessions(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = str(repo / "backend" / "a.py")

    # Session A takes the repo for integration.
    alpha = _as(monkeypatch, "alpha-session-0001")
    assert "Holding pairrepo (integration)" in _st("lease", "--hold", "integration")
    assert "integration" in _st("lease", "--list")

    # Session B sees A's hold: its commit is refused with a one-line reason naming A.
    beta = _as(monkeypatch, "beta-session-00002")
    assert alpha != beta
    (repo / "backend" / "b.py").write_text("b = 2\n")
    with pytest.raises(CommitError, match="hold integration"):
        commit_git_revision(repo, message="b", skip_checks=True, paths=["backend/b.py"])

    # B asks A through the handshake; without an ack the commit stays refused.
    sent = _st("sessions", "send", alpha, "commit backend/b.py while you hold the repo?", "--delivery", "handshake")
    assert sent.startswith("sent ")
    request = coord._load_ledger()[0]
    assert (request["from"], request["to"], request["state"]) == (beta, alpha, "open")
    with pytest.raises(CommitError):
        commit_git_revision(repo, message="b", skip_checks=True, paths=["backend/b.py"], with_ack=request["id"])

    # A is shown the request on its next turn and answers; the sender's ack is not accepted from B.
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "beta-session-00002")
    ack_as_sender = runner.invoke(app, ["sessions", "ack", request["id"], "yes"])
    assert ack_as_sender.exit_code == 2 and "not addressed" in ack_as_sender.output
    _as(monkeypatch, "alpha-session-0001")
    assert any(request["id"] in line for line in coord.notices())
    assert f"acked {request['id']} yes" in _st("sessions", "ack", request["id"], "yes")

    # B's commit now goes through with the acked request; A's hold is untouched.
    _as(monkeypatch, "beta-session-00002")
    assert any(line.startswith(f"ACK {request['id']} yes") for line in coord.notices())
    committed = commit_git_revision(repo, message="b", skip_checks=True, paths=["backend/b.py"], with_ack=request["id"])
    assert committed["status"] == "SUCCESS"
    assert f"closed {request['id']}" in _st("sessions", "confirm", request["id"])
    assert coord._load_ledger()[0]["state"] == "closed"

    # A releases; B edits and commits without any ack, and A's file lease no longer warns.
    _as(monkeypatch, "alpha-session-0001")
    assert "Released" in _st("lease", "--release-all")
    assert "integration" not in _st("lease", "--list")
    _as(monkeypatch, "beta-session-00002")
    (repo / "backend" / "b.py").write_text("b = 3\n")
    assert coord.edit_conflict(target) is None
    result = commit_git_revision(repo, message="b again", skip_checks=True, paths=["backend/b.py"])
    assert result["status"] == "SUCCESS"


def test_file_lease_conflict_warns_then_clears_on_release(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = str(repo / "backend" / "a.py")
    _as(monkeypatch, "alpha-session-0001")
    assert "Acquired lease" in _st("lease", "backend/**")

    _as(monkeypatch, "beta-session-00002")
    warned = coord.edit_conflict(target)
    assert warned is not None and "leased by cc:alpha" in warned
    blocked = runner.invoke(app, ["lease", "--check", "backend/a.py"])
    assert blocked.exit_code == 0 and "WARNING" in blocked.output  # advisory, not a block

    _as(monkeypatch, "alpha-session-0001")
    _st("lease", "--release-all")
    _as(monkeypatch, "beta-session-00002")
    assert coord.edit_conflict(target) is None
