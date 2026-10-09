"""Overnight publication selects only committed, eligible heads and never blocks day work."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.tasks import backup_publish
from app.tasks import nightly_publication as nightly
from tests.tasks.test_backup_native_recovery import _git

NIGHT = datetime(2026, 10, 10, 7, 30, tzinfo=UTC)  # 03:30 EDT


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "note").write_text("published")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "published")
    _git(project, "remote", "add", "origin", "https://github.com/fixture/project.git")
    _git(project, "update-ref", "refs/remotes/origin/main", _git(project, "rev-parse", "HEAD"))
    _git(project, "branch", "--set-upstream-to", "origin/main")
    (project / "note").write_text("committed")
    _git(project, "commit", "-am", "unpublished")
    (project / "note").write_text("work in progress")  # never published
    monkeypatch.setattr(backup_publish, "_acceptance_for_head", lambda *_: {"state": "missing"})
    return project


def _receipt(project: Path, sha: str, observation: dict) -> None:
    directory = project / ".git" / "st" / "publication"
    directory.mkdir(parents=True, exist_ok=True)
    value = {"kind": "manual_publication.v1", "schema_version": 1, "source_commit": sha,
              "requested_source_commit": sha, "project_id": "fixture", "observed_at": "2026-10-10T07:00:00+00:00",
              "observation": observation, "previous_receipt_id": None}
    value["receipt_id"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (directory / f"{sha}.json").write_text(json.dumps(value))


@pytest.mark.parametrize(("utc", "open_"), [
    (datetime(2026, 10, 10, 4, 59, tzinfo=UTC), False),   # 00:59 EDT
    (datetime(2026, 10, 10, 5, 5, tzinfo=UTC), True),     # 01:05 EDT
    (datetime(2026, 10, 10, 9, 55, tzinfo=UTC), True),    # 05:55 EDT
    (datetime(2026, 10, 10, 10, 5, tzinfo=UTC), False),   # 06:05 EDT
    (datetime(2026, 12, 10, 5, 30, tzinfo=UTC), False),   # 00:30 EST
    (datetime(2026, 12, 10, 10, 30, tzinfo=UTC), True),   # 05:30 EST
])
def test_window_is_new_york_local_across_dst(utc, open_):
    assert nightly.publication_window_open(utc) is open_


def test_manual_projects_are_never_selected(repo):
    assert nightly.select_candidate("fixture", repo, "manual") == {
        "project_id": "fixture", "mode": "manual", "action": "skip", "reason": "manual_mode"}


def test_committed_head_without_receipt_is_accepted_first_and_wip_is_ignored(repo):
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert row["action"] == "accept_then_publish" and row["sha"] == _git(repo, "rev-parse", "HEAD")
    assert row["ahead"] == 1 and row["behind"] == 0 and row["resume"] is False


def test_accepted_head_publishes_and_mirror_needs_no_receipt(repo, monkeypatch):
    monkeypatch.setattr(backup_publish, "_acceptance_for_head", lambda *_: {"state": "reused"})
    assert nightly.select_candidate("fixture", repo, "nightly")["action"] == "publish"
    monkeypatch.setattr(backup_publish, "_acceptance_for_head", Mock(side_effect=AssertionError("mirror")))
    assert nightly.select_candidate("fixture", repo, "mirror")["action"] == "publish"


def test_up_to_date_and_diverged_heads_are_skipped(repo):
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", head)
    assert nightly.select_candidate("fixture", repo, "nightly")["reason"] == "up_to_date"
    _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "commit-tree", "-p", head, "-m", "remote", f"{head}^{{tree}}"))
    assert nightly.select_candidate("fixture", repo, "nightly")["reason"] == "diverged_from_remote"


@pytest.mark.parametrize(("observation", "reason", "action"), [
    ({"publication_complete": True, "status": "published"}, "published", "skip"),
    ({"status": "failed", "reason": "outgoing_verification_failed"}, "awaiting_repair", "skip"),
    ({"status": "pending", "reason": "workflow_effects_authorization_required",
      "unauthorized_workflows": [".github/workflows/ci.yml"]}, "owner_action_required", "skip"),
    ({"status": "pending", "reason": "remote_ci_pending"}, "acceptance_missing", "accept_then_publish"),
    ({"status": "pending", "reason": "remote_authentication_unavailable"}, "acceptance_missing", "accept_then_publish"),
])
def test_retained_receipt_decides_resume_or_wait(repo, observation, reason, action):
    head = _git(repo, "rev-parse", "HEAD")
    _receipt(repo, head, observation)
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert (row["reason"], row["action"]) == (reason, action)


def test_failed_night_acceptance_is_not_retried_until_head_changes(repo):
    head = _git(repo, "rev-parse", "HEAD")
    nightly._write_nightly_state(repo, {"sha": head, "outcome": "acceptance_failed"})
    assert nightly.select_candidate("fixture", repo, "nightly")["reason"] == "acceptance_failed"
    _git(repo, "commit", "-am", "fix")
    assert nightly.select_candidate("fixture", repo, "nightly")["action"] == "accept_then_publish"


def _sweep(monkeypatch, repo, rows_by_mode, busy=None):
    monkeypatch.setattr(nightly, "_projects", lambda _ids: [(name, repo) for name in rows_by_mode])
    monkeypatch.setattr(nightly, "publication_mode", lambda name: rows_by_mode[name])
    monkeypatch.setattr(nightly, "busy_reason", lambda name, _root: (busy or {}).get(name))
    executed = Mock(side_effect=lambda row, _root: {**row, "outcome": "published", "reason": "source_publication_verified"})
    monkeypatch.setattr(nightly, "execute_candidate", executed)
    notify = Mock()
    monkeypatch.setattr(nightly, "_notify", notify)
    return executed, notify


def test_sweep_outside_window_does_nothing(repo, monkeypatch):
    executed, _ = _sweep(monkeypatch, repo, {"a": "nightly"})
    assert nightly.run_nightly_publication(now=datetime(2026, 10, 10, 15, 0, tzinfo=UTC)) == {"status": "outside_window"}
    executed.assert_not_called()


def test_sweep_runs_eligible_projects_one_at_a_time_and_skips_busy(repo, monkeypatch):
    monkeypatch.setattr(nightly, "publication_window_open", lambda *_: True)
    executed, notify = _sweep(monkeypatch, repo, {"a": "nightly", "b": "manual", "c": "mirror"}, busy={"c": "active_writers"})
    result = nightly.run_nightly_publication(now=NIGHT)
    rows = {row["project_id"]: row for row in result["projects"]}
    assert executed.call_count == 1 and executed.call_args.args[0]["project_id"] == "a"
    assert rows["b"]["reason"] == "manual_mode" and rows["c"]["reason"] == "active_writers"
    notify.assert_not_called()  # 03:30 is not the final window run


def test_dry_run_selects_without_executing_and_final_run_notifies(repo, monkeypatch):
    executed, notify = _sweep(monkeypatch, repo, {"a": "nightly"})
    dry = nightly.run_nightly_publication(dry_run=True, now=datetime(2026, 10, 10, 15, 0, tzinfo=UTC))
    assert dry["status"] == "dry_run" and dry["projects"][0]["action"] == "accept_then_publish"
    executed.assert_not_called()
    monkeypatch.setattr(nightly, "publication_window_open", lambda *_: True)
    nightly.run_nightly_publication(now=datetime(2026, 10, 10, 9, 5, tzinfo=UTC))  # 05:05 EDT
    notify.assert_called_once()


def test_failed_acceptance_records_repair_and_never_publishes(repo, monkeypatch):
    head = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(nightly, "_run_acceptance", lambda *_: {"state": "failed", "reason": "acceptance_failed", "evidence": "x.json"})
    observed = Mock()
    monkeypatch.setattr("app.services.publication_health.record_publication_observation", observed)
    publisher = Mock(side_effect=AssertionError("unaccepted source published"))
    monkeypatch.setattr("app.tasks.backup_manual_publish.publish_project_now", publisher)
    row = nightly.execute_candidate({"project_id": "fixture", "sha": head, "mode": "nightly",
                                     "action": "accept_then_publish"}, repo)
    assert row["outcome"] == "acceptance_failed"
    assert observed.call_args.args[1]["reason"] == "nightly_acceptance_failed"
    assert (nightly.read_nightly_state(repo) or {}).get("sha") == head


def test_attention_lines_print_the_exact_authorization_command():
    row = {"project_id": "p", "mode": "nightly", "sha": "a" * 40, "action": "skip", "reason": "owner_action_required",
           "unauthorized_workflows": [".github/workflows/ci.yml"]}
    assert nightly.needs_attention(row)
    assert "--authorize-workflow .github/workflows/ci.yml" in nightly.summary_line(row)
    assert not nightly.needs_attention({**row, "reason": "up_to_date", "unauthorized_workflows": []})


def test_inputs_changing_during_acceptance_defer_without_a_repair_finding(repo, monkeypatch):
    head = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(nightly, "_run_acceptance", lambda *_: {"state": "unavailable", "reason": "acceptance_unavailable"})
    observed = Mock()
    monkeypatch.setattr("app.services.publication_health.record_publication_observation", observed)
    row = nightly.execute_candidate({"project_id": "fixture", "sha": head, "mode": "nightly",
                                     "action": "accept_then_publish"}, repo)
    assert row["outcome"] == "deferred"
    observed.assert_not_called()
    assert nightly.read_nightly_state(repo) is None


def test_only_failed_checks_are_a_sticky_source_finding(repo):
    head = _git(repo, "rev-parse", "HEAD")
    receipts = repo / ".git" / "st" / "acceptance"
    receipts.mkdir(parents=True)
    (receipts / "a.json").write_text(json.dumps({"source": {"commit": head}, "reason": "acceptance_plan_changed_during_acceptance"}))
    assert not nightly._checks_failed(repo, head)
    (receipts / "a.json").write_text(json.dumps({"source": {"commit": head}, "reason": "acceptance_checks_failed"}))
    assert nightly._checks_failed(repo, head)


def test_fresh_uncommitted_edits_mean_someone_is_working(repo):
    import time

    assert nightly._recently_edited(repo, time.time())  # fixture just wrote WIP
    assert not nightly._recently_edited(repo, time.time() + 2 * nightly.RECENT_EDIT_SECONDS)
    assert nightly.busy_reason("fixture", repo) == "recent_edits"


def test_hold_keeps_later_commits_local_and_caps_at_released_source(repo):
    released = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-am", "needs review")
    assert nightly.select_candidate("fixture", repo, "nightly", {"through": None})["reason"] == "held"
    row = nightly.select_candidate("fixture", repo, "nightly", {"through": released})
    assert row["sha"] == released and row["held_through"] == released and row["action"] == "accept_then_publish"
    stray = _git(repo, "commit-tree", "-m", "elsewhere", f"{released}^{{tree}}")
    assert nightly.select_candidate("fixture", repo, "nightly", {"through": stray})["reason"] == "hold_source_not_on_branch"
