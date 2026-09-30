"""Daily publication sends only existing committed work and never gates backup."""

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


@pytest.fixture
def source(tmp_path: Path) -> dict:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "note").write_text("published")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "published")
    baseline = _git(project, "rev-parse", "HEAD")
    _git(project, "remote", "add", "origin", "https://example.invalid/project.git")
    _git(project, "update-ref", "refs/remotes/origin/main", baseline)
    _git(project, "branch", "--set-upstream-to", "origin/main")
    (project / "note").write_text("committed unpublished")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "unpublished")
    return {"id": "fixture", "path": str(project), "source_type": "project", "enabled": True, "project_id": "fixture"}


def test_publication_preserves_staged_unstaged_untracked_work_and_private_branches(source: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    _git(project, "branch", "private-work")
    _git(project, "tag", "unpublished-tag")
    (project / "note").write_text("staged original")
    _git(project, "add", "note")
    (project / "note").write_text("unstaged original")
    (project / "unique-work").write_text("untracked original")
    before = (project / ".git/index").read_bytes()
    mocked = Mock(return_value={"status": "published", "reason": "captured_head_published", "attempted": True})
    monkeypatch.setattr(publish, "push_captured_head_to_upstream", mocked)

    result = publish.publish_source_before_backup(source)

    assert result["status"] == "published"
    assert result["backup_can_continue"] is True
    assert result["acceptance"] == {"state": "missing"}
    assert result["head"] == head
    mocked.assert_called_once_with(project, head, "refs/heads/main", "https://example.invalid/project.git", ssh_command="ssh")
    assert (project / ".git/index").read_bytes() == before
    assert (project / "note").read_text() == "unstaged original"
    assert (project / "unique-work").read_text() == "untracked original"
    assert _git(project, "show", ":note") == "staged original"
    assert _git(project, "rev-parse", "HEAD") == head
    assert _git(project, "rev-parse", "private-work") == head
    assert _git(project, "rev-parse", "refs/remotes/origin/main") == head


def test_offline_failure_remains_retryable_then_catches_up_without_new_commit(source: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    upstream = _git(project, "rev-parse", "@{upstream}")
    mocked = Mock(side_effect=[{"status": "failed", "reason": "push_timeout", "attempted": True}, {"status": "published", "reason": "captured_head_published", "attempted": True}])
    monkeypatch.setattr(publish, "push_captured_head_to_upstream", mocked)
    failed = publish.publish_source_before_backup(source)
    assert failed["status"] == "failed" and failed["backup_can_continue"]
    assert _git(project, "rev-parse", "@{upstream}") == upstream
    successful = publish.publish_source_before_backup(source)
    assert successful["status"] == "published"
    assert _git(project, "rev-parse", "HEAD") == head
    assert publish.publish_source_before_backup(source)["status"] == "up_to_date"
    assert mocked.call_count == 2


@pytest.mark.parametrize("case", ["disabled", "non_project", "unregistered", "jj", "detached", "feature", "no_upstream", "local", "loopback", "wrong_push_route", "multiple_routes", "wrong_upstream", "mirror", "up_to_date", "diverged"])
def test_ineligible_or_uncertain_sources_never_push(source: dict, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    project = Path(source["path"])
    mocked = Mock(side_effect=AssertionError("unexpected network publication"))
    monkeypatch.setattr(publish, "push_captured_head_to_upstream", mocked)
    if case == "disabled":
        source["enabled"] = False
    elif case == "non_project":
        source["source_type"] = "infrastructure"
    elif case == "unregistered":
        source["id"] = None
    elif case == "jj":
        (project / ".jj").mkdir()
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
        _git(project, "remote", "set-url", "--push", "origin", "https://wrong.invalid/private.git")
    elif case == "multiple_routes":
        _git(project, "remote", "set-url", "--add", "--push", "origin", "https://example.invalid/project.git")
        _git(project, "remote", "set-url", "--add", "--push", "origin", "https://second.invalid/project.git")
    elif case == "wrong_upstream":
        _git(project, "config", "branch.main.merge", "refs/heads/private")
    elif case == "mirror":
        _git(project, "config", "remote.origin.mirror", "true")
    elif case == "up_to_date":
        _git(project, "update-ref", "refs/remotes/origin/main", "HEAD")
    else:
        _git(project, "checkout", "-b", "remote-side", "HEAD~1")
        (project / "remote-only").write_text("remote commit")
        _git(project, "add", ".")
        _git(project, "commit", "-m", "remote diverged")
        _git(project, "update-ref", "refs/remotes/origin/main", "HEAD")
        _git(project, "checkout", "main")
    result = publish.publish_source_before_backup(source)
    assert result["status"] == ("up_to_date" if case == "up_to_date" else "failed" if case == "diverged" else "skipped")
    assert result["backup_can_continue"] is True
    assert result["attempted"] is False
    mocked.assert_not_called()


def test_head_change_during_receipt_lookup_defers_without_pushing(source: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    project = Path(source["path"])

    def advance(*_args):
        _git(project, "update-ref", "refs/heads/main", "HEAD~1")
        return {"state": "missing"}

    mocked = Mock(side_effect=AssertionError("changed HEAD must not be published"))
    monkeypatch.setattr(publish, "_acceptance_for_head", advance)
    monkeypatch.setattr(publish, "push_captured_head_to_upstream", mocked)
    result = publish.publish_source_before_backup(source)
    assert result["status"] == "pending"
    assert result["reason"] == "repository_changed"
    assert result["backup_can_continue"]
    mocked.assert_not_called()


@pytest.mark.parametrize("valid", [False, True])
def test_exact_head_receipt_uses_canonical_validator_without_running_gate(source: dict, monkeypatch: pytest.MonkeyPatch, valid: bool) -> None:
    from cli.lib import acceptance

    project = Path(source["path"])
    head = _git(project, "rev-parse", "HEAD")
    receipt = project / ".git/st/acceptance/existing.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"source": {"commit": head}}))
    validator = Mock(return_value={"acceptance_id": "validated-id"}) if valid else Mock(side_effect=acceptance.AcceptanceError("secret diagnostic"))
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", validator)
    monkeypatch.setattr(acceptance, "accept_revision", Mock(side_effect=AssertionError("daily gate forbidden")))
    monkeypatch.setattr(publish, "push_captured_head_to_upstream", Mock(return_value={"status": "published", "reason": "captured_head_published", "attempted": True}))
    result = publish.publish_source_before_backup(source)
    validator.assert_called_once_with(project, receipt, sha=head)
    assert result["acceptance"]["state"] == ("reused" if valid else "invalid")
    assert "secret diagnostic" not in json.dumps(result)
    assert result["status"] == "published"


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


def test_partial_clone_does_not_lazily_fetch_for_optional_receipt_reuse(source: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.lib import acceptance

    project = Path(source["path"])
    _git(project, "config", "remote.origin.promisor", "true")
    validator = Mock(side_effect=AssertionError("partial clone validation could fetch offline"))
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", validator)
    assert publish._acceptance_for_head(project, _git(project, "rev-parse", "HEAD")) == {"state": "unavailable", "reason": "partial_clone"}
    validator.assert_not_called()


def test_successful_push_remains_published_when_local_tracking_update_fails(source: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    original = publish._git

    def inspect(project, *arguments):
        if arguments[0] == "update-ref":
            raise publish._InspectionFailed
        return original(project, *arguments)

    monkeypatch.setattr(publish, "_git", inspect)
    monkeypatch.setattr(publish, "push_captured_head_to_upstream", Mock(return_value={"status": "published", "reason": "captured_head_published", "attempted": True}))
    result = publish.publish_source_before_backup(source)
    assert result["status"] == "published"
    assert result["tracking_ref_updated"] is False
    assert result["backup_can_continue"]


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
