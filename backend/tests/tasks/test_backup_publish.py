"""Publication pushes one exact committed source by plain fast-forward and preserves the checkout."""
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
from tests.tasks.git_helpers import _git

_acceptance_lookup = publish._acceptance_for_head
_URL = "https://github.com/fixture/project.git"


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A private GitHub project one commit ahead of its (local bare) remote."""
    from app.services.git import outgoing

    remote = tmp_path / "remote.git"
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "note").write_text("published")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "published")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    _git(project, "push", "-q", str(remote), "main")
    _git(project, "remote", "add", "origin", _URL)
    _git(project, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(project, "branch", "--set-upstream-to", "origin/main")
    (project / "note").write_text("committed unpublished")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "unpublished")
    original = publish._git

    def routed(repo, *args):
        # Network commands reach the bare fixture remote, without global hooks.
        if args[0] in {"push", "fetch", "ls-remote"}:
            return subprocess.run(["git", "-c", f"url.{remote}.insteadOf={_URL}", "-c", "core.hooksPath=/dev/null",
                                   "-C", str(repo), *args], capture_output=True, text=True, check=False)
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", routed)
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda _repo, _head: {"state": "missing"})
    monkeypatch.setattr(publish, "remote_repository", lambda *_: {"private": True, "default_branch": "main"})
    monkeypatch.setattr(outgoing, "verify_outgoing", Mock(return_value=Mock(commits_scanned=1, refs_checked=1)))
    return {"id": "fixture", "path": str(project), "source_type": "project", "enabled": True, "project_id": "fixture",
            "remote": remote}


def _head(source: dict) -> str:
    return _git(Path(source["path"]), "rev-parse", "HEAD")


def _remote_main(source: dict) -> str:
    return _git(source["remote"], "rev-parse", "main")


def _local_refs(project: Path, listing: str | None = None) -> list[str]:
    """Every ref except remote-tracking ones, which record the push."""
    rows = (listing if listing is not None else _git(project, "show-ref")).splitlines()
    return [row for row in rows if " refs/remotes/" not in row]


def test_private_repository_pushes_committed_head_and_preserves_checkout(source):
    project = Path(source["path"])
    head = _head(source)
    _git(project, "branch", "private-work")
    (project / "note").write_text("staged")
    _git(project, "add", "note")
    (project / "note").write_text("unstaged")
    (project / "unfinished").write_text("untracked")
    index = (project / ".git/index").read_bytes()
    refs = _git(project, "show-ref")

    result = publish.publish_source(source, head)

    assert result["status"] == "published" and result["reason"] == "source_published"
    assert result["publication_complete"] and result["pushed"] and result["visibility"] == "private"
    assert result["acceptance"] == {"state": "not_required", "reason": "private_repository", "source_commit": head}
    assert result["security"]["state"] == "success" and result["security"]["sha"] == head
    assert _remote_main(source) == head
    assert _git(project, "rev-parse", "refs/remotes/origin/main") == head  # the push records itself
    assert (project / ".git/index").read_bytes() == index
    assert _local_refs(project) == _local_refs(project, refs)
    assert _git(project, "show", ":note") == "staged"
    assert (project / "note").read_text() == "unstaged"
    assert (project / "unfinished").read_text() == "untracked"


@pytest.mark.parametrize("state", ["missing", "invalid", "unavailable"])
def test_public_repository_never_pushes_an_unaccepted_commit(source, monkeypatch, state):
    monkeypatch.setattr(publish, "remote_repository", lambda *_: {"private": False, "default_branch": "main"})
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda *_: {"state": state})
    before = _remote_main(source)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "pending" and result["reason"] == "source_acceptance_required"
    assert result["visibility"] == "public" and not result["attempted"] and result["action"]
    assert _remote_main(source) == before


def test_public_repository_pushes_an_accepted_commit(source, monkeypatch):
    head = _head(source)
    accepted = {"state": "reused", "acceptance_id": "receipt", "source_commit": head}
    monkeypatch.setattr(publish, "remote_repository", lambda *_: {"private": False, "default_branch": "main"})
    monkeypatch.setattr(publish, "_acceptance_for_head", lambda *_: accepted)
    result = publish.publish_source(source, head)
    assert result["status"] == "published" and result["acceptance"] == accepted
    assert result["source_status"] == "accepted" and _remote_main(source) == head


def test_non_github_remote_counts_as_public(source, monkeypatch):
    monkeypatch.setattr(publish, "remote_repository", lambda *_: None)  # what any non-GitHub host returns
    assert publish.is_public(None) and publish.is_public({"private": False}) and not publish.is_public({"private": True})
    result = publish.publish_source(source, _head(source))
    assert result["reason"] == "source_acceptance_required" and result["visibility"] == "public"


def test_remote_repository_reads_github_metadata_only_for_github(monkeypatch, tmp_path):
    from cli.lib import github_publish

    api = Mock(return_value={"private": True})
    monkeypatch.setattr(github_publish.GitHub, "api", api)
    assert publish.remote_repository(tmp_path, ("github.com", None, "owner/repo")) == {"private": True}
    api.assert_called_once_with("")
    assert publish.remote_repository(tmp_path, ("gitlab.com", None, "owner/repo")) is None
    assert publish.remote_repository(tmp_path, ("github.com", 8443, "owner/repo")) is None


def test_source_already_on_remote_needs_no_push(source):
    head = _head(source)
    assert publish.publish_source(source, head)["pushed"] is True
    again = publish.publish_source(source, head)
    assert again["publication_complete"] and again["pushed"] is False and again["reason"] == "already_on_remote"
    older = publish.publish_source(source, _git(Path(source["path"]), "rev-parse", "HEAD~1"))
    assert older["reason"] == "already_on_remote" and _remote_main(source) == head


def test_remote_work_this_checkout_lacks_blocks_without_push(source, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(source["remote"]), str(other)], check=True)
    _git(other, "-c", "user.name=Other", "-c", "user.email=o@example.invalid", "commit", "--allow-empty", "-m", "remote only")
    _git(other, "push", "-q", "origin", "main")
    remote_head = _remote_main(source)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "failed" and result["reason"] == "remote_base_diverged"
    assert not result["publication_complete"] and _remote_main(source) == remote_head


def test_porcelain_ref_rejection_is_a_finding_and_transport_failure_is_pending(source, monkeypatch):
    routed = publish._git

    def rejecting(repo, *args):
        if args[0] == "push":
            assert "--porcelain" in args and "--force" not in args
            return subprocess.CompletedProcess(args, 1, "!\tHEAD:refs/heads/main\t[remote rejected]\n", "secret-diagnostic")
        return routed(repo, *args)

    monkeypatch.setattr(publish, "_git", rejecting)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "failed" and result["reason"] == "remote_push_rejected"
    assert "secret-diagnostic" not in json.dumps(result)

    def offline(repo, *args):
        if args[0] == "ls-remote":
            return subprocess.CompletedProcess(args, 128, "", "fixture-secret-network-diagnostic")
        return routed(repo, *args)

    monkeypatch.setattr(publish, "_git", offline)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "pending" and result["reason"] == "remote_transport_unavailable"
    assert result["remote_status"] == "unknown" and "fixture-secret" not in json.dumps(result)

    def logged_out(repo, *args):
        if args[0] == "ls-remote":
            return subprocess.CompletedProcess(args, 128, "", "fatal: could not read Username for 'https://github.com'")
        return routed(repo, *args)

    monkeypatch.setattr(publish, "_git", logged_out)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "pending" and result["reason"] == "remote_authentication_unavailable"
    assert "could not read" not in json.dumps(result)


def test_network_timeout_is_typed_but_local_inspection_remains_actionable(tmp_path, monkeypatch):
    original = publish._git
    monkeypatch.setattr(publish.shutil, "which", lambda _: "/usr/bin/timeout")
    monkeypatch.setattr(publish, "_git", lambda *_: subprocess.CompletedProcess([], 1, "", ""))
    monkeypatch.setattr(publish.safe_subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("fixture", 310)))
    with pytest.raises(publish._TransportUnavailable):
        original(tmp_path, "ls-remote", "origin")
    with pytest.raises(publish._InspectionFailed) as exc:
        original(tmp_path, "rev-parse", "HEAD")
    assert not isinstance(exc.value, publish._TransportUnavailable)
    monkeypatch.setattr(publish.shutil, "which", lambda _: None)
    with pytest.raises(publish._TransportUnavailable):
        original(tmp_path, "ls-remote", "origin")


def test_deployment_workflow_requires_separate_explicit_authority(source):
    project = Path(source["path"])
    workflow = project / ".github/workflows/deploy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("on: push\njobs:\n  deploy:\n    environment: production\n    steps:\n      - run: scripts/deploy.sh\n")
    _git(project, "add", ".github")
    _git(project, "commit", "-m", "Declare deployment effects")
    sha = _head(source)
    before = _remote_main(source)
    # Later WIP cannot erase effects in the selected immutable source.
    workflow.write_text("on: workflow_dispatch\njobs: {}\n")
    pending = publish.publish_source(source, sha)
    assert pending["status"] == "pending" and pending["reason"] == "workflow_effects_authorization_required"
    assert pending["unauthorized_workflows"] == [".github/workflows/deploy.yml"]
    assert _remote_main(source) == before
    authorized = publish.publish_source(source, sha, authorized_workflows=(".github/workflows/deploy.yml",))
    assert authorized["status"] == "published" and _remote_main(source) == sha


@pytest.mark.parametrize(("repository", "reason"), [({"private": True, "archived": True}, "remote_repository_archived"),
                                                    ({"private": True, "default_branch": "trunk"}, "remote_default_branch_mismatch")])
def test_remote_metadata_mismatch_never_pushes(source, monkeypatch, repository, reason):
    monkeypatch.setattr(publish, "remote_repository", lambda *_: repository)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "skipped" and result["reason"] == reason and not result["attempted"]


@pytest.mark.parametrize(("unavailable", "status"), [(True, "pending"), (False, "failed")])
def test_github_metadata_error_is_pending_only_for_outages(source, monkeypatch, unavailable, status):
    from cli.lib.github_publish import GitHubError

    reason = "remote_authentication_unavailable" if unavailable else "remote_publication_failed"
    monkeypatch.setattr(publish, "remote_repository", Mock(side_effect=GitHubError("fixture-token-never-persist",
                                                                                    unavailable=unavailable, reason=reason)))
    result = publish.publish_source(source, _head(source))
    assert result["status"] == status and result["reason"] == reason
    assert "fixture-token" not in json.dumps(result)


@pytest.mark.parametrize("requested", ["", "HEAD", "a" * 12, "a" * 41, "A" * 40, "fixture-private-diagnostic"])
def test_invalid_source_fails_before_inspection(source, monkeypatch, requested):
    inspector = Mock(side_effect=AssertionError("Invalid source must not inspect or publish"))
    monkeypatch.setattr(publish, "_git", inspector)
    result = publish.publish_source(source, requested)
    assert result["status"] == "failed" and result["reason"] == "invalid_manual_source"
    assert result["requested_source_commit"] is None and not result["attempted"]
    assert "fixture-private" not in json.dumps(result)
    inspector.assert_not_called()


@pytest.mark.parametrize("requested", ["a" * 40, "a" * 64])
def test_missing_source_object_never_substitutes_head(source, monkeypatch, requested):
    pusher = Mock(side_effect=AssertionError("No fallback to current HEAD"))
    monkeypatch.setattr(publish, "_push", pusher)
    result = publish.publish_source(source, requested)
    assert result["status"] == "failed" and result["reason"] == "manual_source_unavailable"
    assert result["captured_source_commit"] is None
    pusher.assert_not_called()


def test_detached_checkout_still_publishes_the_selected_source(source):
    project = Path(source["path"])
    selected = _git(project, "rev-parse", "main")
    _git(project, "checkout", "--detach", "HEAD~1")
    result = publish.publish_source(source, selected)
    assert result["head"] == selected and _remote_main(source) == selected
    assert _git(project, "rev-parse", "HEAD") != selected


@pytest.mark.parametrize("case", ["disabled", "non_project", "unregistered", "no_upstream", "local", "loopback",
                                  "wrong_push_route", "multiple_routes", "wrong_upstream", "mirror"])
def test_uncertain_sources_never_reach_the_push(source, monkeypatch, case):
    project = Path(source["path"])
    pusher = Mock(side_effect=AssertionError("Unsafe publication route"))
    monkeypatch.setattr(publish, "_push", pusher)
    if case == "disabled":
        source["enabled"] = False
    elif case == "non_project":
        source["source_type"] = "infrastructure"
    elif case == "unregistered":
        source["id"] = None
    elif case == "no_upstream":
        _git(project, "branch", "--unset-upstream")
    elif case == "local":
        _git(project, "remote", "set-url", "origin", "/tmp/private-repository.git")
    elif case == "loopback":
        _git(project, "remote", "set-url", "origin", "ssh://git@localhost/project.git")
    elif case == "wrong_push_route":
        _git(project, "remote", "set-url", "--push", "origin", "https://github.com/wrong/private.git")
    elif case == "multiple_routes":
        _git(project, "remote", "set-url", "--add", "--push", "origin", _URL)
        _git(project, "remote", "set-url", "--add", "--push", "origin", "https://github.com/second/project.git")
    elif case == "wrong_upstream":
        _git(project, "config", "branch.main.merge", "refs/heads/private")
    else:
        _git(project, "config", "remote.origin.mirror", "true")
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "skipped" and not result["attempted"]
    pusher.assert_not_called()


def test_security_failure_never_pushes_and_reports_only_the_redacted_reason(source, monkeypatch):
    from app.services.git import outgoing

    before = _remote_main(source)
    monkeypatch.setattr(outgoing, "verify_outgoing", Mock(side_effect=outgoing.OutgoingVerificationError(
        "Outgoing secret scan refused history or failed (details redacted).")))
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "failed" and result["reason"] == "outgoing_verification_failed"
    assert result["security"] == {"state": "blocked", "sha": _head(source),
                                  "reason": "Outgoing secret scan refused history or failed (details redacted)."}
    assert _remote_main(source) == before


def test_shared_admission_outage_defers_publication_without_push_or_repair(source, monkeypatch):
    from app.services import publication_health
    from app.services.git import outgoing

    before = _remote_main(source)
    monkeypatch.setattr(outgoing, "verify_outgoing", Mock(side_effect=outgoing.OutgoingAdmissionUnavailable(
        "fixture-private-storage-diagnostic")))
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "pending" and result["reason"] == "heavy_work_admission_unavailable"
    assert result["security"]["state"] == "unavailable" and result["remote_status"] == "unknown"
    assert "fixture-private-storage-diagnostic" not in json.dumps(result)
    assert _remote_main(source) == before
    recorder = Mock()
    monkeypatch.setattr(publication_health, "record_finding", recorder)
    assert publication_health.record_publication_observation("fixture", result) is None
    recorder.assert_not_called()


def test_verifier_sees_the_exact_fast_forward_update(source, monkeypatch):
    from app.services.git import outgoing

    base = _remote_main(source)
    head = _head(source)
    verifier = Mock(return_value=Mock(commits_scanned=1, refs_checked=1))
    monkeypatch.setattr(outgoing, "verify_outgoing", verifier)
    publish.publish_source(source, head)
    update = verifier.call_args.args[2][0]
    assert (update.local_oid, update.remote_oid, update.remote_ref) == (head, base, "refs/heads/main")
    assert verifier.call_args.kwargs["published_bases"] == (base,)


def test_pre_push_hook_rejection_is_a_finding_not_a_transport_blip(source, monkeypatch, tmp_path):
    """A refusing pre-push hook (such as the pinned outgoing verifier) prints no
    porcelain ref line; it must still reach repair instead of retrying silently."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text("#!/bin/sh\necho hook-diagnostic >&2\nexit 1\n")
    (hooks / "pre-push").chmod(0o755)
    remote = source["remote"]
    original = publish._git
    before = _remote_main(source)

    def hooked(repo, *args):
        if args[0] == "push":
            return subprocess.run(["git", "-c", f"url.{remote}.insteadOf={_URL}", "-c", f"core.hooksPath={hooks}",
                                   "-C", str(repo), *args], capture_output=True, text=True, check=False)
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", hooked)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "failed" and result["reason"] == "pre_push_hook_rejected"
    assert not result["publication_complete"] and _remote_main(source) == before
    assert "hook-diagnostic" not in json.dumps(result)

    def dropped(repo, *args):
        if args[0] == "push":
            return subprocess.CompletedProcess(args, 128, "", "fatal: Could not read from remote repository.")
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", dropped)
    result = publish.publish_source(source, _head(source))
    assert result["status"] == "pending" and result["reason"] == "remote_transport_unavailable"


def test_push_never_reads_codeql_before_github_analyzed_it(source, monkeypatch):
    from app.services import publication_security

    monkeypatch.setattr(publication_security, "observe_codeql", Mock(side_effect=AssertionError("too early")))
    result = publish.publish_source(source, _head(source))
    assert result["publication_complete"] and "codeql" not in result


def test_acceptance_lookup_uses_the_canonical_receipt_index(source, monkeypatch):
    from cli.lib import acceptance

    project = Path(source["path"])
    head = _head(source)
    monkeypatch.setattr(acceptance, "receipt_for_commit", Mock(return_value={"acceptance_id": "validated"}))
    assert _acceptance_lookup(project, head) == {"state": "reused", "acceptance_id": "validated", "source_commit": head}
    monkeypatch.setattr(acceptance, "receipt_for_commit", Mock(return_value=None))
    assert _acceptance_lookup(project, head) == {"state": "missing"}
    monkeypatch.setattr(acceptance, "receipt_for_commit", Mock(side_effect=RuntimeError("private diagnostic")))
    assert _acceptance_lookup(project, head) == {"state": "unavailable"}


def test_task_receipt_never_counts_as_full_acceptance(source, monkeypatch, local_gate_tools):
    from cli.lib import acceptance

    project = Path(source["path"])
    head = _head(source)
    runner = Mock(side_effect=lambda command, cwd: subprocess.CompletedProcess(command, 0, "RUFF:OK:0", ""))
    acceptance.accept_revision(project, sha=head, coverage="task", scope=("note",), runner=runner, reuse=False)
    assert _acceptance_lookup(project, head) == {"state": "missing"}
    full = acceptance.accept_revision(project, sha=head, runner=runner)
    assert _acceptance_lookup(project, head) == {"state": "reused", "acceptance_id": full["acceptance_id"], "source_commit": head}


def test_partial_clone_receipts_do_not_lazily_fetch(source, monkeypatch):
    from cli.lib import acceptance

    project = Path(source["path"])
    _git(project, "config", "remote.origin.promisor", "true")
    lookup = Mock(side_effect=AssertionError("No lazy fetch"))
    monkeypatch.setattr(acceptance, "receipt_for_commit", lookup)
    assert _acceptance_lookup(project, _head(source)) == {"state": "unavailable", "reason": "partial_clone"}
    lookup.assert_not_called()


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
