"""Multi-session coordination scenarios on disposable git fixture repos.

Each scenario switches the native session identity the way separate Claude
Code / Codex / pi sessions present it, so the same store, hook and guards are
exercised as on the host. Subprocess cases drive the real hook script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cli.lib import coord, coord_lineage, leases
from cli.lib.commit_workflow import CommitError, commit_git_revision

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / "scripts" / "lib" / "lease-hook"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("ST_COORD_ANCHOR", "")  # no harness lineage unless a scenario sets one
    for name in ("PI_SESSION_ID", "ANTIGRAVITY_CONVERSATION_ID", "ST_COORD_HARNESS"):
        monkeypatch.delenv(name, raising=False)
    out = {}
    for name in ("hostrepo", "genrepo"):
        repo = tmp_path / name
        (repo / "backend").mkdir(parents=True)
        (repo / "backend" / "a.py").write_text("a = 1\n")
        (repo / "gen.json").write_text("{}\n")
        (repo / ".gitignore").write_text("cache/\n")
        _git(repo, "init", "-q", "-b", "main")
        # Repo-local identity: the hermetic acceptance fixture has no global git config.
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        out[name] = repo
    return out


def as_claude(monkeypatch, sid: str) -> None:
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)


def as_codex(monkeypatch, sid: str) -> None:
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", sid)


def as_pi(monkeypatch, sid: str) -> None:
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("PI_SESSION_ID", sid)


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def _foreign_op(repo: Path, proc: subprocess.Popen) -> None:
    """An op lease owned by another live process (an acceptance run elsewhere)."""
    lease = leases.acquire_mark(repo.name, str(repo), "op", "acceptance")
    with leases._lock(repo.name):
        rows = leases._load(repo.name)
        for row in rows:
            if row.lease_id == lease.lease_id:
                row.pid, row.pid_start = proc.pid, leases._process_start(proc.pid)
        leases._save(repo.name, rows)


def _tokens(text: str) -> int:
    return (len(text) + 3) // 4


# ------------------------------------------------------------ edits

def test_concurrent_edit_same_file_blocks_then_commit_releases(repos, monkeypatch):
    repo = repos["hostrepo"]
    target = str(repo / "backend" / "a.py")
    as_claude(monkeypatch, "claude-aaaaaaaa")
    assert coord.edit_conflict(target) is None
    (repo / "backend" / "a.py").write_text("a = 2\n")

    as_codex(monkeypatch, "codex-bbbbbbbb")
    blocked = coord.edit_conflict(target)
    assert blocked is not None and "leased by cc:claude" in blocked
    assert blocked.count("\n") == 0 and _tokens(blocked) < 60

    as_claude(monkeypatch, "claude-aaaaaaaa")
    result = commit_git_revision(repo, message="edit", skip_checks=True, paths=["backend/a.py"])
    assert result["status"] == "SUCCESS"
    as_codex(monkeypatch, "codex-bbbbbbbb")
    assert coord.edit_conflict(target) is None


def test_commit_of_foreign_leased_path_is_refused_in_unregistered_repo(repos, monkeypatch):
    """Fixture repos are not registered projects; the per-path commit check must still apply."""
    repo = repos["hostrepo"]
    as_claude(monkeypatch, "claude-aaaaaaaa")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    (repo / "backend" / "a.py").write_text("a = 3\n")

    as_codex(monkeypatch, "codex-bbbbbbbb")
    with pytest.raises(CommitError, match="leased by another agent"):
        commit_git_revision(repo, message="steal", skip_checks=True, paths=["backend/a.py"], with_ack=None)


def test_subagents_share_parent_identity_separate_sessions_do_not(repos, monkeypatch):
    target = str(repos["hostrepo"] / "backend" / "a.py")
    as_claude(monkeypatch, "parent-11111111")
    assert coord.edit_conflict(target) is None
    # A subagent inherits the parent's CLAUDE_CODE_SESSION_ID.
    assert coord.edit_conflict(target) is None
    as_claude(monkeypatch, "other-22222222")
    assert coord.edit_conflict(target) is not None


def test_cross_repo_generated_artifact_lands_in_target_repo_store(repos, monkeypatch):
    """neri.json case: a session working in genrepo writes into hostrepo."""
    host, gen = repos["hostrepo"], repos["genrepo"]
    monkeypatch.chdir(gen)
    as_codex(monkeypatch, "gen-session-0001")
    assert coord.edit_conflict(str(host / "gen.json")) is None
    assert [lease.agent_id for lease in leases.list_active("hostrepo")] == ["codex:gen-se"]
    assert leases.list_active("genrepo") == []

    proc = _sleeper()
    try:
        _foreign_op(host, proc)
        blocked = coord.edit_conflict(str(host / "gen.json"))
        assert blocked is not None and "op acceptance" in blocked
        # Ignored paths cannot invalidate acceptance and stay writable.
        assert coord.edit_conflict(str(host / "cache" / "x.bin")) is None
    finally:
        proc.kill()
        proc.wait()


def test_acceptance_op_blocks_every_editor_and_commit(repos, monkeypatch):
    repo = repos["hostrepo"]
    proc = _sleeper()
    try:
        _foreign_op(repo, proc)
        for become in (lambda: as_claude(monkeypatch, "x-claude-01"), lambda: as_codex(monkeypatch, "x-codex-01")):
            become()
            assert coord.edit_conflict(str(repo / "backend" / "a.py")) is not None
        (repo / "backend" / "a.py").write_text("a = 3\n")
        with pytest.raises(CommitError, match="op acceptance"):
            commit_git_revision(repo, message="x", skip_checks=True, paths=["backend/a.py"])
    finally:
        proc.kill()
        proc.wait()


def test_crashed_op_holder_is_stale_immediately(repos, monkeypatch):
    repo = repos["hostrepo"]
    proc = _sleeper()
    _foreign_op(repo, proc)
    proc.kill()
    proc.wait()
    as_codex(monkeypatch, "after-crash-01")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    assert leases.repo_marks("hostrepo") == []


def test_foreign_hold_refuses_acceptance_but_not_the_holder(repos, monkeypatch):
    from cli.lib import acceptance

    repo = repos["hostrepo"]
    as_claude(monkeypatch, "integrator-0001")
    leases.acquire_mark("hostrepo", str(repo), "hold", "integration")
    coord.guard(repo, "acceptance")
    as_codex(monkeypatch, "finisher-00001")
    with pytest.raises(acceptance.AcceptanceError, match=r"hold integration .*acceptance refused"):
        acceptance.accept_revision(repo)
    # Concurrent acceptance op leases never block each other.
    as_claude(monkeypatch, "integrator-0001")
    proc = _sleeper()
    try:
        _foreign_op(repo, proc)
        coord.guard(repo, "acceptance")
    finally:
        proc.kill()
        proc.wait()


def test_active_holder_keeps_its_hold_live(repos, monkeypatch):
    repo = repos["hostrepo"]
    as_claude(monkeypatch, "holder-busy-01")
    leases.acquire_mark("hostrepo", str(repo), "hold", "integration")
    with leases._lock("hostrepo"):
        rows = leases._load("hostrepo")
        for row in rows:
            row.last_heartbeat = (datetime.now(UTC) - timedelta(minutes=29)).isoformat()
        leases._save("hostrepo", rows)
    coord.guard(repo, "commit")  # the holder keeps working
    hold = next(m for m in leases.repo_marks("hostrepo") if m.kind == "hold")
    assert datetime.now(UTC) - datetime.fromisoformat(hold.last_heartbeat) < timedelta(minutes=1)


def test_idle_hold_expires_and_take_overrides_file_lease(repos, monkeypatch):
    repo = repos["hostrepo"]
    as_claude(monkeypatch, "holder-crash-01")
    leases.acquire_mark("hostrepo", str(repo), "hold", "integration")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    with leases._lock("hostrepo"):
        rows = leases._load("hostrepo")
        for row in rows:
            row.last_heartbeat = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        leases._save("hostrepo", rows)
    as_codex(monkeypatch, "survivor-0001")
    coord.guard(repo, "publish")  # stale hold and stale file lease no longer block
    as_claude(monkeypatch, "holder-crash-01")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    as_codex(monkeypatch, "survivor-0001")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is not None
    leases.take("hostrepo", str(repo / "backend" / "a.py"))
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None


# ------------------------------------------------------------ repo guards + handshake

def test_publish_on_held_repo_needs_acked_request(repos, monkeypatch):
    """The agent-hub publish case: the tool refuses; memory of earlier messages is not needed."""
    repo = repos["hostrepo"]
    as_claude(monkeypatch, "b7-integrator")
    leases.acquire_mark("hostrepo", str(repo), "hold", "integration")

    as_claude(monkeypatch, "coordinator-34")
    for operation in ("publish", "rebuild", "reconcile", "commit"):
        with pytest.raises(coord.CoordBlocked) as blocked:
            coord.guard(repo, operation)
        line = str(blocked.value)
        assert "hold integration by cc:b7-int" in line and "\n" not in line
    request = coord.send("cc:b7-int", "publish hostrepo now?", project="hostrepo")
    with pytest.raises(coord.CoordBlocked):
        coord.guard(repo, "publish", with_ack=request["id"])  # not acked yet

    as_claude(monkeypatch, "b7-integrator")
    assert any(request["id"] in line for line in coord.notices())
    coord.ack(request["id"], "yes")

    as_claude(monkeypatch, "coordinator-34")
    coord.guard(repo, "publish", with_ack=request["id"])
    assert any(line.startswith(f"ACK {request['id']} yes") for line in coord.notices())
    assert coord.notices() == []  # surfaced once
    coord.confirm(request["id"])
    assert [row["state"] for row in coord._load_ledger()] == ["closed"]


def test_commit_of_own_paths_is_not_blocked_by_parallel_file_work(repos, monkeypatch):
    repo = repos["hostrepo"]
    as_codex(monkeypatch, "parallel-codex-1")
    assert coord.edit_conflict(str(repo / "gen.json")) is None
    as_claude(monkeypatch, "parallel-cc-1")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    (repo / "backend" / "a.py").write_text("a = 9\n")
    assert commit_git_revision(repo, message="own", skip_checks=True, paths=["backend/a.py"])["status"] == "SUCCESS"
    with pytest.raises(coord.CoordBlocked, match="leased by codex:parall"):
        coord.guard(repo, "rebuild")


def test_unacked_request_surfaces_once_and_late_ack_still_lands(repos, monkeypatch):
    as_claude(monkeypatch, "asker-000001")
    request = coord.send("codex:silent", "pause writes to backend/** until 15:00")
    assert coord.notices() == []  # not yet overdue
    with leases._lock("_coord"):
        rows = coord._load_ledger()
        rows[0]["created"] = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        coord._save_ledger(rows)
    first = coord.notices()
    assert len(first) == 1 and first[0].startswith(f"UNACKED {request['id']}")
    assert coord.notices() == []

    as_codex(monkeypatch, "silent-thread-uuid")
    assert any(request["id"] in line for line in coord.notices())
    coord.ack(request["id"], "eta:20", None)
    as_claude(monkeypatch, "asker-000001")
    assert coord.notices() == [f"ACK {request['id']} eta 20m from codex:silent; close: st sessions confirm {request['id']}"]


def test_duplicate_and_replayed_messages(repos, monkeypatch):
    as_claude(monkeypatch, "dup-sender-01")
    first = coord.send("codex:abcdef", "is gen.json yours?")
    again = coord.send("codex:abcdef", "is  gen.json   yours?")
    assert again["id"] == first["id"] and again.get("duplicate")
    with pytest.raises(ValueError, match="not addressed"):
        coord.ack(first["id"], "yes")
    as_codex(monkeypatch, "abcdef-thread")
    with pytest.raises(ValueError, match="reason"):
        coord.ack(first["id"], "no")
    coord.ack(first["id"], "no", "mine, committing in 5m")
    as_claude(monkeypatch, "dup-sender-01")
    coord.confirm(first["id"])
    with pytest.raises(ValueError, match="no ack"):
        coord.confirm(first["id"])
    as_codex(monkeypatch, "abcdef-thread")
    with pytest.raises(ValueError, match="closed"):
        coord.ack(first["id"], "yes")
    with pytest.raises(ValueError, match="160"):
        coord.send("cc:x", "x" * 200)


def test_no_ack_does_not_authorize_and_ack_is_project_bound(repos, monkeypatch):
    host, gen = repos["hostrepo"], repos["genrepo"]
    as_codex(monkeypatch, "holder-two-01")
    leases.acquire_mark("hostrepo", str(host), "hold", "release")
    leases.acquire_mark("genrepo", str(gen), "hold", "release")
    as_claude(monkeypatch, "asker-two-01")
    request = coord.send("codex:holder", "rebuild hostrepo?", project="hostrepo")
    as_codex(monkeypatch, "holder-two-01")
    coord.ack(request["id"], "yes")
    as_claude(monkeypatch, "asker-two-01")
    coord.guard(host, "rebuild", with_ack=request["id"])
    with pytest.raises(coord.CoordBlocked):
        coord.guard(gen, "rebuild", with_ack=request["id"])  # replay against another repo


def test_sensitive_holder_renders_opaque_busy_line(repos, monkeypatch):
    repo = repos["hostrepo"]
    monkeypatch.setenv("ST_COORD_SENSITIVE", "1")
    as_codex(monkeypatch, "sensitive-001")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    leases.acquire_mark("hostrepo", str(repo), "hold", "target-xyz triage")
    (repo / "backend" / "a.py").write_text("a = 5\n")
    monkeypatch.delenv("ST_COORD_SENSITIVE")
    as_claude(monkeypatch, "observer-001")
    blocked = coord.edit_conflict(str(repo / "backend" / "a.py"))
    assert blocked is not None and "busy (backend/**)" in blocked
    assert "a.py" not in blocked.split("; ask")[0] and "target-xyz" not in blocked
    with pytest.raises(coord.CoordBlocked) as guarded:
        coord.guard(repo, "publish")
    assert "target-xyz" not in str(guarded.value)
    owner = coord.dirty_owner_line("hostrepo", repo)
    assert owner is not None and "a.py" not in owner and "backend/**<-codex:sensit" in owner
    assert all("target-xyz" not in line for line in coord.system_lines())


def test_deadlock_two_holders_resolve_by_acks_without_waiting(repos, monkeypatch):
    host, gen = repos["hostrepo"], repos["genrepo"]
    as_claude(monkeypatch, "holder-host-1")
    leases.acquire_mark("hostrepo", str(host), "hold", "integration")
    as_codex(monkeypatch, "holder-gen-01")
    leases.acquire_mark("genrepo", str(gen), "hold", "integration")
    with pytest.raises(coord.CoordBlocked):
        coord.guard(host, "rebuild")  # returns immediately, never waits
    want_host = coord.send("cc:holder", "rebuild hostrepo?", project="hostrepo")
    as_claude(monkeypatch, "holder-host-1")
    with pytest.raises(coord.CoordBlocked):
        coord.guard(gen, "rebuild")
    want_gen = coord.send("codex:holder", "rebuild genrepo?", project="genrepo")
    coord.ack(want_host["id"], "yes")  # earlier hold acks first
    as_codex(monkeypatch, "holder-gen-01")
    coord.guard(host, "rebuild", with_ack=want_host["id"])
    coord.ack(want_gen["id"], "yes")
    as_claude(monkeypatch, "holder-host-1")
    coord.guard(gen, "rebuild", with_ack=want_gen["id"])


def test_pi_session_without_hooks_still_hits_st_guards(repos, monkeypatch):
    """A session that ignores the instruction (no hook, no st lease) is still refused by st."""
    repo = repos["hostrepo"]
    as_claude(monkeypatch, "holder-pi-case")
    leases.acquire_mark("hostrepo", str(repo), "hold", "integration")
    as_pi(monkeypatch, "pi-session-777")
    (repo / "gen.json").write_text('{"x": 1}\n')
    with pytest.raises(CommitError, match="hold integration"):
        commit_git_revision(repo, message="pi", skip_checks=True, paths=["gen.json"])


def test_no_overlap_awareness_output_is_empty(repos, monkeypatch):
    repo = repos["hostrepo"]
    as_claude(monkeypatch, "lonely-000001")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    assert coord.notices() == []
    assert coord.dirty_owner_line("hostrepo", repo) is None
    coord.guard(repo, "publish")


# ------------------------------------------------------------ real hook, separate processes

def _hook(payload: dict, tmp: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in {
        "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "TMUX_PANE", "ST_SESSION_ID",
        "CODEX_SESSION_ID", "ALLOW_LEASE_OVERLAP", "ST_COORD_SENSITIVE", "PI_SESSION_ID"}}
    # Exercise this checkout's coord code, not the deployed release.
    clean.update({"ST_LEASES_DIR": str(tmp / "hook-leases"), "ST_DEV_CHECKOUT": "1", "ST_COORD_ANCHOR": "", **env})
    # Harnesses run hooks with the user's PATH; the native gate's allowlist lacks coreutils.
    clean["PATH"] = f"{clean.get('PATH', '')}:/usr/bin:/bin"
    return subprocess.run(["bash", str(HOOK), *args], input=json.dumps(payload), capture_output=True,
                          text=True, env=clean, check=False, timeout=30)


def test_real_hook_claude_edit_then_codex_apply_patch(repos, tmp_path):
    repo = repos["hostrepo"]
    claude = {"session_id": "11111111-aaaa", "tool_name": "Edit", "cwd": str(repo),
              "tool_input": {"file_path": str(repo / "backend" / "a.py")}}
    first = _hook(claude, tmp_path)
    assert first.returncode == 0 and first.stderr == ""
    patch = "*** Begin Patch\n*** Update File: backend/a.py\n@@\n-a = 1\n+a = 2\n*** End Patch\n"
    codex = {"session_id": "22222222-bbbb", "tool_name": "apply_patch", "cwd": str(repo),
             "transcript_path": "/home/u/.codex/sessions/x.jsonl", "tool_input": {"command": patch}}
    second = _hook(codex, tmp_path)
    assert second.returncode == 2
    lines = second.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("BLOCKED: hostrepo: backend/a.py leased by cc:111111")
    assert _hook(claude, tmp_path).returncode == 0  # same session keeps editing
    assert _hook(codex, tmp_path, ALLOW_LEASE_OVERLAP="1").returncode == 0



# ------------------------------------------------------------ context resets (lineage)

HARNESSES = [
    pytest.param(("claude_code", "CLAUDE_CODE_SESSION_ID", "cc"), id="claude"),
    pytest.param(("codex", "CODEX_THREAD_ID", "codex"), id="codex"),
    pytest.param(("pi", "PI_SESSION_ID", "pi"), id="pi"),
]
_SESSION_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "PI_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_SESSION_ID")


@pytest.fixture
def harness_procs():
    """Live stand-ins for harness processes; the anchor is '<pid>:<start tick>'."""
    procs: list[subprocess.Popen] = []

    def spawn() -> tuple[str, subprocess.Popen]:
        proc = _sleeper()
        procs.append(proc)
        return f"{proc.pid}:{leases._process_start(proc.pid)}", proc

    yield spawn
    for proc in procs:
        proc.kill()
        proc.wait()


def become(monkeypatch, harness: tuple[str, str, str], sid: str, anchor: str) -> str:
    provider, var, prefix = harness
    for name in _SESSION_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(var, sid)
    monkeypatch.setenv("ST_COORD_ANCHOR", anchor)
    monkeypatch.setenv("ST_COORD_HARNESS", provider)
    return f"{prefix}:{sid[:6]}"


def _peer(monkeypatch, anchor: str) -> str:
    return become(monkeypatch, ("claude_code", "CLAUDE_CODE_SESSION_ID", "cc"), "peer00-session", anchor)


@pytest.mark.parametrize("harness", HARNESSES)
def test_reset_with_held_lease_inherits_without_self_block(repos, monkeypatch, harness_procs, harness):
    repo = repos["hostrepo"]
    anchor, _ = harness_procs()
    peer_anchor, _ = harness_procs()
    old = become(monkeypatch, harness, "old111-context", anchor)
    coord_lineage.observe()
    leases.acquire_mark("hostrepo", str(repo), "hold", "integration")
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None
    (repo / "backend" / "a.py").write_text("a = 4\n")

    new = become(monkeypatch, harness, "new222-context", anchor)  # /clear, /new: same process
    lines = coord_lineage.observe(reset=True, emit=True)
    assert lines == [f"continuing {old}: holds hostrepo; leased files hostrepo(1)"]
    assert _tokens(lines[0]) < 40
    assert coord.edit_conflict(str(repo / "backend" / "a.py")) is None  # no self-block
    coord.guard(repo, "publish")  # inherited hold counts as own
    assert commit_git_revision(repo, message="after reset", skip_checks=True, paths=["backend/a.py"])["status"] == "SUCCESS"
    assert coord.notices() == []  # notice was emitted once, nothing else open

    _peer(monkeypatch, peer_anchor)
    with pytest.raises(coord.CoordBlocked, match=f"hold integration by {old}"):
        coord.guard(repo, "publish")
    assert new != old


@pytest.mark.parametrize("harness", HARNESSES)
def test_reset_with_pending_ack_tells_successor_and_peer_once(repos, monkeypatch, harness_procs, harness):
    repo = repos["hostrepo"]
    anchor, _ = harness_procs()
    peer_anchor, _ = harness_procs()
    peer = _peer(monkeypatch, peer_anchor)
    coord_lineage.observe()
    leases.acquire_mark("hostrepo", str(repo), "hold", "integration")
    old = become(monkeypatch, harness, "old333-context", anchor)
    coord_lineage.observe()
    request = coord.send(peer, "publish hostrepo now?", project="hostrepo")

    become(monkeypatch, harness, "new444-context", anchor)
    assert coord_lineage.observe(reset=True, emit=True) == [
        f"continuing {old}: awaiting ack from {peer} on {request['id']}"]

    _peer(monkeypatch, peer_anchor)
    notes = coord.notices()
    assert f"{old} context reset (now {harness[2]}:new444); resend full ask if pending" in notes
    assert all("context reset" not in line for line in coord.notices())  # once
    coord.ack(request["id"], "yes")

    become(monkeypatch, harness, "new444-context", anchor)
    assert coord.notices() == [f"ACK {request['id']} yes from {peer}; close: st sessions confirm {request['id']}"]
    coord.guard(repo, "publish", with_ack=request["id"])
    coord.confirm(request["id"])


@pytest.mark.parametrize("harness", HARNESSES)
def test_peer_message_to_old_identity_reaches_successor(repos, monkeypatch, harness_procs, harness):
    repo = repos["hostrepo"]
    anchor, _ = harness_procs()
    peer_anchor, _ = harness_procs()
    old = become(monkeypatch, harness, "old555-context", anchor)
    coord_lineage.observe()
    leases.acquire_mark("hostrepo", str(repo), "hold", "release")
    become(monkeypatch, harness, "new666-context", anchor)
    coord_lineage.observe(reset=True, emit=True)

    _peer(monkeypatch, peer_anchor)
    with pytest.raises(coord.CoordBlocked, match=f"by {old}"):
        coord.guard(repo, "rebuild")
    request = coord.send(old, "rebuild hostrepo?", project="hostrepo")  # peer only knows the old id

    become(monkeypatch, harness, "new666-context", anchor)
    assert any(request["id"] in line for line in coord.notices())
    assert [row["id"] for row in coord.inbox()] == [request["id"]]
    coord.ack(request["id"], "yes")

    _peer(monkeypatch, peer_anchor)
    coord.guard(repo, "rebuild", with_ack=request["id"])  # ack by successor authorizes against old's hold


@pytest.mark.parametrize("harness", HARNESSES)
def test_stale_predecessor_is_not_inherited_and_expires_normally(repos, monkeypatch, harness_procs, harness):
    repo = repos["hostrepo"]
    target = str(repo / "backend" / "a.py")
    anchor, proc = harness_procs()
    old = become(monkeypatch, harness, "old777-context", anchor)
    coord_lineage.observe()
    assert coord.edit_conflict(target) is None
    proc.kill()
    proc.wait()  # harness exited: lineage is unclaimable

    new_anchor, _ = harness_procs()
    become(monkeypatch, harness, "new888-context", new_anchor)
    assert coord_lineage.observe(reset=True, emit=True) == []
    blocked = coord.edit_conflict(target)
    assert blocked is not None and f"leased by {old}" in blocked  # still protects its dirty file
    reused = f"{os.getpid()}:0"  # live pid, wrong start tick: a reused pid never revives a family
    assert not coord_lineage.anchor_alive(reused) and coord_lineage.family_ids(reused) == set()
    with leases._lock("hostrepo"):
        rows = leases._load("hostrepo")
        for row in rows:
            row.last_heartbeat = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
        leases._save("hostrepo", rows)
    assert coord.edit_conflict(target) is None
    assert old not in coord_lineage.load_doc().get("identities", {})


@pytest.mark.parametrize("harness", HARNESSES)
def test_reset_without_hook_is_detected_lazily(repos, monkeypatch, harness_procs, harness):
    """No SessionStart hook ran: the next st call from the same process notices the new id."""
    repo = repos["hostrepo"]
    anchor, _ = harness_procs()
    old = become(monkeypatch, harness, "oldaaa-context", anchor)
    coord_lineage.observe()
    assert coord.edit_conflict(str(repo / "gen.json")) is None
    become(monkeypatch, harness, "newbbb-context", anchor)
    assert coord.edit_conflict(str(repo / "gen.json")) is None  # family self, even before any hook
    lines = coord.notices()
    if harness[0] == "codex":
        # A new codex thread id on one process may be a subagent thread; only SessionStart reports resets.
        assert lines == []
    else:
        assert lines == [f"continuing {old}: leased files hostrepo(1)"]
        assert coord.notices() == []


def test_codex_subagent_thread_is_self_without_peer_notice(repos, monkeypatch, harness_procs):
    codex = ("codex", "CODEX_THREAD_ID", "codex")
    anchor, _ = harness_procs()
    peer_anchor, _ = harness_procs()
    peer = _peer(monkeypatch, peer_anchor)
    coord_lineage.observe()
    become(monkeypatch, codex, "parent-thread", anchor)
    coord_lineage.observe()
    coord.send(peer, "pause backend/** writes?")
    assert coord.edit_conflict(str(repos["hostrepo"] / "gen.json")) is None
    become(monkeypatch, codex, "child0-thread", anchor)
    assert coord.edit_conflict(str(repos["hostrepo"] / "gen.json")) is None
    assert coord_lineage.observe(subagent=True, emit=True) == []
    _peer(monkeypatch, peer_anchor)
    assert all("context reset" not in line for line in coord.notices())


def test_inherited_session_variable_of_another_harness_is_ignored(repos, monkeypatch, harness_procs):
    """Codex launched from a Claude shell inherits CLAUDE_CODE_SESSION_ID; it is still codex."""
    anchor, _ = harness_procs()
    become(monkeypatch, ("codex", "CODEX_THREAD_ID", "codex"), "codexx-thread", anchor)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-parent")
    assert leases.identify_agent()[0] == "codex:codexx"
    monkeypatch.delenv("CODEX_THREAD_ID")  # a codex shell without its own id falls back to the inherited one
    assert leases.identify_agent()[0] == "cc:claude"
    coord_lineage.observe()  # ...which never joins the codex process's family
    assert coord_lineage.family_ids(anchor) == set()


def test_real_hook_session_start_and_shell_write_overlap(repos, tmp_path, harness_procs):
    repo = repos["hostrepo"]
    anchor, _ = harness_procs()
    env = {"ST_COORD_ANCHOR": anchor, "ST_COORD_HARNESS": "claude_code"}
    edit = {"hook_event_name": "PreToolUse", "session_id": "aaaa11-old", "tool_name": "Edit", "cwd": str(repo),
            "tool_input": {"file_path": str(repo / "backend" / "a.py")}}
    assert _hook(edit, tmp_path, **env).returncode == 0
    start = {"hook_event_name": "SessionStart", "source": "clear", "session_id": "bbbb22-new", "cwd": str(repo)}
    started = _hook(start, tmp_path, "session", **env)
    assert started.returncode == 0 and started.stderr == ""
    context = json.loads(started.stdout)["hookSpecificOutput"]["additionalContext"]
    assert context == "continuing cc:aaaa11: leased files hostrepo(1)"
    assert _hook(start, tmp_path, "session", **env).stdout == ""  # silent once known
    edit["session_id"] = "bbbb22-new"
    assert _hook(edit, tmp_path, **env).returncode == 0  # successor keeps editing

    # Another agent's shell command rewrites the leased file: one warning line after the fact.
    other_anchor, _ = harness_procs()
    shell = {"hook_event_name": "PreToolUse", "session_id": "cccc33-other", "tool_name": "Bash",
             "tool_use_id": "toolu_1", "cwd": str(repo), "tool_input": {"command": "sed -i s/1/2/ backend/a.py"}}
    other = {"ST_COORD_ANCHOR": other_anchor, "ST_COORD_HARNESS": "claude_code"}
    assert _hook(shell, tmp_path, "bash-pre", **other).returncode == 0
    (repo / "backend" / "a.py").write_text("a = 7\n")
    (repo / "backend" / "new.py").write_text("n = 1\n")
    post = _hook({**shell, "hook_event_name": "PostToolUse"}, tmp_path, "bash-post", **other)
    assert post.returncode == 2
    lines = post.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("OVERLAP: this shell command wrote hostrepo: backend/a.py leased by cc:aaaa11")
    # A read-only command is silent and costs no Python start.
    assert _hook(shell, tmp_path, "bash-pre", **other).returncode == 0
    quiet = _hook({**shell, "hook_event_name": "PostToolUse"}, tmp_path, "bash-post", **other)
    assert quiet.returncode == 0 and quiet.stderr == ""


def test_uuid7_sessions_started_hours_apart_keep_distinct_identities(repos, monkeypatch):
    """Codex and Pi ids are UUIDv7: the first 6 chars are a timestamp shared by every session for ~4.6 h."""
    target = str(repos["hostrepo"] / "backend" / "a.py")
    as_codex(monkeypatch, "01a12620-c916-7aa1-afa8-f774ce8af197")
    assert leases.identify_agent()[0] == "codex:8af197"
    assert coord.edit_conflict(target) is None
    as_codex(monkeypatch, "01a1265b-7c0d-7b53-81f1-3f6104ba944f")
    blocked = coord.edit_conflict(target)
    assert blocked is not None and "leased by codex:8af197" in blocked
    assert not coord._addresses("01a126", "codex:04ba944f", "01a1265b-7c0d-7b53-81f1-3f6104ba944f")
