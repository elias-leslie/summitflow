"""Hourly publication: private repos push their head, public repos their newest accepted commit."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.tasks import backup_publish
from app.tasks import nightly_deep_lane as deep_lane
from app.tasks import nightly_publication as nightly
from tests.tasks.git_helpers import _git

DAY = datetime(2026, 10, 10, 15, 5, tzinfo=UTC)  # 11:05 EDT
NIGHT = datetime(2026, 10, 10, 7, 5, tzinfo=UTC)  # 03:05 EDT, the containment hour


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
    monkeypatch.setattr(backup_publish, "remote_repository", lambda *_: {"private": True, "default_branch": "main"})
    return project


def _public(monkeypatch, accepted: set[str]) -> None:
    monkeypatch.setattr(backup_publish, "remote_repository", lambda *_: {"private": False, "default_branch": "main"})
    monkeypatch.setattr(backup_publish, "_acceptance_for_head",
                        lambda _root, sha: {"state": "reused" if sha in accepted else "missing"})


def _receipt(project: Path, sha: str, observation: dict) -> None:
    directory = project / ".git" / "st" / "publication"
    directory.mkdir(parents=True, exist_ok=True)
    value = {"kind": "manual_publication.v1", "schema_version": 1, "source_commit": sha,
             "requested_source_commit": sha, "project_id": "fixture", "observed_at": "2026-10-10T07:00:00+00:00",
             "observation": observation, "previous_receipt_id": None}
    value["receipt_id"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (directory / f"{sha}.json").write_text(json.dumps(value))


def test_manual_projects_are_never_selected(repo):
    assert nightly.select_candidate("fixture", repo, "manual") == {
        "project_id": "fixture", "mode": "manual", "action": "skip", "reason": "manual_mode"}


def test_private_repository_publishes_committed_head_without_acceptance(repo):
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert (row["action"], row["reason"], row["visibility"]) == ("publish", "private_head", "private")
    assert row["sha"] == _git(repo, "rev-parse", "HEAD") and row["ahead"] == 1 and row["behind"] == 0


def test_stored_mirror_mode_reads_as_nightly(monkeypatch):
    stored = {"publication_mode": "mirror"}
    monkeypatch.setattr(nightly, "get_agent_config", lambda _project: stored)
    monkeypatch.setattr(nightly, "update_agent_config", lambda _project, config: stored.update(config))
    assert nightly.publication_mode("fixture") == "nightly"
    assert nightly.set_publication_mode("fixture", "mirror") == "nightly"
    assert stored["publication_mode"] == "nightly"


def test_public_repository_publishes_its_newest_accepted_commit(repo, monkeypatch):
    accepted = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-am", "not yet accepted")
    _public(monkeypatch, {accepted})
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert (row["action"], row["reason"], row["sha"]) == ("publish", "accepted", accepted)
    assert row["unaccepted_later"] is True
    _public(monkeypatch, set())
    assert nightly.select_candidate("fixture", repo, "nightly")["reason"] == "no_accepted_commit"


def test_public_commits_stuck_without_acceptance_for_a_day_need_attention(repo, monkeypatch):
    _public(monkeypatch, set())
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert row["reason"] == "no_accepted_commit" and 0 <= row["waiting_seconds"] < 600
    assert not nightly.needs_attention(row)  # normal gap before the next acceptance
    assert nightly.needs_attention({**row, "waiting_seconds": nightly.STALE_UNACCEPTED_SECONDS})


def test_unknown_visibility_never_publishes_and_auth_loss_is_surfaced(repo, monkeypatch):
    from cli.lib.github_publish import GitHubError

    expired = GitHubError("unavailable", unavailable=True, reason="remote_authentication_unavailable")
    monkeypatch.setattr(backup_publish, "remote_repository", Mock(side_effect=expired))
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert (row["action"], row["reason"]) == ("skip", "remote_authentication_unavailable")
    assert nightly.needs_attention(row)
    monkeypatch.setattr(backup_publish, "remote_repository", Mock(side_effect=GitHubError(
        "unavailable", unavailable=True, reason="remote_rate_limited")))
    assert not nightly.needs_attention(nightly.select_candidate("fixture", repo, "nightly"))  # transient
    monkeypatch.setattr(backup_publish, "remote_repository", Mock(side_effect=KeyError("bug")))
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert row["reason"] == "remote_visibility_unknown" and nightly.needs_attention(row)
    _git(repo, "remote", "set-url", "origin", "https://gitlab.com/fixture/project.git")
    monkeypatch.setattr(backup_publish, "remote_repository", lambda *_: None)
    assert nightly.select_candidate("fixture", repo, "nightly")["reason"] == "no_accepted_commit"  # non-GitHub counts as public


def test_up_to_date_and_diverged_heads_are_skipped(repo):
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", head)
    assert nightly.select_candidate("fixture", repo, "nightly")["reason"] == "up_to_date"
    other = _git(repo, "commit-tree", "-p", head, "-m", "remote", _git(repo, "hash-object", "-w", "-t", "tree", "/dev/null"))
    _git(repo, "update-ref", "refs/remotes/origin/main", other)
    assert nightly.select_candidate("fixture", repo, "nightly")["reason"] == "diverged_from_remote"


@pytest.mark.parametrize(("observation", "reason", "action"), [
    ({"publication_complete": True, "status": "published"}, "published", "skip"),
    ({"status": "failed", "reason": "outgoing_verification_failed"}, "awaiting_repair", "skip"),
    ({"status": "pending", "reason": "workflow_effects_authorization_required",
      "unauthorized_workflows": [".github/workflows/ci.yml"]}, "owner_action_required", "skip"),
    ({"status": "pending", "reason": "remote_transport_unavailable"}, "private_head", "publish"),
])
def test_retained_receipt_decides_retry_or_wait(repo, observation, reason, action):
    _receipt(repo, _git(repo, "rev-parse", "HEAD"), observation)
    row = nightly.select_candidate("fixture", repo, "nightly")
    assert (row["reason"], row["action"]) == (reason, action)


def test_hold_keeps_later_commits_local_and_caps_at_released_source(repo, monkeypatch):
    released = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-am", "needs review")
    assert nightly.select_candidate("fixture", repo, "nightly", {"through": None})["reason"] == "held"
    row = nightly.select_candidate("fixture", repo, "nightly", {"through": released})
    assert (row["action"], row["sha"], row["held_through"]) == ("publish", released, released)
    _public(monkeypatch, set())
    assert nightly.select_candidate("fixture", repo, "nightly", {"through": released})["reason"] == "no_accepted_commit"
    stray = _git(repo, "commit-tree", "-m", "elsewhere", f"{released}^{{tree}}")
    assert nightly.select_candidate("fixture", repo, "nightly", {"through": stray})["reason"] == "hold_source_not_on_branch"


def test_execute_publishes_the_selected_source_and_records_state(repo, monkeypatch):
    head = _git(repo, "rev-parse", "HEAD")
    publisher = Mock(return_value={"status": "published", "reason": "source_published", "publication_complete": True})
    monkeypatch.setattr("app.tasks.backup_manual_publish.publish_project_now", publisher)
    row = nightly.execute_candidate({"project_id": "fixture", "sha": head, "mode": "nightly", "action": "publish"}, repo)
    publisher.assert_called_once_with("fixture", head)
    assert (row["outcome"], row["publication_complete"]) == ("published", True)
    assert (nightly.read_nightly_state(repo) or {}).get("sha") == head


def _sweep(monkeypatch, repo, rows_by_mode):
    monkeypatch.setattr(nightly, "_projects", lambda _ids: [(name, repo) for name in rows_by_mode])
    monkeypatch.setattr(nightly, "publication_mode", lambda name: rows_by_mode[name])
    monkeypatch.setattr(nightly, "publication_hold", lambda _name: None)
    codeql = Mock()
    monkeypatch.setattr(nightly, "observe_codeql", codeql)
    executed = Mock(side_effect=lambda row, _root: {**row, "outcome": "published", "reason": "source_published"})
    monkeypatch.setattr(nightly, "execute_candidate", executed)
    notify = Mock()
    monkeypatch.setattr(nightly, "_notify", notify)
    containment = Mock(return_value=None)
    monkeypatch.setattr(nightly, "remote_containment", containment)
    return executed, notify, containment, codeql


def test_hourly_pass_runs_all_day_and_never_defers_on_activity(repo, monkeypatch):
    # Live edits (the fixture's WIP), heavy work and agents' repo holds never
    # defer a push; only the owner's publication hold does (select_candidate).
    monkeypatch.setattr("app.utils.heavy_work.lane_activity", Mock(side_effect=AssertionError("not consulted")))
    monkeypatch.setattr("cli.lib.leases.list_active", Mock(side_effect=AssertionError("not consulted")))
    executed, notify, containment, codeql = _sweep(monkeypatch, repo, {"a": "nightly", "b": "manual", "c": "nightly"})
    result = nightly.run_nightly_publication(now=DAY)
    rows = {row["project_id"]: row for row in result["projects"]}
    assert [call.args[0]["project_id"] for call in executed.call_args_list] == ["a", "c"]
    assert rows["b"]["reason"] == "manual_mode"
    notify.assert_called_once()
    containment.assert_not_called()  # only in the nightly containment hour
    codeql.assert_not_called()


def test_dry_run_selects_without_executing_or_notifying(repo, monkeypatch):
    executed, notify, _, _ = _sweep(monkeypatch, repo, {"a": "nightly"})
    dry = nightly.run_nightly_publication(dry_run=True, now=DAY)
    assert dry["status"] == "dry_run" and dry["projects"][0]["action"] == "publish"
    executed.assert_not_called()
    notify.assert_not_called()


def test_nightly_hour_checks_github_containment(repo, monkeypatch):
    _, notify, containment, codeql = _sweep(monkeypatch, repo, {"a": "nightly"})
    lost = {"project_id": "a", "mode": "nightly", "action": "check", "reason": "remote_not_containing_published"}
    containment.return_value = lost
    result = nightly.run_nightly_publication(now=NIGHT)
    assert lost in result["projects"]
    assert nightly.needs_attention(lost)
    assert lost in notify.call_args.args[0]
    codeql.assert_called_once_with("a", repo, "nightly")


@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A checkout whose upstream matches a local bare remote."""
    remote = tmp_path / "remote.git"
    project = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(project)], check=True, capture_output=True)
    _git(project, "-c", "user.name=F", "-c", "user.email=f@example.invalid", "commit", "--allow-empty", "-m", "one")
    _git(project, "-c", "core.hooksPath=/dev/null", "push", "-q", "-u", "origin", "main")
    original = backup_publish._git

    def local(root, *args):
        if args[0] in {"ls-remote", "fetch"}:  # the guarded transport refuses local paths; read the bare repo directly
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
        return original(root, *args)

    monkeypatch.setattr(backup_publish, "_git", local)
    return project, remote


def test_containment_passes_while_github_contains_the_last_published_commit(published):
    project, _remote = published
    assert nightly.remote_containment("p", project, "nightly") is None
    assert nightly.remote_containment("p", project, "manual") is None


def test_containment_flags_a_rewound_or_unknown_remote(published, tmp_path):
    project, remote = published
    _git(project, "-c", "user.name=F", "-c", "user.email=f@example.invalid", "commit", "--allow-empty", "-m", "two")
    _git(project, "-c", "core.hooksPath=/dev/null", "push", "-q", "origin", "main")
    # GitHub's branch moves back to an older commit: the published one is gone.
    subprocess.run(["git", "-C", str(remote), "update-ref", "refs/heads/main", _git(project, "rev-parse", "HEAD~1")], check=True)
    row = nightly.remote_containment("p", project, "nightly")
    assert row is not None and row["reason"] == "remote_not_containing_published"
    subprocess.run(["git", "-C", str(remote), "update-ref", "-d", "refs/heads/main"], check=True)
    row = nightly.remote_containment("p", project, "nightly")
    assert row is not None and row["reason"] == "remote_branch_missing"


def test_containment_fetches_a_remote_commit_it_lacks_before_judging(published, tmp_path):
    """GitHub moving ahead from elsewhere still contains the published commit;
    an object missing locally must not read as a lost publication."""
    project, remote = published
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True, capture_output=True)
    _git(other, "-c", "user.name=F", "-c", "user.email=f@example.invalid", "commit", "--allow-empty", "-m", "elsewhere")
    _git(other, "-c", "core.hooksPath=/dev/null", "push", "-q", "origin", "main")
    assert nightly.remote_containment("p", project, "nightly") is None


def test_containment_that_cannot_run_is_reported_not_silent(published, monkeypatch):
    project, _remote = published
    original = backup_publish._git
    monkeypatch.setattr(backup_publish, "_git", lambda root, *args: subprocess.CompletedProcess(
        args, 128, "", "offline") if args[0] == "ls-remote" else original(root, *args))
    row = nightly.remote_containment("p", project, "nightly")
    assert row is not None and row["reason"] == "remote_containment_unverified" and nightly.needs_attention(row)


def test_nightly_codeql_read_records_github_projects_only(repo, monkeypatch):
    from app.services import publication_security

    evidence = {"state": "success", "reason": "codeql_default_source_verified"}
    observe = Mock(return_value=evidence)
    record = Mock()
    monkeypatch.setattr(publication_security, "observe_codeql", observe)
    monkeypatch.setattr(publication_security, "record_codeql_observation", record)
    nightly.observe_codeql("fixture", repo, "nightly")
    observe.assert_called_once_with(repo, "fixture/project")
    record.assert_called_once_with(repo, evidence, project_id="fixture")
    nightly.observe_codeql("fixture", repo, "manual")
    _git(repo, "remote", "set-url", "origin", "https://gitlab.com/fixture/project.git")
    nightly.observe_codeql("fixture", repo, "nightly")
    assert observe.call_count == 1
    observe.side_effect = RuntimeError("api down")
    _git(repo, "remote", "set-url", "origin", "https://github.com/fixture/project.git")
    nightly.observe_codeql("fixture", repo, "nightly")  # never breaks the pass


def test_attention_notifies_once_per_distinct_set_per_day(monkeypatch):
    created = Mock()
    monkeypatch.setattr("app.storage.notifications.create_notification", created)
    row = {"project_id": "p", "mode": "nightly", "sha": "a" * 40, "action": "skip", "reason": "owner_action_required",
           "unauthorized_workflows": [".github/workflows/ci.yml"]}
    assert nightly.needs_attention(row)
    assert "--authorize-workflow .github/workflows/ci.yml" in nightly.summary_line(row)
    assert not nightly.needs_attention({**row, "reason": "up_to_date", "unauthorized_workflows": []})
    nightly._notify([row, {**row, "project_id": "q", "reason": "up_to_date"}], DAY)
    nightly._notify([row], DAY)
    keys = [call.kwargs["dedupe_key"] for call in created.call_args_list]
    assert keys[0] == keys[1] and keys[0].startswith("publication-2026-10-10-")
    nightly._notify([{**row, "reason": "diverged_from_remote"}], DAY)
    assert created.call_args.kwargs["dedupe_key"] != keys[0]


def test_deep_lane_busy_check_still_sees_fresh_edits(repo):
    assert deep_lane._recently_edited(repo, time.time())  # fixture just wrote WIP
    assert not deep_lane._recently_edited(repo, time.time() + 2 * deep_lane.RECENT_EDIT_SECONDS)
    assert deep_lane.busy_reason("fixture", repo) == "recent_edits"


def test_retired_projects_are_never_considered(monkeypatch, tmp_path):
    monkeypatch.setattr("app.storage.projects.list_projects", lambda: [
        {"id": "live", "root_path": str(tmp_path / "live")}, {"id": "old", "root_path": str(tmp_path / "old")}])
    monkeypatch.setattr("app.project_identity.get_project_lifecycles",
                        lambda ids, **_: {project_id: "retired" if project_id == "old" else "active" for project_id in ids})
    assert nightly._projects(None) == [("live", tmp_path / "live")]
