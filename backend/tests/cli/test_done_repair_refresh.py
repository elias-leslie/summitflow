"""Reclaimed repair closeout rechecks the original audited patch, never an empty diff."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer import Exit

from cli.commands.done_task import complete_task
from cli.lib import acceptance


@pytest.fixture
def repair_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    task_id = "task-repair-refresh"
    project_id = "repair-fixture"

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / "app.py").write_text("print('before')\n")
    git("add", "app.py")
    git("commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text("print('repaired')\n")
    git("commit", "-qam", "repair")
    head = git("rev-parse", "HEAD")
    receipt = acceptance.accept_revision(
        tmp_path, sha=head, scope=("app.py",), task_id=task_id,
        runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "fixture check", ""),
    )
    task: dict[str, Any] = {"id": task_id, "project_id": project_id, "status": "running",
                            "labels": ["publication-repair"], "verification_result": {}}
    snapshot = {"project_id": project_id, "base_branch": "main", "base_commit": head}
    events = [{"trace_id": task_id, "project_id": project_id,
               "message": f"st commit commit={head} pushed=false"}]
    client = MagicMock()
    client.get_task.return_value = task
    client.get_task_completion_readiness.return_value = {"ready": True, "gates": []}
    queued = MagicMock(return_value={"request_id": "fixture-closeout"})
    monkeypatch.setattr("app.services.task_closeout.get_closeout", lambda _task: None)
    monkeypatch.setattr("app.services.task_closeout.request_closeout", queued)
    monkeypatch.setattr("app.storage.tasks.closeout.release_closeout_claim", lambda *args: True)
    monkeypatch.setattr("app.storage.tasks.publication_repair.get_repair_task", lambda _project: task)
    monkeypatch.setattr("app.storage.events.get_events_by_trace", lambda *args, **kwargs: events)
    monkeypatch.setattr("cli.commands.done_task.get_snapshot_info", lambda _task: snapshot)
    monkeypatch.setattr("cli.commands.done_task.get_project_root_path", lambda _project: str(tmp_path))
    monkeypatch.setattr("cli.commands.done_task.capture_lifecycle_baseline", lambda **kwargs: None)
    monkeypatch.setattr("cli.commands.done_task.remove_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr("cli.commands.done._release_task_leases", lambda *args: None)

    def store(_task, _project, value):
        task["verification_result"].update(value)

    monkeypatch.setattr("app.storage.tasks.closeout.store_verification", store)
    return {"repo": tmp_path, "git": git, "head": head, "receipt": receipt,
            "task": task, "snapshot": snapshot, "events": events,
            "client": client, "queued": queued}


def finish(fixture: dict[str, Any], **kwargs: Any):
    options: dict[str, Any] = {"strict": True, "paths": ("app.py",), "acceptance_receipt": fixture["receipt"]}
    options.update(kwargs)
    return complete_task(fixture["client"], fixture["task"]["id"], **options)


def test_reclaimed_repair_requeues_exact_accepted_audited_source(repair_refresh):
    repair_refresh["events"].insert(0, {
        "trace_id": repair_refresh["task"]["id"],
        "project_id": repair_refresh["task"]["project_id"],
        "message": f"st commit commit={repair_refresh['git']('rev-parse', 'HEAD^')} pushed=false",
    })
    result = finish(repair_refresh)
    assert result["reason"] == "nightly_repair_confirmation_pending"
    assert repair_refresh["queued"].call_args.kwargs["source_sha"] == repair_refresh["head"]
    repair_refresh["client"].update_status.assert_not_called()


def test_reclaimed_repair_preserves_unrelated_uncommitted_work(repair_refresh):
    unrelated = repair_refresh["repo"] / "other-agent.py"
    unrelated.write_text("print('unrelated work')\n")
    assert finish(repair_refresh)["action"] == "pending"
    assert unrelated.read_text() == "print('unrelated work')\n"
    assert repair_refresh["git"]("status", "--porcelain") == "?? other-agent.py"


@pytest.mark.parametrize("defect", [
    "no_event", "wrong_task_event", "wrong_project_event", "abbreviated_event",
    "ordinary_task", "wrong_rolling_task", "wrong_checkpoint_project", "no_receipt",
    "tampered_receipt", "selected_dirty", "foreign_head", "ancestor_event", "wrong_source",
    "empty_original_patch", "no_paths",
])
def test_repair_refresh_requires_exact_audited_accepted_patch(repair_refresh, monkeypatch, defect):
    fixture = repair_refresh
    options = {}
    if defect == "no_event":
        fixture["events"].clear()
    elif defect == "wrong_task_event":
        fixture["events"][0]["trace_id"] = "task-other"
    elif defect == "wrong_project_event":
        fixture["events"][0]["project_id"] = "other-project"
    elif defect == "abbreviated_event":
        fixture["events"][0]["message"] = f"st commit commit={fixture['head'][:12]} pushed=false"
    elif defect == "ordinary_task":
        fixture["task"]["labels"] = []
    elif defect == "wrong_rolling_task":
        monkeypatch.setattr("app.storage.tasks.publication_repair.get_repair_task",
                            lambda _project: {"id": "task-other"})
    elif defect == "wrong_checkpoint_project":
        fixture["snapshot"]["project_id"] = "other-project"
    elif defect == "no_receipt":
        options["acceptance_receipt"] = None
    elif defect == "tampered_receipt":
        fixture["receipt"]["acceptance_id"] = "0" * 64
    elif defect == "selected_dirty":
        (fixture["repo"] / "app.py").write_text("print('unaccepted edit')\n")
    elif defect == "no_paths":
        options["paths"] = ()
    else:
        # A later commit must not borrow the earlier repair's audited patch.
        if defect == "empty_original_patch":
            fixture["git"]("commit", "--allow-empty", "-qm", "empty work")
        else:
            (fixture["repo"] / "app.py").write_text("print('later source')\n")
            fixture["git"]("commit", "-qam", "later work")
        new_head = fixture["git"]("rev-parse", "HEAD")
        if defect not in {"wrong_source", "foreign_head"}:
            fixture["receipt"] = acceptance.accept_revision(
                fixture["repo"], sha=new_head,
                runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "fixture", ""),
            )
        fixture["snapshot"]["base_commit"] = new_head
        if defect in {"empty_original_patch", "wrong_source"}:
            fixture["events"][0]["message"] = f"st commit commit={new_head} pushed=false"
    with pytest.raises(Exit):
        finish(fixture, **options)
    fixture["queued"].assert_not_called()
    fixture["client"].update_status.assert_not_called()


def test_failure_inspecting_original_patch_cannot_requeue(repair_refresh, monkeypatch):
    original_run = subprocess.run
    parent = repair_refresh["git"]("rev-parse", "HEAD^")

    def fail_original_diff(command, *args, **kwargs):
        if command[1:3] == ["diff", "--numstat"] and command[-2] == parent:
            return subprocess.CompletedProcess(command, 1, "", "fixture Git inspection failure")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_original_diff)
    with pytest.raises(Exit):
        finish(repair_refresh)
    repair_refresh["queued"].assert_not_called()


@pytest.mark.parametrize("drift", ["selected_path", "head"])
def test_source_drift_during_original_patch_check_cannot_requeue(repair_refresh, monkeypatch, drift):
    original_run = subprocess.run
    parent = repair_refresh["git"]("rev-parse", "HEAD^")

    def change_after_original_diff(command, *args, **kwargs):
        result = original_run(command, *args, **kwargs)
        if command[1:3] == ["diff", "--numstat"] and command[-2] == parent:
            (repair_refresh["repo"] / "app.py").write_text("print('changed during check')\n")
            if drift == "head":
                original_run(["git", "commit", "-qam", "fixture source drift"],
                             cwd=repair_refresh["repo"], check=True, capture_output=True)
        return result

    monkeypatch.setattr(subprocess, "run", change_after_original_diff)
    with pytest.raises(Exit):
        finish(repair_refresh)
    repair_refresh["queued"].assert_not_called()
