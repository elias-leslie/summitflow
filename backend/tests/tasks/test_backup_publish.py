"""Nightly publication uses accepted immutable source and independent backups."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services.git import utils as git_utils
from app.tasks import backup_publish as publish
from tests.tasks.test_backup_native_recovery import _git

_acceptance_lookup = publish._acceptance_for_head


@pytest.mark.parametrize('unavailable,expected', [(True, 'pending'), (False, 'failed')])
def test_typed_publication_error_is_pending_only_for_outages(source, monkeypatch, unavailable, expected):
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
    result = publish.publish_source_before_backup(source)
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
    result = publish.publish_source_before_backup(source)
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
    result = publish.publish_source_before_backup(source)
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
    monkeypatch.setattr(publish, "publication_window_open", lambda: True)
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda _repo, head: {"state": "reused", "acceptance_id": "fixture", "source_commit": head})
    monkeypatch.setattr(publish, "_codeql_after_publication", lambda *_: {"state": "unavailable", "reason": "fixture_only"})
    return {"id": "fixture", "path": str(project), "source_type": "project", "enabled": True, "project_id": "fixture"}


def delivery(state="success", *, pushed=True):
    return {"status": "SUCCESS" if state == "success" else "PENDING" if state == "pending" else "BLOCKED",
            "pushed": pushed, "publication_complete": state == "success", "ci": {"state": state, "checks": []},
            "security": {"state": "success"}, "reason": f"remote_ci_{state}"}


@pytest.mark.parametrize("instant,expected", [
    ("2026-01-10T06:59:00+00:00", False), ("2026-01-10T07:00:00+00:00", True),
    ("2026-01-10T11:00:00+00:00", False), ("2026-07-10T06:00:00+00:00", True),
    ("2026-07-10T10:00:00+00:00", False), ("2026-03-08T07:00:00+00:00", True),
    ("2026-11-01T06:30:00+00:00", False), ("2026-11-01T07:00:00+00:00", True),
])
def test_night_window_tracks_dst(instant, expected):
    assert publish.publication_window_open(datetime.fromisoformat(instant)) is expected


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
    result = publish.publish_source_before_backup(source)
    assert result["status"] == "published" and result["publication_complete"]
    assert result["head"] == head and result["observed_at"]
    assert result["backup_can_continue"]
    assert isolated.call_args.args[1] == head
    assert (project / ".git/index").read_bytes() == index
    assert _git(project, "show-ref") == refs
    assert _git(project, "show", ":note") == "staged"
    assert (project / "note").read_text() == "unstaged"
    assert (project / "unfinished").read_text() == "untracked"


@pytest.mark.parametrize("state", ["missing", "invalid", "unavailable"])
def test_unaccepted_source_never_publishes(source, monkeypatch, state):
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda *_: {"state": state})
    publisher = Mock(side_effect=AssertionError("Unreviewed source publication"))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source)
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
    result = publish.publish_source_before_backup(source)
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
    result = publish.publish_source_before_backup(source)
    assert result["reason"] == "source_acceptance_required" and result["backup_can_continue"]
    publisher.assert_not_called()


def test_window_closure_never_attempts_publication(source, monkeypatch):
    monkeypatch.setattr(publish, "publication_window_open", lambda: False)
    publisher = Mock()
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source)
    assert result["status"] == "pending" and not result["attempted"]
    assert result["reason"] == "outside_publication_window"
    publisher.assert_not_called()


@pytest.mark.parametrize("case", ["disabled", "non_project", "unregistered", "detached", "feature",
                                 "no_upstream", "local", "loopback", "wrong_push_route", "multiple_routes",
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
    result = publish.publish_source_before_backup(source)
    assert result["status"] == "skipped" and result["backup_can_continue"]
    publisher.assert_not_called()


@pytest.mark.parametrize("ci", ["pending", "failed", "success"])
def test_remote_presence_still_observes_ci(source, monkeypatch, ci):
    project = Path(source["path"])
    _git(project, "update-ref", "refs/remotes/origin/main", "HEAD")
    publisher = Mock(return_value=delivery(ci, pushed=False))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source)
    assert result["ci"]["state"] == ci
    assert result["publication_complete"] is (ci == "success")
    publisher.assert_called_once()


def test_retry_retains_source_after_new_commits(source, monkeypatch):
    project = Path(source["path"])
    accepted = _git(project, "rev-parse", "HEAD")
    (project / "later").write_text("new work")
    _git(project, "add", "later")
    _git(project, "commit", "-m", "later")
    publisher = Mock(return_value=delivery("pending", pushed=False))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, retained={"head": accepted, "pushed": True})
    assert result["head"] == accepted
    assert publisher.call_args.kwargs == {"resume": True}
    assert _git(project, "rev-parse", "HEAD") != accepted


def test_retained_source_retries_without_switching_later_active_branch(source, monkeypatch):
    project = Path(source["path"])
    accepted = _git(project, "rev-parse", "main")
    _git(project, "checkout", "-b", "later-work")
    publisher = Mock(return_value=delivery("pending", pushed=False))
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source, retained={"head": accepted, "branch": "main", "pushed": True})
    assert result["head"] == accepted and result["pushed"] is True
    assert _git(project, "branch", "--show-current") == "later-work"


def test_jj_uses_accepted_default_bookmark_not_mutable_git_head(source, monkeypatch):
    project = Path(source["path"])
    accepted = _git(project, "rev-parse", "main")
    (project / ".jj").mkdir()
    _git(project, "checkout", "--detach", "HEAD~1")
    _git(project, "config", "--unset-all", "branch.main.remote")
    _git(project, "config", "--unset-all", "branch.main.merge")
    publisher = Mock(return_value=delivery())
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    result = publish.publish_source_before_backup(source)
    assert result["vcs"] == "jj" and result["head"] == accepted
    assert _git(project, "rev-parse", "HEAD") != accepted


def test_jj_publishes_reviewed_revision_descending_from_stale_default_bookmark(source, monkeypatch):
    from cli.lib import acceptance

    project = Path(source["path"])
    default_head = _git(project, "rev-parse", "main")
    (project / ".jj").mkdir()
    _git(project, "checkout", "--detach")
    (project / "reviewed").write_text("accepted JJ work")
    _git(project, "add", "reviewed")
    _git(project, "commit", "-m", "reviewed JJ revision")
    accepted = _git(project, "rev-parse", "HEAD")
    receipt = project / ".git/st/acceptance/reviewed.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"source": {"commit": accepted}}))
    # Later @ work is unrelated to the accepted immutable source.
    (project / "unfinished").write_text("new JJ work")
    publisher = Mock(return_value=delivery())
    monkeypatch.setattr(publish, "_publish_isolated", publisher)
    monkeypatch.setattr(publish, "_acceptance_for_head", _acceptance_lookup)
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", Mock(return_value={"acceptance_id": "reviewed", "source_commit": accepted}))
    result = publish.publish_source_before_backup(source)
    assert result["head"] == accepted
    assert publisher.call_args.args[1:3] == (accepted, "main")
    assert _git(project, "rev-parse", "main") == default_head
    assert (project / "unfinished").read_text() == "new JJ work"


def test_jj_malformed_receipt_does_not_select_mutable_head(source):
    project = Path(source["path"])
    default_head = _git(project, "rev-parse", "main")
    receipt = project / ".git/st/acceptance/malformed.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"source": "untrusted shape"}))
    assert publish._reviewed_jj_source(project, default_head) == default_head


def test_canonical_publisher_runs_in_disposable_checkout_with_explicit_verifier(source, monkeypatch):
    from app.services.git import outgoing
    from cli.lib import publish_workflow

    project = Path(source["path"])
    index = (project / ".git/index").read_bytes()
    original_git = publish._git
    verifier = Mock(return_value=Mock(commits_scanned=2, refs_checked=1))
    monkeypatch.setattr(outgoing, "verify_outgoing", verifier)

    def safe_git(repo, *args):
        if args[0] in {"ls-remote", "push"}:
            return subprocess.CompletedProcess(args, 0, "", "")
        return original_git(repo, *args)

    monkeypatch.setattr(publish, "_git", safe_git)
    seen = []

    def canonical(repo, **kwargs):
        seen.append(repo)
        assert repo != project
        assert _git(repo, "rev-parse", "HEAD") == kwargs["sha"]
        assert kwargs["reconcile_checkout"] is False and kwargs["destination"] == "main"
        kwargs["run_git"](repo, ["push", "origin", f"{kwargs['sha']}:refs/heads/st/nightly"])
        return {**delivery(), "ci": {"state": "success", "detail": "token must never persist"}}

    monkeypatch.setattr(publish_workflow, "publish_git", canonical)
    result = publish.publish_source_before_backup(source)
    assert result["publication_complete"] and result["security"]["commits_scanned"] == 2
    assert "token" not in json.dumps(result) and not seen[0].exists()
    assert (project / ".git/index").read_bytes() == index
    assert verifier.call_args.args[2][0].remote_ref == "refs/heads/st/nightly"


def test_security_failure_never_pushes_or_discloses_diagnostics(source, monkeypatch):
    monkeypatch.setattr(publish, "_publish_isolated", Mock(side_effect=publish._OutgoingFailed("private token")))
    result = publish.publish_source_before_backup(source)
    assert result["security"]["state"] == "blocked" and result["backup_can_continue"]
    assert result["reason"] == "outgoing_verification_failed"
    assert "private token" not in json.dumps(result)


@pytest.mark.parametrize("valid", [False, True])
def test_exact_source_receipt_requires_canonical_validation(source, monkeypatch, valid):
    from cli.lib import acceptance

    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    receipt = project / ".git/st/acceptance/existing.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"source": {"commit": head}}))
    validator = Mock(return_value={"acceptance_id": "validated"}) if valid else Mock(side_effect=acceptance.AcceptanceError("private diagnostic"))
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", validator)
    monkeypatch.setattr(acceptance, "accept_revision", Mock(side_effect=AssertionError("No nightly full gate")))
    result = _acceptance_lookup(project, head)
    assert result["state"] == ("reused" if valid else "invalid")
    validator.assert_called_once_with(project, receipt, sha=head)
    assert "private diagnostic" not in json.dumps(result)


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
