"""st done closeout ergonomics: inferred scope, lapsed-claim recovery, multi-value paths, checkout roots."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import typer
from typer.testing import CliRunner

from cli.commands import claim, done, done_task
from cli.commands.done_task_scope import closeout_paths, paths_from_task_commits


def _repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "core.hooksPath", "/dev/null")
    for name in ("app.py", "gone.py", "other.py"):
        (path / name).write_text("before\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    return git


def _task_commit(path: Path, git, files: dict[str, str | None]) -> str:
    for name, content in files.items():
        if content is None:
            git("rm", "-q", name)
        else:
            (path / name).write_text(content)
            git("add", name)
    git("commit", "-qm", "task work")
    return git("rev-parse", "HEAD")


def test_task_commits_name_added_and_modified_paths_still_at_head(tmp_path):
    git = _repo(tmp_path)
    first = _task_commit(tmp_path, git, {"app.py": "after\n", "new.py": "new\n", "gone.py": None})
    second = _task_commit(tmp_path, git, {"other.py": "after\n"})
    assert paths_from_task_commits(str(tmp_path), [first, second]) == ("app.py", "new.py", "other.py")
    git("rm", "-q", "new.py")
    git("commit", "-qm", "another task removed it")
    assert paths_from_task_commits(str(tmp_path), [first]) == ("app.py",)


@pytest.mark.parametrize("commits", [[], ["0" * 40], ["--all"]])
def test_unlinked_or_foreign_task_commits_infer_nothing(tmp_path, commits):
    git = _repo(tmp_path)
    landed = _task_commit(tmp_path, git, {"app.py": "after\n"})
    assert paths_from_task_commits(str(tmp_path), [landed, *commits] if commits else []) == ()


def test_closeout_scope_defaults_to_task_commits_and_leaves_unrelated_work(tmp_path, capsys):
    git = _repo(tmp_path)
    sha = _task_commit(tmp_path, git, {"app.py": "after\n"})
    (tmp_path / "other.py").write_text("someone else's edit\n")
    task = {"id": "task-1", "commits": [sha]}
    assert closeout_paths(str(tmp_path), "task-1", task, project_id=None) == ("app.py",)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Selected 1 task path(s) from task-1's recorded commits." in output
    assert "Left 1 uncommitted path(s)" in output
    assert (tmp_path / "other.py").read_text() == "someone else's edit\n"


def test_uncommitted_edit_to_a_task_committed_path_needs_explicit_choice(tmp_path):
    git = _repo(tmp_path)
    sha = _task_commit(tmp_path, git, {"app.py": "after\n"})
    (tmp_path / "app.py").write_text("later edit\n")
    with pytest.raises(ValueError, match=r"Task path app\.py has uncommitted changes"):
        closeout_paths(str(tmp_path), "task-1", {"id": "task-1", "commits": [sha]}, project_id=None)


def test_task_without_linked_commits_keeps_the_explicit_paths_error(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app.py").write_text("unscoped edit\n")
    with pytest.raises(ValueError, match="Task scope is ambiguous"):
        closeout_paths(str(tmp_path), "task-1", {"id": "task-1", "commits": []}, project_id=None)


def test_no_change_since_checkpoint_no_longer_blocks(tmp_path):
    git = _repo(tmp_path)
    head = git("rev-parse", "HEAD")
    done_task._run_diff_gate(str(tmp_path), "task-1", "example", "main", base_commit=head)


def _completion_fixture(monkeypatch, task):
    client = Mock()
    client.get_task.return_value = task
    monkeypatch.setattr(done, "STClient", Mock(return_value=client))
    monkeypatch.setattr(done, "preflight", Mock())
    monkeypatch.setattr(done, "_report_requirement_amendments", Mock())
    monkeypatch.setattr(done, "_assess_budget", Mock(return_value=None))
    monkeypatch.setattr(done, "_release_task_leases", Mock())
    complete = Mock(return_value={})
    monkeypatch.setattr(done, "complete_task", complete)
    reclaim = Mock(return_value={"action": "resumed"})
    monkeypatch.setattr(claim, "_claim_task", reclaim)
    return client, reclaim, complete


def test_done_reclaims_a_lapsed_claim_through_st_claim(monkeypatch):
    _, reclaim, complete = _completion_fixture(monkeypatch, {
        "status": "pending", "project_id": "example", "claimed_by": None, "started_at": "2026-10-16T00:00:00Z"})
    result = CliRunner().invoke(done.app, ["task-1"])
    assert result.exit_code == 0, result.output
    reclaim.assert_called_once()
    assert reclaim.call_args.args[1] == "task-1"
    assert "Re-claimed task-1" in result.output
    complete.assert_called_once()


@pytest.mark.parametrize("task", [
    {"status": "running", "project_id": "example", "claimed_by": "another-agent", "started_at": "then"},
    {"status": "pending", "project_id": "example", "claimed_by": None, "started_at": None},
    {"status": "paused", "project_id": "example", "claimed_by": None, "started_at": "then"},
])
def test_done_never_takes_a_held_handed_off_or_unstarted_claim(monkeypatch, task):
    _, reclaim, _ = _completion_fixture(monkeypatch, task)
    CliRunner().invoke(done.app, ["task-1"])
    reclaim.assert_not_called()


def test_done_paths_accepts_several_values_per_flag(monkeypatch):
    _, _, complete = _completion_fixture(monkeypatch, {"status": "running", "project_id": "example"})
    result = CliRunner().invoke(done.app, ["task-1", "--paths", "src/a.py", "src/b.py", "--path", "tests"])
    assert result.exit_code == 0, result.output
    assert complete.call_args.kwargs["paths"] == ("src/a.py", "tests", "src/b.py")


def test_done_rejects_stray_arguments_without_paths(monkeypatch):
    _, _, complete = _completion_fixture(monkeypatch, {"status": "running", "project_id": "example"})
    result = CliRunner().invoke(done.app, ["task-1", "src/a.py"])
    assert result.exit_code == 2
    assert "Select task paths with --paths a b" in result.output
    complete.assert_not_called()


def test_checkout_root_follows_a_worktree_of_the_registered_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    git = _repo(repo)
    worktree = tmp_path / "wt"
    git("worktree", "add", "-q", "--detach", str(worktree))
    other = tmp_path / "other"
    _repo(other)
    monkeypatch.setattr(done_task, "get_project_root_path", lambda _project: str(repo))

    monkeypatch.chdir(worktree)
    assert done_task._checkpoint_repo_root("example") == str(worktree.resolve())
    monkeypatch.chdir(repo)
    assert done_task._checkpoint_repo_root("example") == str(repo)
    monkeypatch.chdir(other)
    assert done_task._checkpoint_repo_root("example") == str(repo)
    monkeypatch.chdir(tmp_path)
    assert done_task._checkpoint_repo_root("example") == str(repo)


def test_worktree_closeout_renews_the_claim_against_the_project_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    git = _repo(repo)
    worktree = tmp_path / "wt"
    git("worktree", "add", "-q", "--detach", str(worktree))
    renewed = Mock(return_value={"project_id": "example", "status": "running", "claimed_by": "me", "claimed_at": "now"})
    monkeypatch.setattr("cli.lib.task_claims.renew_local_owned_claim", renewed)
    monkeypatch.setattr("cli.lib.task_claims.current_worker_id", lambda: "me")
    done_task._owned_completion_claim(worktree, "task-1", "example")
    assert renewed.call_args.args[0] == repo.resolve()


def test_claim_refuses_while_another_session_writes_without_a_claim(monkeypatch):
    client = Mock()
    client.get_task.return_value = {"id": "task-1", "status": "pending", "project_id": "example",
                                    "plan_status": "approved"}
    monkeypatch.setattr(claim, "get_snapshot_info", lambda _task: None)
    monkeypatch.setattr("cli.commands.pulse.fetch_pulse_payload", lambda _project: {})
    monkeypatch.setattr("cli.commands.pulse.preflight_reasons_for_payload",
                        lambda _payload, **_kw: ["active_nonwriter_write_session"])
    with pytest.raises(typer.Exit) as exit_info:
        claim._claim_task(client, "task-1")
    assert exit_info.value.exit_code == 2
    client.claim_task.assert_not_called()
