"""Cross-session sweep guard: writer sets, advisory edit leases, lineage-scoped lease ownership.

Scenarios switch native session identities on disposable fixture repos the way
separate Claude Code / Codex sessions present them; subprocess cases drive the
real lease-hook script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cli.lib import commit_workflow, coord, coord_lineage, leases
from cli.lib.commit_workflow import CommitError, commit_git_revision
from cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / "scripts" / "lib" / "lease-hook"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _init(repo: Path) -> Path:
    (repo / "backend").mkdir(parents=True)
    (repo / "backend" / "a.py").write_text("a = 1\n")
    (repo / "backend" / "b.py").write_text("b = 1\n")
    (repo / "gen.json").write_text("{}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for name in ("TMUX_PANE", "CLAUDE_SESSION_ID", "PI_SESSION_ID", "ST_COORD_HARNESS", "ST_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ST_COORD_ANCHOR", "")
    return _init(tmp_path / "hostrepo")


def as_claude(monkeypatch, sid: str) -> None:
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)


def as_codex(monkeypatch, sid: str) -> None:
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", sid)


def _shell_write(repo: Path, rel: str, text: str | None) -> None:
    """A shell command of the current session writes (or deletes, text=None) one file; bash-post records it."""
    since = datetime.now(UTC) - timedelta(seconds=1)
    target = repo / rel
    if text is None:
        target.unlink()
    else:
        target.write_text(text)
    dirty = [str(repo / path) for path in coord.dirty_paths(repo) or []]
    coord.record_shell_writes([str(target)], since, dirty=dirty)


# ------------------------------------------------------------ the reproduced sweep

def test_whole_tree_commit_refuses_another_sessions_shell_write(repo, monkeypatch):
    """Two sessions in one checkout: B's whole-tree commit used to absorb A's shell-written file."""
    as_claude(monkeypatch, "aaaaaaaa-session")
    _shell_write(repo, "backend/a.py", "a = 2  # A's work\n")
    as_codex(monkeypatch, "bbbbbbbb-session")
    _shell_write(repo, "backend/b.py", "b = 2  # B's work\n")

    with pytest.raises(CommitError) as refused:
        commit_git_revision(repo, message="sweep", skip_checks=True)
    text = str(refused.value)
    assert "backend/a.py<-cc:aaaaaa" in text and "--paths <file>" in text
    assert "backend/b.py" not in text
    assert _git(repo, "log", "--format=%s").splitlines() == ["init"]

    # A directory scope sweeps the same way.
    with pytest.raises(CommitError, match=r"backend/a\.py"):
        commit_git_revision(repo, message="sweep dir", skip_checks=True, paths=["backend"])

    # The explicit escape commits only B's file and leaves A's work dirty and attributed.
    result = commit_git_revision(repo, message="mine", skip_checks=True, paths=["backend/b.py"])
    assert result["status"] == "SUCCESS"
    assert _git(repo, "status", "--porcelain").split() == ["M", "backend/a.py"]
    assert set(leases.writers("hostrepo")) == {str((repo / "backend" / "a.py").resolve())}
    log = (leases.LEASES_DIR / "_sweep_refusals.jsonl").read_text().splitlines()
    assert len(log) == 2 and json.loads(log[0])["paths"] == ["backend/a.py<-cc:aaaaaa"]


def test_explicit_file_written_by_another_session_is_refused_until_taken(repo, monkeypatch):
    as_claude(monkeypatch, "aaaaaaaa-session")
    _shell_write(repo, "gen.json", '{"a": 1}\n')
    as_codex(monkeypatch, "bbbbbbbb-session")
    _shell_write(repo, "gen.json", '{"a": 1, "b": 2}\n')
    with pytest.raises(CommitError, match=r"another session also wrote gen.json<-cc:aaaaaa.*st lease --take"):
        commit_git_revision(repo, message="both", skip_checks=True, paths=["gen.json"])
    leases.take("hostrepo", str(repo / "gen.json"))
    assert commit_git_revision(repo, message="adopted", skip_checks=True, paths=["gen.json"])["status"] == "SUCCESS"
    assert leases.writers("hostrepo") == {}


def test_unknown_writer_blocks_broad_scope_but_not_an_explicit_file(repo, monkeypatch):
    as_claude(monkeypatch, "aaaaaaaa-session")
    since = datetime.now(UTC) - timedelta(seconds=1)
    (repo / "gen.json").write_text('{"bg": 1}\n')
    coord.record_shell_writes([str(repo / "gen.json")], since, background=True)
    with pytest.raises(CommitError, match=r"gen.json<-unknown\(background\)"):
        commit_git_revision(repo, message="all", skip_checks=True)
    assert commit_git_revision(repo, message="named", skip_checks=True, paths=["gen.json"])["status"] == "SUCCESS"


def test_own_writes_and_unrecorded_dirt_commit_whole_tree(repo, monkeypatch):
    as_claude(monkeypatch, "aaaaaaaa-session")
    _shell_write(repo, "backend/a.py", "a = 3\n")
    (repo / "notes.txt").write_text("no hook saw this\n")
    assert commit_git_revision(repo, message="all mine", skip_checks=True)["status"] == "SUCCESS"


def test_deletion_by_another_session_is_attributed(repo, monkeypatch):
    as_claude(monkeypatch, "aaaaaaaa-session")
    _shell_write(repo, "backend/b.py", None)
    as_codex(monkeypatch, "bbbbbbbb-session")
    (repo / "gen.json").write_text('{"b": 1}\n')
    with pytest.raises(CommitError, match=r"backend/b\.py<-cc:aaaaaa"):
        commit_git_revision(repo, message="sweep delete", skip_checks=True)


# ------------------------------------------------------------ writer-set lifetime

def test_writer_sets_outlive_the_old_24h_touch_window_until_commit_or_revert(repo, monkeypatch):
    as_claude(monkeypatch, "aaaaaaaa-session")
    _shell_write(repo, "backend/a.py", "a = 9\n")
    _shell_write(repo, "backend/b.py", "b = 9\n")
    key_a, key_b = (str((repo / "backend" / name).resolve()) for name in ("a.py", "b.py"))
    with leases._lock("hostrepo"):
        doc = leases._read("hostrepo")
        for entries in doc["writers"].values():
            for entry in entries:
                entry["at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        leases._save("hostrepo", leases._load("hostrepo"), doc["writers"])
    assert set(leases.writers("hostrepo")) == {key_a, key_b}

    _git(repo, "checkout", "--", "backend/b.py")  # reverted
    as_codex(monkeypatch, "bbbbbbbb-session")
    _shell_write(repo, "gen.json", '{"x": 1}\n')  # the next record in the repo prunes clean paths
    assert set(leases.writers("hostrepo")) == {key_a, str((repo / "gen.json").resolve())}


def test_legacy_touch_records_fold_into_writer_sets(repo, monkeypatch):
    as_claude(monkeypatch, "aaaaaaaa-session")
    (repo / "gen.json").write_text('{"legacy": 1}\n')
    path = str((repo / "gen.json").resolve())
    with leases._lock("hostrepo"):
        leases._store_path("hostrepo").parent.mkdir(parents=True, exist_ok=True)
        leases._store_path("hostrepo").write_text(json.dumps({"leases": [], "touches": {path: {
            "agent_id": "cc:olderr", "session_id": "olderr", "at": datetime.now(UTC).isoformat()}}}))
    assert [e["agent_id"] for e in leases.writers("hostrepo")[path]] == ["cc:olderr"]
    assert leases.touches("hostrepo")[path]["agent_id"] == "cc:olderr"
    with pytest.raises(CommitError, match=r"gen\.json<-cc:olderr"):
        commit_git_revision(repo, message="legacy", skip_checks=True)


def test_shell_write_concurrent_with_another_sessions_edit_is_unknown(repo, monkeypatch):
    """Either session may own a path both touched during the command: both broad commits stay refused."""
    as_codex(monkeypatch, "bbbbbbbb-session")
    since = datetime.now(UTC) - timedelta(seconds=5)
    as_claude(monkeypatch, "aaaaaaaa-session")
    assert coord.edit_conflict(str(repo / "gen.json")) is None  # A edits while B's command runs
    (repo / "gen.json").write_text('{"a": 1}\n')
    as_codex(monkeypatch, "bbbbbbbb-session")
    coord.record_shell_writes([str(repo / "gen.json")], since)
    entries = leases.writers("hostrepo")[str((repo / "gen.json").resolve())]
    assert [leases.writer_label(e) for e in entries] == ["cc:aaaaaa", "unknown(concurrent)"]
    with pytest.raises(CommitError, match=r"gen\.json"):
        commit_git_revision(repo, message="B sweep", skip_checks=True)
    as_claude(monkeypatch, "aaaaaaaa-session")
    with pytest.raises(CommitError, match=r"gen\.json<-unknown\(concurrent\)"):
        commit_git_revision(repo, message="A sweep", skip_checks=True)
    assert commit_git_revision(repo, message="A named", skip_checks=True, paths=["gen.json"])["status"] == "SUCCESS"


def test_shell_write_on_a_path_another_session_leased_earlier_is_attributed_to_the_writer(repo, monkeypatch):
    """A foreign lease's heartbeat ticking during my command must not hand my shell write to its holder."""
    as_claude(monkeypatch, "aaaaaaaa-session")
    assert leases.claim("hostrepo", str(repo / "backend" / "a.py"), str(repo))[0]
    as_codex(monkeypatch, "bbbbbbbb-session")
    since = datetime.now(UTC)
    as_claude(monkeypatch, "aaaaaaaa-session")
    assert leases.claim("hostrepo", str(repo / "backend" / "b.py"), str(repo))[0]  # refreshes A's a.py heartbeat
    (repo / "backend" / "a.py").write_text("a = 9  # B's sed\n")
    as_codex(monkeypatch, "bbbbbbbb-session")
    coord.record_shell_writes([str(repo / "backend" / "a.py")], since)
    entries = leases.writers("hostrepo")[str((repo / "backend" / "a.py").resolve())]
    assert [leases.writer_label(e) for e in entries] == ["cc:aaaaaa", "codex:bbbbbb"]
    as_claude(monkeypatch, "aaaaaaaa-session")
    with pytest.raises(CommitError, match=r"backend/a\.py<-codex:bbbbbb"):
        commit_git_revision(repo, message="A sweep", skip_checks=True)


# ------------------------------------------------------------ advisory edit leases

def test_edit_hook_warns_on_foreign_lease_and_records_both_writers(repo, monkeypatch):
    target = str(repo / "backend" / "a.py")
    as_claude(monkeypatch, "aaaaaaaa-session")
    assert coord.run_hook({"tool_input": {"file_path": target}, "cwd": str(repo)}) is None
    as_codex(monkeypatch, "bbbbbbbb-session")
    message = coord.run_hook({"tool_input": {"file_path": target}, "cwd": str(repo)})
    assert message is not None and message.startswith("WARNING: hostrepo: backend/a.py leased by cc:aaaaaa")
    assert "\n" not in message
    assert coord.dispatch_hook({"tool_input": {"file_path": target}, "cwd": str(repo)}) == ("context", message)
    (repo / "backend" / "a.py").write_text("a = 5\n")
    labels = sorted(e["agent_id"] for e in leases.writers("hostrepo")[str(Path(target).resolve())])
    assert labels == ["cc:aaaaaa", "codex:bbbbbb"]
    as_claude(monkeypatch, "aaaaaaaa-session")
    with pytest.raises(CommitError):
        commit_git_revision(repo, message="contested", skip_checks=True, paths=["backend/a.py"])


def test_op_lease_still_blocks_edits(repo, monkeypatch):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lease = leases.acquire_mark("hostrepo", str(repo), "op", "acceptance")
        with leases._lock("hostrepo"):
            rows = leases._load("hostrepo")
            for row in rows:
                if row.lease_id == lease.lease_id:
                    row.pid, row.pid_start = proc.pid, leases._process_start(proc.pid)
            leases._save("hostrepo", rows)
        as_claude(monkeypatch, "aaaaaaaa-session")
        result = coord.dispatch_hook({"tool_input": {"file_path": str(repo / "gen.json")}, "cwd": str(repo)})
        assert result is not None and result[0] == "block" and result[1].startswith("BLOCKED: ")
    finally:
        proc.kill()
        proc.wait()


# ------------------------------------------------------------ lineage-scoped lease ownership

@pytest.fixture
def anchor():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield f"{proc.pid}:{leases._process_start(proc.pid)}"
    proc.kill()
    proc.wait()


def _codex_thread(monkeypatch, sid: str, anchor: str) -> None:
    as_codex(monkeypatch, sid)
    monkeypatch.setenv("ST_COORD_ANCHOR", anchor)
    monkeypatch.setenv("ST_COORD_HARNESS", "codex")
    coord_lineage.observe()


def test_codex_child_release_all_keeps_sibling_and_parent_leases(repo, monkeypatch, anchor):
    _codex_thread(monkeypatch, "parent-thread-1", anchor)
    coord.session_start({"hook_event_name": "SessionStart", "source": "startup", "session_id": "parent-thread-1"})
    leases.acquire("hostrepo", ["backend/a.py"], project_root=str(repo))
    _codex_thread(monkeypatch, "kid111-thread", anchor)
    leases.acquire("hostrepo", ["backend/b.py"], project_root=str(repo))
    _codex_thread(monkeypatch, "kid222-thread", anchor)
    leases.acquire("hostrepo", ["gen.json"], project_root=str(repo))

    assert leases.release("hostrepo") == 1  # only its own
    held = sorted((lease.agent_id, Path(lease.globs[0]).name) for lease in leases.list_active("hostrepo"))
    assert held == [("codex:kid111", "b.py"), ("codex:parent", "a.py")]
    # The parent's release-all leaves the child's lease too.
    _codex_thread(monkeypatch, "parent-thread-1", anchor)
    assert leases.release("hostrepo") == 1
    assert [Path(lease.globs[0]).name for lease in leases.list_active("hostrepo")] == ["b.py"]
    # The child's writes still count as the session's: the parent commits them, leased or not.
    _codex_thread(monkeypatch, "kid111-thread", anchor)
    assert leases.root_key() == "codex:parent"
    _shell_write(repo, "backend/b.py", "b = 7\n")
    _codex_thread(monkeypatch, "parent-thread-1", anchor)
    assert commit_git_revision(repo, message="session work", skip_checks=True)["status"] == "SUCCESS"


def test_main_thread_successor_still_owns_predecessor_leases(repo, monkeypatch, anchor):
    _codex_thread(monkeypatch, "old-thread-0001", anchor)
    coord.session_start({"hook_event_name": "SessionStart", "source": "startup", "session_id": "old-thread-0001"})
    leases.acquire("hostrepo", ["backend/a.py"], project_root=str(repo))
    _codex_thread(monkeypatch, "new-thread-0002", anchor)  # /new on the same process
    coord.session_start({"hook_event_name": "SessionStart", "source": "clear", "session_id": "new-thread-0002"})
    assert leases.release("hostrepo") == 1
    assert leases.list_active("hostrepo") == []


# ------------------------------------------------------------ multi-glob release

def test_release_one_glob_keeps_the_rest_of_a_multi_glob_lease(repo, monkeypatch):
    as_claude(monkeypatch, "aaaaaaaa-session")
    lease = leases.acquire("hostrepo", ["backend/**", "gen.json"], project_root=str(repo))
    assert leases.release("hostrepo", "gen.json", project_root=str(repo)) == 1
    (kept,) = leases.list_active("hostrepo")
    assert kept.lease_id == lease.lease_id and kept.globs == [str(repo / "backend/**")]
    assert leases.release("hostrepo", lease.lease_id) == 1
    assert leases.list_active("hostrepo") == []


# ------------------------------------------------------------ repo lock wait

def test_commit_lock_wait_is_five_minutes_with_progress_lines(tmp_path, monkeypatch, capsys):
    import fcntl
    import threading

    assert commit_workflow.REPO_LOCK_WAIT_SECONDS == 300.0
    repo = _init(tmp_path / "lockrepo")
    (repo / "gen.json").write_text('{"x": 1}\n')
    lock = repo / ".git/st/repo-mutation.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    handle = lock.open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    monkeypatch.setattr(commit_workflow, "REPO_LOCK_POLL_SECONDS", 0.02)
    monkeypatch.setattr(commit_workflow, "REPO_LOCK_PROGRESS_SECONDS", 0.1)
    monkeypatch.setattr(commit_workflow, "_refresh_symbols_after_publish", lambda _repo, result: result)
    timer = threading.Timer(0.45, handle.close)
    timer.start()
    try:
        result = commit_workflow.commit_repo(repo, message="waited", skip_checks=True, paths=("gen.json",))
    finally:
        timer.cancel()
        handle.close()
    err = capsys.readouterr().err
    assert result["status"] == "SUCCESS"
    assert err.count("another repository operation is running; waiting up to 300s") == 1
    assert err.count("still waiting for the repository lock") >= 2


# ------------------------------------------------------------ multi-value --paths

@pytest.mark.parametrize(("argv", "expected"), [
    (["--paths", "a.py", "b.py"], ("a.py", "b.py")),
    (["--paths", "a.py", "b.py", "--task", "t1"], ("a.py", "b.py")),
    (["--paths", "a.py", "--paths", "b.py"], ("a.py", "b.py")),
    (["--path", "a.py", "b.py", "--paths", "c.py"], ("a.py", "c.py", "b.py")),
])
def test_st_commit_accepts_several_values_per_paths(argv, expected):
    with (
        patch("cli.main.current_repo", return_value=Path("/repo")),
        patch("cli.main.commit_repo", return_value={"repo": "repo", "status": "SKIP", "pushed": False}) as commit,
        patch("cli.main._log_commit_event"),
    ):
        result = CliRunner().invoke(app, ["commit", "-m", "msg", *argv])
    assert result.exit_code == 0, result.output
    assert commit.call_args.kwargs["paths"] == expected


def test_st_commit_rejects_stray_words_without_paths():
    with patch("cli.main.current_repo", return_value=Path("/repo")), patch("cli.main.commit_repo") as commit:
        result = CliRunner().invoke(app, ["commit", "-m", "msg", "stray.py"])
    assert result.exit_code == 1 and "unexpected argument(s): stray.py" in result.output
    commit.assert_not_called()


# ------------------------------------------------------------ real hook script

def _hook(payload: dict | str, tmp: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in {
        "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "TMUX_PANE", "ST_SESSION_ID",
        "CODEX_SESSION_ID", "ST_COORD_SENSITIVE", "PI_SESSION_ID"}}
    clean.update({"ST_LEASES_DIR": str(tmp / "hook-leases"), "ST_DEV_CHECKOUT": "1", "ST_COORD_ANCHOR": "",
                  "XDG_RUNTIME_DIR": str(tmp / "run"), **env})
    clean["PATH"] = f"{clean.get('PATH', '')}:/usr/bin:/bin"
    (tmp / "run").mkdir(exist_ok=True)
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(["bash", str(HOOK), *args], input=data, capture_output=True,
                          text=True, env=clean, check=False, timeout=30)


def _hook_writers(tmp: Path, project: str = "hostrepo") -> dict[str, list[str]]:
    doc = json.loads((tmp / "hook-leases" / f"{project}.json").read_text())
    return {Path(p).name: sorted(leases.writer_label(e) for e in entries) for p, entries in doc["writers"].items()}


def _shell(repo: Path, sid: str, tool: str, command: str, **extra) -> dict:
    return {"hook_event_name": "PreToolUse", "session_id": sid, "tool_name": "Bash", "tool_use_id": tool,
            "cwd": str(repo), "tool_input": {"command": command, **extra}}


def test_real_hook_records_shell_writes_and_deletions_then_commit_refuses_the_sweep(repo, tmp_path, monkeypatch):
    env = {"ST_COORD_HARNESS": "claude_code"}
    shell = _shell(repo, "aaaaaaaa-1111", "toolu_1", "sed -i s/1/2/ backend/a.py && rm backend/b.py")
    assert _hook(shell, tmp_path, "bash-pre", **env).returncode == 0
    (repo / "backend" / "a.py").write_text("a = 2\n")
    (repo / "backend" / "b.py").unlink()
    post = _hook({**shell, "hook_event_name": "PostToolUse"}, tmp_path, "bash-post", **env)
    assert (post.returncode, post.stderr) == (0, "")
    assert _hook_writers(tmp_path) == {"a.py": ["cc:aaaaaa"], "b.py": ["cc:aaaaaa"]}

    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path / "hook-leases")
    as_claude(monkeypatch, "bbbbbbbb-2222")
    (repo / "gen.json").write_text('{"b": 1}\n')
    with pytest.raises(CommitError, match=r"backend/a.py<-cc:aaaaaa, backend/b.py<-cc:aaaaaa"):
        commit_git_revision(repo, message="sweep", skip_checks=True)


def test_real_hook_marks_background_and_other_repo_writes_unknown(repo, tmp_path):
    other = _init(repo.parent / "siblingrepo")
    env = {"ST_COORD_HARNESS": "claude_code"}
    shell = _shell(repo, "aaaaaaaa-1111", "toolu_2", f"cd {other} && touch new.txt", run_in_background=True)
    assert _hook(shell, tmp_path, "bash-pre", **env).returncode == 0
    (other / "new.txt").write_text("x\n")
    (repo / "gen.json").write_text('{"bg": 1}\n')
    assert _hook({**shell, "hook_event_name": "PostToolUse"}, tmp_path, "bash-post", **env).returncode == 0
    assert _hook_writers(tmp_path) == {"gen.json": ["unknown(background)"]}
    assert _hook_writers(tmp_path, "siblingrepo") == {"new.txt": ["unknown(other-repo)"]}


def test_real_hook_edit_collision_reaches_the_model_and_exits_zero(repo, tmp_path):
    """The warning is PreToolUse additionalContext (stdout JSON): exit-0 stderr reaches no harness model."""
    target = str(repo / "backend" / "a.py")
    claude = {"session_id": "11111111-aaaa", "hook_event_name": "PreToolUse", "tool_name": "Edit",
              "cwd": str(repo), "tool_input": {"file_path": target}}
    first = _hook(claude, tmp_path)
    assert (first.returncode, first.stdout, first.stderr) == (0, "", "")
    patch_text = "*** Begin Patch\n*** Update File: backend/a.py\n@@\n-a = 1\n+a = 2\n*** End Patch\n"
    codex = {"session_id": "22222222-bbbb", "hook_event_name": "PreToolUse", "tool_name": "apply_patch",
             "cwd": str(repo), "transcript_path": "/home/u/.codex/sessions/x.jsonl",
             "tool_input": {"command": patch_text}}
    second = _hook(codex, tmp_path)
    assert (second.returncode, second.stderr) == (0, "")
    output = json.loads(second.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse" and "permissionDecision" not in output
    assert output["additionalContext"].startswith("WARNING: hostrepo: backend/a.py leased by cc:111111")
    assert _hook_writers(tmp_path) == {"a.py": ["cc:111111", "codex:222222"]}
    again = _hook(claude, tmp_path)  # the first session keeps editing and now hears of the second
    assert again.returncode == 0 and "leased by codex:222222" in again.stdout


def test_real_hook_escaped_payload_falls_back_to_python_parse(repo, tmp_path):
    """A cwd with a JSON escape is parsed by Python; plain payloads never start it on bash-pre."""
    odd = _init(repo.parent / 'q"repo')
    shell = _shell(odd, "aaaaaaaa-1111", "toolu_3", "true")
    assert _hook(shell, tmp_path, "bash-pre").returncode == 0
    markers = list((tmp_path / "run" / "st-lease-bash").iterdir())
    assert [m.name for m in markers] == ["aaaaaaaa-1111-toolu_3"]
    assert str(odd) in markers[0].read_text()
