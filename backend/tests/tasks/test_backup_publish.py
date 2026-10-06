"""Manual publication pins accepted immutable source and preserves working files."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services.git import utils as git_utils
from app.tasks import backup_publish as publish
from tests.tasks.test_backup_native_recovery import _git

_acceptance_lookup = publish._acceptance_for_head


@pytest.mark.parametrize("manual", [True])
@pytest.mark.parametrize('unavailable,expected', [(True, 'pending'), (False, 'failed')])
def test_typed_publication_error_is_pending_only_for_outages(source, monkeypatch, unavailable, expected, manual):
    from app.services.git import outgoing
    from cli.lib import publish_workflow
    project = Path(source['path'])
    original = publish._git
    def local_git(repo, *args):
        if args[0] == 'ls-remote':
            return subprocess.CompletedProcess(args, 0, '', '')
        return original(repo, *args)
    monkeypatch.setattr(publish, '_git', local_git)
    monkeypatch.setattr(outgoing, 'verify_outgoing', Mock(return_value=Mock(commits_scanned=2, refs_checked=1)))
    reason = 'remote_authentication_unavailable' if unavailable else 'remote_publication_failed'
    monkeypatch.setattr(publish_workflow, 'publish_git', Mock(side_effect=publish_workflow.PublishError('fixture-token-never-persist', unavailable=unavailable, reason=reason)))
    head = _git(project, 'rev-parse', 'HEAD')
    result = publish.publish_source_before_backup(source, manual_source_commit=head if manual else None)
    assert result['status'] == expected and result['reason'] == reason
    assert result['backup_can_continue'] and not result['publication_complete']
    assert result['head'] == _git(project, 'rev-parse', 'HEAD')
    assert result['security']['state'] == 'success'
    assert result['remote_status'] == ('unknown' if unavailable else 'blocked')
    assert 'fixture-token' not in json.dumps(result)


@pytest.mark.parametrize('phase', ['ls-remote', 'fetch', 'push'])
def test_network_transport_failure_never_becomes_project_repair(source, monkeypatch, phase):
    from app.services.git import outgoing
    from cli.lib import publish_workflow
    project = Path(source['path'])
    base = _git(project, 'rev-parse', 'origin/main')
    original = publish._git
    def local_git(repo, *args):
        if args[0] == phase:
            return subprocess.CompletedProcess(args, 128, '', 'fixture-secret-network-diagnostic')
        if args[0] == 'ls-remote':
            return subprocess.CompletedProcess(args, 0, f'{base}\trefs/heads/main\n', '')
        if args[0] == 'fetch':
            return subprocess.CompletedProcess(args, 0, '', '')
        return original(repo, *args)
    monkeypatch.setattr(publish, '_git', local_git)
    monkeypatch.setattr(outgoing, 'verify_outgoing', Mock(return_value=Mock(commits_scanned=2, refs_checked=1)))
    def canonical(repo, **kwargs):
        kwargs['run_git'](repo, ['push', 'origin', f"{kwargs['sha']}:refs/heads/main"])
        raise AssertionError('No completed delivery after outage')
    monkeypatch.setattr(publish_workflow, 'publish_git', canonical)
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result['status'] == 'pending' and result['reason'] == 'remote_transport_unavailable'
    assert result['remote_status'] == 'unknown' and not result['publication_complete']
    assert result['backup_can_continue'] and 'fixture-secret' not in json.dumps(result)


def test_network_timeout_is_typed_but_local_inspection_remains_actionable(tmp_path, monkeypatch):
    original = publish._git
    monkeypatch.setattr(publish.shutil, 'which', lambda _: '/usr/bin/timeout')
    monkeypatch.setattr(publish, '_git', lambda *_: subprocess.CompletedProcess([], 1, '', ''))
    monkeypatch.setattr(publish.safe_subprocess, 'run', Mock(side_effect=subprocess.TimeoutExpired('fixture', 310)))
    with pytest.raises(publish._TransportUnavailable):
        original(tmp_path, 'ls-remote', 'origin')
    with pytest.raises(publish._InspectionFailed) as exc:
        original(tmp_path, 'rev-parse', 'HEAD')
    assert not isinstance(exc.value, publish._TransportUnavailable)
    monkeypatch.setattr(publish.shutil, 'which', lambda _: None)
    with pytest.raises(publish._TransportUnavailable):
        original(tmp_path, 'ls-remote', 'origin')


def test_porcelain_ref_rejection_remains_actionable(source, monkeypatch):
    from app.services.git import outgoing
    from cli.lib import publish_workflow
    original = publish._git
    def local_git(repo, *args):
        if args[0] == 'ls-remote':
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'push':
            assert '--porcelain' in args
            return subprocess.CompletedProcess(args, 1, '!\tHEAD:refs/heads/main\t[remote rejected]\n', 'secret-diagnostic')
        return original(repo, *args)
    monkeypatch.setattr(publish, '_git', local_git)
    monkeypatch.setattr(outgoing, 'verify_outgoing', Mock(return_value=Mock(commits_scanned=2, refs_checked=1)))
    def canonical(repo, **kwargs):
        pushed = kwargs['run_git'](repo, ['push', 'origin', f"{kwargs['sha']}:refs/heads/main"])
        assert pushed.returncode == 1
        raise publish_workflow.PublishError('secret-diagnostic')
    monkeypatch.setattr(publish_workflow, 'publish_git', canonical)
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result['status'] == 'failed' and result['reason'] == 'remote_publication_failed'
    assert result['backup_can_continue'] and not result['publication_complete']
    assert 'secret-diagnostic' not in json.dumps(result)


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "note").write_text("published")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "published")
    baseline = _git(project, "rev-parse", "HEAD")
    _git(project, "remote", "add", "origin", "https://github.com/fixture/project.git")
    _git(project, "update-ref", "refs/remotes/origin/main", baseline)
    _git(project, "branch", "--set-upstream-to", "origin/main")
    (project / "note").write_text("committed unpublished")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "unpublished")
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda _repo, head: {"state": "reused", "acceptance_id": "fixture", "source_commit": head})
    monkeypatch.setattr(publish, "_codeql_after_publication", lambda *_: {"state": "unavailable", "reason": "fixture_only"})
    return {"id": "fixture", "path": str(project), "source_type": "project", "enabled": True, "project_id": "fixture"}


def delivery(state="success", *, pushed=True):
    return {"status": "SUCCESS" if state == "success" else "PENDING" if state == "pending" else "BLOCKED",
            "pushed": pushed, "publication_complete": state == "success", "ci": {"state": state, "checks": []},
            "security": {"state": "success"}, "reason": f"remote_ci_{state}"}




def test_publication_preserves_all_active_checkout_state(source, monkeypatch):
    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    _git(project, "branch", "private-work")
    (project / "note").write_text("staged")
    _git(project, "add", "note")
    (project / "note").write_text("unstaged")
    (project / "unfinished").write_text("untracked")
    index = (project / ".git/index").read_bytes()
    refs = _git(project, "show-ref")
    isolated = Mock(return_value=delivery())
    monkeypatch.setattr(publish, "_publish_isolated", isolated)
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result["status"] == "published" and result["publication_complete"]
    assert result["head"] == head and result["observed_at"]
    assert result["backup_can_continue"]
    assert isolated.call_args.args[1] == head
    assert (project / ".git/index").read_bytes() == index
    assert _git(project, "show-ref") == refs
    assert _git(project, "show", ":note") == "staged"
    assert (project / "note").read_text() == "unstaged"
    assert (project / "unfinished").read_text() == "untracked"


def test_completed_upload_without_ci_is_not_worded_as_verified(source, monkeypatch):
    head = _git(Path(source["path"]), "rev-parse", "HEAD")
    delivered = delivery("not_applicable")
    delivered.update(status="SUCCESS", publication_complete=True,
                     ci={"state": "not_applicable", "sha": head, "checks": []},
                     security={"state": "success", "sha": head})
    monkeypatch.setattr(publish, "_publish_isolated", Mock(return_value=delivered))
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result["publication_complete"] and result["backup_can_continue"]
    assert result["status"] == "published" and result["reason"] == "uploaded_without_ci"
    assert result["remote_status"] == "uploaded" and result["ci"]["state"] == "not_applicable"


@pytest.mark.parametrize("state", ["missing", "invalid", "unavailable"])
def test_unaccepted_source_never_publishes(source, monkeypatch, state):
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda *_: {"state": state})
    publisher = Mock(side_effect=AssertionError("Unreviewed source publication"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result["status"] == "pending" and result["reason"] == "source_acceptance_required"
    assert result["action"] and result["backup_can_continue"]
    publisher.assert_not_called()


def test_configured_empty_repository_bootstrap_retains_accepted_source_and_wip(source, monkeypatch):
    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    _git(project, "update-ref", "-d", "refs/remotes/origin/main")
    (project / "unfinished").write_text("private untracked work")
    index = (project / ".git/index").read_bytes()
    publisher = Mock(return_value=delivery("pending"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result["head"] == head and result["status"] == "pending"
    assert result["ahead"] is None and result["upstream_status"] == "unobserved_locally"
    assert publisher.call_args.args[1] == head
    assert (project / "unfinished").read_text() == "private untracked work"
    assert (project / ".git/index").read_bytes() == index
    assert _git(project, "rev-parse", "HEAD") == head


def test_empty_repository_without_acceptance_never_bootstraps(source, monkeypatch):
    project = Path(source["path"])
    _git(project, "update-ref", "-d", "refs/remotes/origin/main")
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda *_: {"state": "missing"})
    publisher = Mock(side_effect=AssertionError("No unaccepted initialization"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result["reason"] == "source_acceptance_required" and result["backup_can_continue"]
    publisher.assert_not_called()




def test_manual_daytime_publication_pins_source_and_preserves_later_checkout(source, monkeypatch):
    project = Path(source["path"])
    accepted = _git(project, "rev-parse", "HEAD")
    _git(project, "checkout", "-b", "later-work")
    (project / "later").write_text("later committed work")
    _git(project, "add", "later")
    _git(project, "commit", "-m", "later")
    later_head = _git(project, "rev-parse", "HEAD")
    (project / "note").write_text("staged")
    _git(project, "add", "note")
    (project / "note").write_text("unstaged")
    (project / "unfinished").write_text("untracked")
    index = (project / ".git/index").read_bytes()
    refs = _git(project, "show-ref")
    publisher = Mock(return_value=delivery())
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    acceptance = Mock(return_value={"state": "reused", "acceptance_id": "exact", "source_commit": accepted})
    monkeypatch.setattr(publish, "_acceptance_for_head", acceptance)

    result = publish.publish_source_before_backup(source, manual_source_commit=accepted)

    assert result["publication_mode"] == "manual" and result["status"] == "published"
    assert result["requested_source_commit"] == result["captured_source_commit"] == result["head"] == accepted
    acceptance.assert_called_once_with(project, accepted)
    assert publisher.call_args.args[1:3] == (accepted, "main")
    assert publisher.call_args.kwargs["activity_allowed"]() is True
    assert (project / ".git/index").read_bytes() == index
    assert _git(project, "show-ref") == refs and _git(project, "rev-parse", "HEAD") == later_head
    assert _git(project, "branch", "--show-current") == "later-work"
    assert _git(project, "show", ":note") == "staged"
    assert (project / "note").read_text() == "unstaged"
    assert (project / "unfinished").read_text() == "untracked"


@pytest.mark.parametrize("requested", ["", "HEAD", "a" * 12, "a" * 41, "A" * 40, "fixture-private-diagnostic"])
def test_invalid_manual_source_fails_before_inspection(source, monkeypatch, requested):
    inspector = Mock(side_effect=AssertionError("Invalid source must not inspect or publish"))
    monkeypatch.setattr(publish, "_git", inspector)
    policy = Mock(side_effect=AssertionError("Validate source before owner policy"))
    result = publish.publish_source_before_backup(source, manual_source_commit=requested, activity_allowed=policy)
    assert result["status"] == "failed" and result["reason"] == "invalid_manual_source"
    assert result["publication_mode"] == "manual" and result["requested_source_commit"] is None
    assert not result["attempted"] and result["backup_can_continue"]
    assert "fixture-private" not in json.dumps(result)
    inspector.assert_not_called()
    policy.assert_not_called()


@pytest.mark.parametrize("retained_head", ["b" * 40, "", "HEAD"])
def test_manual_source_rejects_conflicting_or_invalid_retained_head(source, monkeypatch, retained_head):
    accepted = _git(Path(source["path"]), "rev-parse", "HEAD")
    inspector = Mock(side_effect=AssertionError("Conflicting source must not inspect or publish"))
    monkeypatch.setattr(publish, "_git", inspector)
    result = publish.publish_source_before_backup(source, retained={"head": retained_head}, manual_source_commit=accepted)
    assert result["status"] == "failed"
    assert result["reason"] == ("manual_retained_source_conflict" if retained_head == "b" * 40 else "invalid_retained_source")
    assert not result["attempted"] and result["captured_source_commit"] is None
    inspector.assert_not_called()


@pytest.mark.parametrize("requested", ["a" * 40, "a" * 64])
def test_missing_manual_object_never_substitutes_head(source, monkeypatch, requested):
    publisher = Mock(side_effect=AssertionError("No fallback to current HEAD"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    policy = Mock(side_effect=AssertionError("Validate source before owner policy"))
    result = publish.publish_source_before_backup(source, manual_source_commit=requested, activity_allowed=policy)
    assert result["status"] == "failed" and result["reason"] == "manual_source_unavailable"
    assert result["requested_source_commit"] == requested and result["captured_source_commit"] is None
    publisher.assert_not_called()
    policy.assert_not_called()


@pytest.mark.parametrize("state", ["missing", "invalid", "unavailable"])
def test_manual_daytime_source_still_requires_full_acceptance(source, monkeypatch, state):
    accepted = _git(Path(source["path"]), "rev-parse", "HEAD")
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda *_: {"state": state})
    publisher = Mock(side_effect=AssertionError("No unaccepted manual publication"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, manual_source_commit=accepted)
    assert result["status"] == "pending" and result["reason"] == "source_acceptance_required"
    assert result["captured_source_commit"] == accepted and not result["attempted"]
    publisher.assert_not_called()


def test_manual_detached_source_never_uses_receipt_selected_or_mutable_head(source, monkeypatch):
    project = Path(source["path"])
    accepted = _git(project, "rev-parse", "main")
    _git(project, "checkout", "--detach", "HEAD~1")
    publisher = Mock(return_value=delivery("pending"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, manual_source_commit=accepted)
    assert result["head"] == accepted and result["vcs"] == "git"
    assert publisher.call_args.args[1] == accepted
    assert _git(project, "rev-parse", "HEAD") != accepted


def test_manual_matching_retained_source_preserves_resume_policy(source, monkeypatch):
    accepted = _git(Path(source["path"]), "rev-parse", "HEAD")
    publisher = Mock(return_value=delivery("pending", pushed=False))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(
        source, retained={"head": accepted, "branch": "main", "pushed": True}, manual_source_commit=accepted)
    assert result["head"] == accepted and result["pushed"] is True
    assert publisher.call_args.kwargs["resume"] is True
    assert publisher.call_args.kwargs["activity_allowed"]() is True


def test_deployment_workflow_requires_separate_explicit_authority(source, monkeypatch):
    project = Path(source["path"])
    workflow = project / ".github/workflows/deploy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("on: push\njobs:\n  deploy:\n    environment: production\n    steps:\n      - run: scripts/deploy.sh\n")
    _git(project, "add", ".github")
    _git(project, "commit", "-m", "Declare deployment effects")
    sha = _git(project, "rev-parse", "HEAD")
    publisher = Mock(return_value=delivery("pending"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    # Later WIP cannot erase effects in the selected immutable source.
    workflow.write_text("on: workflow_dispatch\njobs: {}\n")
    pending = publish.publish_source_before_backup(source, manual_source_commit=sha)
    assert pending["reason"] == "workflow_effects_authorization_required"
    assert pending["unauthorized_workflows"] == [".github/workflows/deploy.yml"]
    publisher.assert_not_called()
    authorized = publish.publish_source_before_backup(source, manual_source_commit=sha,
        authorized_workflows=(".github/workflows/deploy.yml",))
    assert authorized["attempted"] is True
    assert publisher.call_args.args[1] == sha


@pytest.mark.parametrize("failure", ["rejected", "exception"])
def test_manual_owner_policy_failure_is_sanitized_pending(source, monkeypatch, failure):
    accepted = _git(Path(source["path"]), "rev-parse", "HEAD")
    policy = Mock(return_value=False) if failure == "rejected" else Mock(side_effect=RuntimeError("fixture-private-policy-diagnostic"))
    publisher = Mock(side_effect=AssertionError("No publication without owner activity permission"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, manual_source_commit=accepted, activity_allowed=policy)
    assert result["status"] == "pending" and result["reason"] == "publication_busy"
    assert result["captured_source_commit"] == accepted and result["source_status"] == "accepted"
    assert not result["attempted"] and not result["publication_complete"]
    assert "fixture-private" not in json.dumps(result)
    policy.assert_called_once_with()
    publisher.assert_not_called()


@pytest.mark.parametrize("phase", ["initial_scan", "push_scan"])
def test_manual_owner_loss_stops_nested_publication_and_latches_closed(source, monkeypatch, phase):
    from app.services.git import outgoing
    from cli.lib import publish_workflow

    accepted = _git(Path(source["path"]), "rev-parse", "HEAD")
    ownership = {"allowed": True}
    policy = Mock(side_effect=lambda: ownership["allowed"])
    original = publish._git
    pushes = []

    def local_git(repo, *args):
        if args[0] == "ls-remote":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "push":
            pushes.append(args)
            raise AssertionError("No transport after owner lease loss")
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", local_git)
    scans = []

    def verify(*args, **kwargs):
        scans.append(args)
        if len(scans) == (1 if phase == "initial_scan" else 2):
            ownership["allowed"] = False
        return Mock(commits_scanned=2, refs_checked=1)

    monkeypatch.setattr(outgoing, "verify_outgoing", verify)
    captured_policy = []

    def canonical(repo, **kwargs):
        captured_policy.append(kwargs["activity_allowed"])
        if not kwargs["activity_allowed"]():
            raise publish_workflow.PublishError("Scheduled publication window is closed", unavailable=True,
                                                reason="outside_publication_window")
        kwargs["run_git"](repo, ["push", "origin", f"{accepted}:refs/heads/st/manual"])
        raise AssertionError("No completed publication after owner loss")

    monkeypatch.setattr(publish_workflow, "publish_git", canonical)
    result = publish.publish_source_before_backup(source, manual_source_commit=accepted, activity_allowed=policy)
    assert result["status"] == "pending" and result["reason"] == "publication_busy"
    assert not result["publication_complete"] and not pushes
    assert len(scans) == (1 if phase == "initial_scan" else 2)
    calls = policy.call_count
    ownership["allowed"] = True
    assert captured_policy[0]() is False and policy.call_count == calls


def test_manual_resolved_source_mismatch_never_reaches_acceptance(source, monkeypatch):
    project = Path(source["path"])
    accepted = _git(project, "rev-parse", "HEAD")
    original = publish._git

    def local_git(repo, *args):
        if args == ("rev-parse", "--verify", f"{accepted}^{{commit}}"):
            return subprocess.CompletedProcess(args, 0, "b" * 40, "")
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", local_git)
    acceptance = Mock(side_effect=AssertionError("No substituted source acceptance"))
    monkeypatch.setattr(publish, "_acceptance_for_head", acceptance)
    result = publish.publish_source_before_backup(source, manual_source_commit=accepted)
    assert result["reason"] == "manual_source_unavailable" and not result["attempted"]
    acceptance.assert_not_called()


@pytest.mark.parametrize("case", ["disabled", "unregistered", "wrong_push_route", "mirror", "ambiguous_default"])
def test_manual_daytime_still_rejects_uncertain_project_routes(source, monkeypatch, case):
    project = Path(source["path"])
    accepted = _git(project, "rev-parse", "HEAD")
    publisher = Mock(side_effect=AssertionError("No unsafe manual route"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    if case == "disabled":
        source["enabled"] = False
    elif case == "unregistered":
        source["id"] = None
    elif case == "wrong_push_route":
        _git(project, "remote", "set-url", "--push", "origin", "https://github.com/wrong/private.git")
    elif case == "mirror":
        _git(project, "config", "remote.origin.mirror", "true")
    else:
        _git(project, "branch", "master")
    result = publish.publish_source_before_backup(source, manual_source_commit=accepted)
    assert not result["attempted"] and not result["publication_complete"]
    assert result["backup_can_continue"]
    publisher.assert_not_called()


@pytest.mark.parametrize("case", ["disabled", "non_project", "unregistered",                                  "no_upstream", "local", "loopback", "wrong_push_route", "multiple_routes",
                                 "wrong_upstream", "mirror"])
def test_uncertain_sources_never_reach_publisher(source, monkeypatch, case):
    project = Path(source["path"])
    publisher = Mock(side_effect=AssertionError("Unsafe publication route"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    if case == "disabled":
        source["enabled"] = False
    elif case == "non_project":
        source["source_type"] = "infrastructure"
    elif case == "unregistered":
        source["id"] = None
    elif case == "detached":
        _git(project, "checkout", "--detach")
    elif case == "feature":
        _git(project, "checkout", "-b", "private-feature")
    elif case == "no_upstream":
        _git(project, "branch", "--unset-upstream")
    elif case == "local":
        _git(project, "remote", "set-url", "origin", "/tmp/private-repository.git")
    elif case == "loopback":
        _git(project, "remote", "set-url", "origin", "ssh://git@localhost/project.git")
    elif case == "wrong_push_route":
        _git(project, "remote", "set-url", "--push", "origin", "https://github.com/wrong/private.git")
    elif case == "multiple_routes":
        _git(project, "remote", "set-url", "--add", "--push", "origin", "https://github.com/fixture/project.git")
        _git(project, "remote", "set-url", "--add", "--push", "origin", "https://github.com/second/project.git")
    elif case == "wrong_upstream":
        _git(project, "config", "branch.main.merge", "refs/heads/private")
    else:
        _git(project, "config", "remote.origin.mirror", "true")
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result["status"] == "skipped" and result["backup_can_continue"]
    publisher.assert_not_called()


@pytest.mark.parametrize("ci", ["pending", "failed", "success"])
def test_remote_presence_still_observes_ci(source, monkeypatch, ci):
    project = Path(source["path"])
    _git(project, "update-ref", "refs/remotes/origin/main", "HEAD")
    publisher = Mock(return_value=delivery(ci, pushed=False))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, manual_source_commit=_git(Path(source["path"]), "rev-parse", "HEAD"))
    assert result["ci"]["state"] == ci
    assert result["publication_complete"] is (ci == "success")
    publisher.assert_called_once()












@pytest.mark.parametrize("manual", [True])
def test_canonical_publisher_runs_in_disposable_checkout_with_explicit_verifier(source, monkeypatch, manual):
    from app.services.git import outgoing
    from cli.lib import publish_workflow

    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    index = (project / ".git/index").read_bytes()
    original_git = publish._git
    verifier = Mock(return_value=Mock(commits_scanned=2, refs_checked=1))
    monkeypatch.setattr(outgoing, "verify_outgoing", verifier)

    def safe_git(repo, *args):
        if args[0] in {"ls-remote", "push"}:
            return subprocess.CompletedProcess(args, 0, "", "")
        return original_git(repo, *args)

    monkeypatch.setattr(publish, "_git", safe_git)
    codeql = Mock(return_value={"state": "unavailable", "reason": "fixture_only"})
    monkeypatch.setattr(publish, "_codeql_after_publication", codeql)
    seen = []

    def canonical(repo, **kwargs):
        seen.append(repo)
        assert repo != project
        assert _git(repo, "rev-parse", "HEAD") == kwargs["sha"]
        assert kwargs["reconcile_checkout"] is False and kwargs["destination"] == "main"
        assert kwargs["activity_allowed"]() is True
        kwargs["run_git"](repo, ["push", "origin", f"{kwargs['sha']}:refs/heads/st/nightly"])
        return {**delivery(), "ci": {"state": "success", "detail": "token must never persist"}}

    monkeypatch.setattr(publish_workflow, "publish_git", canonical)
    result = publish.publish_source_before_backup(source, manual_source_commit=head if manual else None)
    assert result["publication_complete"] and result["security"]["commits_scanned"] == 2
    assert "token" not in json.dumps(result) and not seen[0].exists()
    assert (project / ".git/index").read_bytes() == index
    assert verifier.call_args.args[2][0].remote_ref == "refs/heads/st/nightly"
    assert verifier.call_count == 2 and all(call.args[2][0].local_oid == head for call in verifier.call_args_list)
    codeql.assert_called_once()
    assert codeql.call_args.args[-1] == head


@pytest.mark.parametrize("manual", [True])
def test_security_failure_never_pushes_or_discloses_diagnostics(source, monkeypatch, manual):
    monkeypatch.setattr(publish, "_publish_isolated", Mock(side_effect=publish._OutgoingFailed("private token")))
    head = _git(Path(source["path"]), "rev-parse", "HEAD")
    result = publish.publish_source_before_backup(source, manual_source_commit=head if manual else None)
    assert result["security"]["state"] == "blocked" and result["backup_can_continue"]
    assert result["reason"] == "outgoing_verification_failed"
    assert "private token" not in json.dumps(result)


@pytest.mark.parametrize("manual", [True])
@pytest.mark.parametrize("phase", ["initial", "push"])
def test_shared_admission_outage_defers_publication_without_push_or_repair(source, monkeypatch, phase, manual):
    from app.services import publication_health
    from app.services.git import outgoing
    from cli.lib import publish_workflow

    original = publish._git

    def local_git(repo, *args):
        if args[0] == "ls-remote":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "push":
            raise AssertionError("No push when required admission is unavailable")
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", local_git)
    unavailable = outgoing.OutgoingAdmissionUnavailable("fixture-private-storage-diagnostic")
    evidence = Mock(commits_scanned=2, refs_checked=1)
    verifier = Mock(side_effect=unavailable if phase == "initial" else [evidence, unavailable])
    monkeypatch.setattr(outgoing, "verify_outgoing", verifier)

    def canonical(repo, **kwargs):
        kwargs["run_git"](repo, ["push", "origin", f"{kwargs['sha']}:refs/heads/st/nightly"])
        raise AssertionError("No delivery after required admission is unavailable")

    publisher = Mock(side_effect=canonical)
    monkeypatch.setattr(publish_workflow, "publish_git", publisher)
    head = _git(Path(source["path"]), "rev-parse", "HEAD")
    result = publish.publish_source_before_backup(source, manual_source_commit=head if manual else None)
    assert result["status"] == "pending" and result["reason"] == "heavy_work_admission_unavailable"
    assert result["backup_can_continue"] and not result["publication_complete"]
    assert result["security"]["state"] == "unavailable" and result["remote_status"] == "unknown"
    assert verifier.call_count == (1 if phase == "initial" else 2)
    assert publisher.call_count == (0 if phase == "initial" else 1)
    assert "fixture-private-storage-diagnostic" not in json.dumps(result)
    recorder = Mock()
    monkeypatch.setattr(publication_health, "record_finding", recorder)
    assert publication_health.record_publication_observation("fixture", result) is None
    recorder.assert_not_called()


@pytest.mark.parametrize("valid", [False, True])
def test_exact_source_receipt_requires_canonical_validation(source, monkeypatch, valid):
    from cli.lib import acceptance

    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    receipt = project / ".git/st/acceptance/existing.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"source": {"commit": head}}))
    validator = Mock(return_value={"acceptance_id": "validated", "coverage": "full"}) if valid else Mock(side_effect=acceptance.AcceptanceError("private diagnostic"))
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", validator)
    monkeypatch.setattr(acceptance, "accept_revision", Mock(side_effect=AssertionError("No nightly full gate")))
    result = _acceptance_lookup(project, head)
    assert result["state"] == ("reused" if valid else "invalid")
    validator.assert_called_once_with(project, receipt, sha=head)
    assert "private diagnostic" not in json.dumps(result)


@pytest.mark.parametrize("coverage", [None, "unknown", "focused", "task", "FULL"])
def test_manual_publication_requires_canonical_full_coverage(source, monkeypatch, coverage):
    from cli.lib import acceptance

    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    receipt = project / ".git/st/acceptance/existing.json"
    receipt.parent.mkdir(parents=True)
    # Raw coverage alone cannot authorize publication; use the validated result.
    receipt.write_text(json.dumps({"source": {"commit": head}, "coverage": "full"}))
    validated = {"acceptance_id": "validated"}
    if coverage is not None:
        validated["coverage"] = coverage
    validator = Mock(return_value=validated)
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", validator)
    monkeypatch.setattr(publish, "_acceptance_for_head", _acceptance_lookup)
    publisher = Mock(side_effect=AssertionError("No non-full manual publication"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)

    result = publish.publish_source_before_backup(source, manual_source_commit=head)

    assert result["acceptance"] == {"state": "invalid"}
    assert result["status"] == "pending" and result["reason"] == "source_acceptance_required"
    assert not result["attempted"] and result["backup_can_continue"]
    validator.assert_called_once_with(project, receipt, sha=head)
    publisher.assert_not_called()


@pytest.mark.parametrize("with_full", [False, True])
def test_valid_task_receipt_does_not_hide_older_exact_full_receipt(source, monkeypatch, local_gate_tools, with_full):
    from cli.lib import acceptance

    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    runner = Mock(side_effect=lambda command, cwd: subprocess.CompletedProcess(command, 0, "RUFF:OK:0", ""))
    if with_full:
        full = acceptance.accept_revision(project, sha=head, runner=runner)
        os.utime(full["acceptance_artifact"], ns=(1_000_000_000, 1_000_000_000))
    task = acceptance.accept_revision(project, sha=head, coverage="task", scope=("note",), runner=runner)
    os.utime(task["acceptance_artifact"], ns=(2_000_000_000, 2_000_000_000))
    assert acceptance.validate_acceptance_receipt(project, Path(task["acceptance_artifact"]), sha=head)["coverage"] == "task"
    monkeypatch.setattr(acceptance, "accept_revision", Mock(side_effect=AssertionError("Reuse only; no acceptance gate")))
    monkeypatch.setattr(publish, "_acceptance_for_head", _acceptance_lookup)
    publisher = Mock(return_value=delivery())
    monkeypatch.setattr(publish, "_publish_isolated", publisher)

    result = publish.publish_source_before_backup(source, manual_source_commit=head)

    if with_full:
        assert result["acceptance"] == {"state": "reused", "acceptance_id": full["acceptance_id"], "source_commit": head}
        assert result["status"] == "published" and result["attempted"]
        publisher.assert_called_once()
    else:
        assert result["acceptance"] == {"state": "invalid"}
        assert result["status"] == "pending" and result["reason"] == "source_acceptance_required"
        assert not result["attempted"]
        publisher.assert_not_called()


def test_partial_clone_receipts_do_not_lazily_fetch(source, monkeypatch):
    from cli.lib import acceptance

    project = Path(source["path"])
    _git(project, "config", "remote.origin.promisor", "true")
    validator = Mock(side_effect=AssertionError("No lazy fetch"))
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", validator)
    assert _acceptance_lookup(project, _git(project, "rev-parse", "HEAD")) == {"state": "unavailable", "reason": "partial_clone"}
    validator.assert_not_called()
@pytest.mark.parametrize("failure", ["nonzero", "timeout", "exception", "missing_watchdog"])
def test_network_worker_is_bounded_noninteractive_and_never_exposes_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    monkeypatch.setattr(git_utils.shutil, "which", lambda _: None if failure == "missing_watchdog" else "/usr/bin/timeout")
    captured = []

    def run(command, **kwargs):
        captured.append((command, kwargs))
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 300, output="secret", stderr="token")
        if failure == "exception":
            raise OSError("secret credentials")
        return subprocess.CompletedProcess(command, 128, "secret", "token")

    monkeypatch.setattr(git_utils.safe_subprocess, "run", run)
    head = "a" * 40
    result = git_utils.push_captured_head_to_upstream(tmp_path, head, "refs/heads/main", "https://username:token@example.invalid/project.git")
    assert result["status"] == "failed"
    assert "token" not in json.dumps(result) and "secret" not in json.dumps(result)
    if failure == "missing_watchdog":
        assert not captured
        return
    command, kwargs = captured[0]
    assert command[:4] == ["/usr/bin/timeout", "--signal=TERM", "--kill-after=5s", "300s"]
    assert command[-1] == f"{head}:refs/heads/main"
    assert "--no-follow-tags" in command and "--recurse-submodules=no" in command
    assert not {"--all", "--mirror", "--force", "--force-with-lease", "-u"} & set(command)
    assert kwargs["timeout"] == 310
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kwargs["env"]["GCM_INTERACTIVE"] == "Never"
    assert "BatchMode=yes" in kwargs["env"]["GIT_SSH_COMMAND"]
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL


def test_successful_network_worker_sends_only_captured_oid_and_configured_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_utils.shutil, "which", lambda _: "/usr/bin/timeout")
    mocked = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(git_utils.safe_subprocess, "run", mocked)
    head = "b" * 64
    result = git_utils.push_captured_head_to_upstream(tmp_path, head, "refs/heads/master", "git@example.invalid:project.git", ssh_command="ssh -i /keys/existing")
    assert result["status"] == "published"
    assert mocked.call_args.args[0][-1] == f"{head}:refs/heads/master"
    assert mocked.call_args.kwargs["env"]["GIT_SSH_COMMAND"].startswith("ssh -i /keys/existing ")


@pytest.mark.parametrize("url", ["file:///tmp/project.git", "/tmp/project.git", "https://localhost/project.git", "ssh://git@127.0.0.1/project.git", "ext::private-helper", "git://example.invalid/project.git", "custom::private-helper", "https://example.invalid/project.git?repository=private"])
def test_transport_helper_refuses_local_or_external_command_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    mocked = Mock(side_effect=AssertionError("unsafe route invoked"))
    monkeypatch.setattr(git_utils.safe_subprocess, "run", mocked)
    assert git_utils.push_captured_head_to_upstream(tmp_path, "a" * 40, "refs/heads/main", url)["status"] == "failed"
    mocked.assert_not_called()



def test_timeout_watchdog_terminates_fixture_git_and_its_transport_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if git_utils.shutil.which("timeout") is None:
        pytest.skip("GNU timeout unavailable")
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    child_marker = tmp_path / "transport-pid"
    fake_git = binary_directory / "git"
    fake_git.write_text(
        "#!/usr/bin/env python3\n"
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"Path({str(child_marker)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    fake_git.chmod(0o700)
    monkeypatch.setenv("PATH", f"{binary_directory}:{os.environ.get('PATH', '')}")
    started = time.monotonic()
    result = git_utils.push_captured_head_to_upstream(tmp_path, "a" * 40, "refs/heads/main", "https://example.invalid/project.git", timeout_seconds=1)
    assert result == {"status": "failed", "reason": "push_timeout", "attempted": True}
    assert time.monotonic() - started < 8
    child_pid = int(child_marker.read_text())
    child_status = Path(f"/proc/{child_pid}/stat")
    assert not child_status.exists() or child_status.read_text().split(") ", 1)[1].startswith("Z")


def test_legacy_publication_call_is_retired_before_any_inspection(source, monkeypatch):
    inspect = Mock(side_effect=AssertionError("No implicit publication"))
    monkeypatch.setattr(publish, "_git", inspect)
    result = publish.publish_source_before_backup(source)
    assert result["status"] == "retired" and not result["publication_complete"]
    inspect.assert_not_called()
