"""Closeout friction: requirement waivers, literal bracket paths, range scope, plan diffs, parent claims."""
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import task_acceptance
from app.services.task_acceptance import assess_completion

SHA = "a" * 40


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    return tmp_path


def _live_task(waivers=None):
    requirements = {"deployment": False, "live_checks": ["Telegram status report delivers", "api-health"]}
    if waivers is not None:
        requirements["waivers"] = waivers
    passed = {"id": "api-health", "state": "success", "artifact": "a.json", "sha256": "b" * 64}
    return {"commits": [SHA], "context": {"completion_requirements": requirements}, "verification_result": {
        "acceptance": {"state": "success", "source_commit": SHA, "coverage": "task"},
        "live_validation": {"source_commit": SHA, "checks": [passed]}}}


def test_waived_live_check_is_satisfied_by_its_recorded_waiver():
    gates = assess_completion(_live_task()).gates
    assert gates == ({"gate": "live_validation", "pass": False, "detail": ["Telegram status report delivers"]},)
    waiver = {"check": "Telegram status report delivers", "kind": "waived", "reason": "Telegram retired", "actor": "me"}
    assert assess_completion(_live_task([waiver])).gates == ()
    # A waiver without a reason is never silent permission.
    assert assess_completion(_live_task([{**waiver, "reason": " "}])).gates == gates


def _amend_store(monkeypatch, status="running"):
    spirit = {"context": {"completion_requirements": {"live_checks": ["old check"]}}, "done_when": ["tests pass"]}
    updates, events = [], []
    monkeypatch.setattr("app.storage.tasks.get_task", lambda _: {"id": "task-1", "status": status})
    monkeypatch.setattr("app.storage.task_spirit.get_task_spirit", lambda _: spirit)
    monkeypatch.setattr("app.storage.task_spirit.update_task_spirit", lambda _id, **kw: updates.append(kw))
    monkeypatch.setattr("app.storage.events.log_task_event", lambda *a, **kw: events.append((a, kw)))
    return updates, events


def test_waiver_and_replacement_are_audited_without_resetting_the_plan(monkeypatch):
    updates, events = _amend_store(monkeypatch)
    record = task_acceptance.amend_completion_requirement("task-1", "old check", reason="owner retired it", actor="cc:me")
    assert record["kind"] == "waived" and record["actor"] == "cc:me"
    context = updates[0]["context"]
    assert "plan_status" not in updates[0]
    assert context["completion_requirements"]["live_checks"] == ["old check"]
    assert task_acceptance.active_live_checks(context["completion_requirements"]) == []
    assert events[0][1]["event_type"] == "completion_requirement_amended"

    updates, _ = _amend_store(monkeypatch)
    record = task_acceptance.amend_completion_requirement("task-1", "tests pass", reason="scope moved", actor="cc:me",
                                                          replacement="smoke passes")
    assert updates[0]["done_when"] == ["smoke passes"] and record["field"] == "done_when"


@pytest.mark.parametrize(("check", "reason", "status", "message"), [
    ("old check", "", "running", "--reason"),
    ("unknown", "why", "running", "matches exactly"),
    ("old check", "why", "completed", "historical"),
])
def test_amendment_refuses_silent_or_unknown_changes(monkeypatch, check, reason, status, message):
    _amend_store(monkeypatch, status)
    with pytest.raises(ValueError, match=message):
        task_acceptance.amend_completion_requirement("task-1", check, reason=reason, actor="cc:me")


def test_update_cli_requires_reason_and_prints_the_waiver(monkeypatch):
    from typer.testing import CliRunner

    from cli.commands import tasks

    amend = Mock(return_value={"check": "c", "kind": "waived", "reason": "owner", "actor": "me", "at": "now"})
    monkeypatch.setattr("app.services.task_acceptance.amend_completion_requirement", amend)
    result = CliRunner().invoke(tasks.app, ["update", "task-1", "--waive-check", "c"])
    assert result.exit_code == 1 and "--reason" in result.output
    amend.assert_not_called()
    result = CliRunner().invoke(tasks.app, ["update", "task-1", "--replace-check", "c=d", "--reason", "owner"])
    assert result.exit_code == 0, result.output
    assert amend.call_args.kwargs["replacement"] == "d" and amend.call_args.args[1] == "c"


def test_context_shows_amendments():
    from cli._formatters_context_task import _format_requirement_lines

    waiver = {"check": "Telegram", "kind": "waived", "reason": "retired", "actor": "me", "at": "t"}
    lines = _format_requirement_lines({"context": {"completion_requirements": {"live_checks": ["Telegram", "x"],
                                                                                 "waivers": [waiver]}}})
    assert lines == ["LIVE_CHECKS[1]:x", "REQUIREMENT_AMENDED:'Telegram' waived (me, t): retired"]


def test_bracket_route_paths_are_literal_when_they_exist(tmp_path, monkeypatch):
    from cli.commands.done_task_scope import closeout_paths
    from cli.lib import commit_workflow

    repo = _repo(tmp_path)
    for name in ("app/[id]/page.tsx", "app/i/page.tsx"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("before")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    (repo / "app/[id]/page.tsx").write_text("after")
    (repo / "app/i/page.tsx").write_text("unrelated")
    monkeypatch.setattr("cli.lib.leases.list_active", lambda *a, **k: [])
    assert closeout_paths(str(repo), "task-1", {}, project_id="example", paths=("app/[id]/page.tsx",)) == ("app/[id]/page.tsx",)
    with pytest.raises(ValueError, match="unsupported scope"):
        closeout_paths(str(repo), "task-1", {}, project_id="example", paths=("app/[x]/missing.tsx",))
    monkeypatch.setattr(commit_workflow, "run_checks", lambda repo, **kw: (True, ""))
    result = commit_workflow.commit_git_revision(repo, message="route", paths=("app/[id]/page.tsx",))
    assert result["status"] == "SUCCESS"
    assert _git(repo, "show", "--format=", "--name-only", "HEAD") == "app/[id]/page.tsx"
    assert _git(repo, "status", "--porcelain") == "M app/i/page.tsx"


def test_paths_from_range_lists_added_and_modified_files(tmp_path):
    from cli.commands.done_task_scope import paths_from_range

    repo = _repo(tmp_path)
    (repo / "keep.py").write_text("1")
    (repo / "gone.py").write_text("1")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "keep.py").write_text("2")
    (repo / "new.py").write_text("1")
    _git(repo, "rm", "-q", "gone.py")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "work")
    assert paths_from_range(str(repo), f"{base}..HEAD") == ("keep.py", "new.py")
    with pytest.raises(ValueError, match=r"<base>\.\.<head>"):
        paths_from_range(str(repo), "--output=x")
    with pytest.raises(ValueError, match="no files"):
        paths_from_range(str(repo), "HEAD..HEAD")


def test_plan_mismatch_names_changed_inputs():
    from cli.lib.acceptance import plan_differences

    recorded = {"gate_implementation": {"cli/commands/check.py": "a", "x.py": "b"}, "commands": [1], "fingerprint": "1"}
    current = {"gate_implementation": {"cli/commands/check.py": "c", "x.py": "b"}, "commands": [2], "fingerprint": "2"}
    assert plan_differences(recorded, current) == ["commands", "gate_implementation:cli/commands/check.py"]


def test_subtask_claim_renews_own_parent_claim_and_names_expiry(monkeypatch):
    import typer

    from cli.commands import claim

    monkeypatch.setattr(claim, "require_claim_safe_tree", lambda: None)
    monkeypatch.setattr(claim, "_current_caller_id", lambda: "me")
    client = Mock()
    client.get_task.return_value = {"id": "task-1", "status": "running", "claimed_by": "me"}
    claim._claim_subtask(client, "1.1", "task-1")
    client.claim_task.assert_called_once_with("task-1", renew_only=True)

    client = Mock()
    client.get_task.return_value = {"id": "task-1", "status": "running", "claimed_by": "someone-else"}
    claim._claim_subtask(client, "1.1", "task-1")
    client.claim_task.assert_not_called()

    errors = []
    monkeypatch.setattr(claim, "output_error", errors.append)
    client.get_task.return_value = {"id": "task-1", "status": "pending"}
    with pytest.raises(typer.Exit):
        claim._claim_subtask(client, "1.1", "task-1")
    assert "expired" in errors[0] and errors[0].endswith("Re-claim: st claim task-1")
