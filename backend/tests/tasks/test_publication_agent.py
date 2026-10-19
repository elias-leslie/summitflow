"""Publication crosses identities as pack data and keeps the source hook veto."""
from __future__ import annotations

import multiprocessing
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.tasks import backup_publish as publish
from app.tasks import publication_agent as agent
from tests.tasks.test_backup_native_recovery import _git
from tests.tasks.test_backup_publish import _URL, _head, _remote_main, source  # noqa: F401


@pytest.fixture
def agent_source(source, monkeypatch):  # noqa: F811 - imported pytest fixture
    project = Path(source["path"])
    monkeypatch.setattr(publish, "_requires_independent_repository", lambda path: path == project)
    monkeypatch.setattr(agent.tether, "_agent_uid", os.getuid)
    monkeypatch.setattr(agent, "run_installed_agent_job", lambda _module, payload, **_kwargs: agent.run_job(payload))
    _git(project, "config", "core.hooksPath", str(project / ".git/hooks"))
    return source


def test_private_copy_has_independent_objects_and_omits_source_config(agent_source):
    project, head = Path(agent_source["path"]), _head(agent_source)
    _git(project, "config", "core.sshCommand", "source-ssh-must-not-run")
    _git(project, "config", "core.fsmonitor", "source-monitor-must-not-run")
    _git(project, "config", "credential.helper", "!source-helper-must-not-run")
    _git(project, "config", "remote.origin.receivepack", "source-receive-pack-must-not-run")
    with agent.independent_repository(project, head) as clean:
        assert _git(clean, "rev-parse", f"{head}^{{commit}}") == head
        assert _git(clean, "config", "--get", "core.hooksPath") == "/dev/null"
        config = (clean / ".git/config").read_text()
        assert "source-" not in config and "remote" not in config
        assert not (clean / ".git/objects/info/alternates").exists()
        assert not (clean / ".git/hooks").exists()
        source_objects = project / ".git/objects"
        source_objects.rename(project / ".git/objects-away")
        try:
            assert _git(clean, "show", f"{head}:note") == "committed unpublished"
            assert len(_git(clean, "rev-list", head).splitlines()) == 2
        finally:
            (project / ".git/objects-away").rename(source_objects)
    assert not list((project / ".git/st/publication-transfer").iterdir())


@pytest.mark.parametrize("hook_status", [0, 1])
def test_agent_source_hook_receives_exact_update_and_can_veto(agent_source, monkeypatch, hook_status):
    project = Path(agent_source["path"])
    head, old = _head(agent_source), _remote_main(agent_source)
    record = project / "hook-record"
    hook = project / ".git/hooks/pre-push"
    hook.write_text(f'#!/bin/sh\nprintf "%s\\n%s\\n" "$1" "$2" > "{record}"\ncat >> "{record}"\nexit {hook_status}\n')
    hook.chmod(0o755)
    # Dangerous source transport configuration must never be read by an owner
    # network command. The fixture maps the captured URL to its bare remote.
    _git(project, "config", "core.sshCommand", "source-ssh-must-not-run")
    _git(project, "config", "remote.origin.pushurl", _URL)
    original = publish._git
    networks = []

    def capture(repo, *args):
        if args[0] in {"ls-remote", "fetch", "push"}:
            assert repo != project
            networks.append(args)
            assert _URL in args and "origin" not in args
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", capture)
    metadata = Mock(return_value={"private": True, "default_branch": "main"})
    monkeypatch.setattr(publish, "remote_repository", metadata)
    result = publish.publish_source(agent_source, head)
    assert record.read_text() == f"origin\n{_URL}\n{head} {head} refs/heads/main {old}\n"
    assert metadata.call_args.args[0] != project
    if hook_status:
        assert result["reason"] == "pre_push_hook_rejected"
        assert _remote_main(agent_source) == old
        assert all(args[0] != "push" for args in networks)
    else:
        assert result["status"] == "published"
        assert _remote_main(agent_source) == head
        assert _git(project, "rev-parse", "refs/remotes/origin/main") == head
        assert networks[-1][-1] == f"{head}:refs/heads/main"


def test_configured_hook_chain_runs_as_source_job(agent_source):
    project = Path(agent_source["path"])
    hooks = project / "configured-hooks"
    hooks.mkdir()
    record = project / "configured-hook-ran"
    hook = hooks / "pre-push"
    hook.write_text(f'#!/bin/sh\nprintf ran > "{record}"\nexit 1\n')
    hook.chmod(0o755)
    _git(project, "config", "core.hooksPath", str(hooks))
    result = publish.publish_source(agent_source, _head(agent_source))
    assert result["reason"] == "pre_push_hook_rejected" and record.read_text() == "ran"


def test_transfer_refuses_symlink_pack(agent_source, monkeypatch, tmp_path):
    project = Path(agent_source["path"])
    original = agent.source_job

    def tamper(repo, operation, **payload):
        result = original(repo, operation, **payload)
        if operation == "export":
            pack = agent._handoff_directory(repo, payload["transfer_id"]) / "objects.pack"
            pack.unlink()
            pack.symlink_to(tmp_path / "missing")
        return result

    monkeypatch.setattr(agent, "source_job", tamper)
    with pytest.raises(OSError), agent.independent_repository(project, _head(agent_source)):
        pytest.fail("symlink export was imported")
    assert not list((project / ".git/st/publication-transfer").iterdir())


def test_source_inspection_uses_source_adapter(monkeypatch, tmp_path):
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "head\n", ""))
    monkeypatch.setattr(publish, "run_source_git", runner)
    publish._git(tmp_path, "rev-parse", "HEAD")
    assert runner.call_args.args[0] == ["git", "--no-replace-objects", "-C", str(tmp_path), "rev-parse", "HEAD"]


def test_sha256_export_preserves_object_format(agent_source, tmp_path):
    project = tmp_path / "sha256-project"
    project.mkdir()
    _git(project, "init", "--object-format=sha256", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "note").write_text("sha256 source")
    _git(project, "add", "note")
    _git(project, "commit", "-m", "sha256 source")
    head = _git(project, "rev-parse", "HEAD")
    with agent.independent_repository(project, head) as clean:
        assert _git(clean, "rev-parse", "--show-object-format") == "sha256"
        assert _git(clean, "show", f"{head}:note") == "sha256 source"


def test_missing_remote_base_is_fetched_into_private_copy_only(agent_source, monkeypatch):
    # Export only this exact source and its ancestors. A new remote branch tip
    # is absent from the copy and must be fetched by URL before divergence wins.
    project = Path(agent_source["path"])
    head, old = _head(agent_source), _remote_main(agent_source)
    _git(project, "checkout", "--detach", old)
    (project / "remote-note").write_text("another publisher")
    _git(project, "add", "remote-note")
    _git(project, "commit", "-m", "remote advance")
    _git(project, "push", str(agent_source["remote"]), "HEAD:main")
    remote_head = _remote_main(agent_source)
    original = publish._git
    fetched = []

    def capture(repo, *args):
        if args[0] == "fetch":
            fetched.append((repo, args))
            assert repo != project and _URL in args and "origin" not in args
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", capture)
    result = publish.publish_source(agent_source, head)
    assert result["reason"] == "remote_base_diverged" and len(fetched) == 1
    assert _remote_main(agent_source) == remote_head


@pytest.mark.parametrize("listing", ["\n", "invalid\trefs/heads/main\n", "a" * 40 + "\trefs/heads/other\n"])
def test_malformed_remote_listing_never_reaches_push(agent_source, monkeypatch, listing):
    original = publish._git

    def malformed(repo, *args):
        if args[0] == "ls-remote":
            return subprocess.CompletedProcess(args, 0, listing, "")
        if args[0] == "push":
            pytest.fail("Malformed remote evidence reached push")
        return original(repo, *args)

    monkeypatch.setattr(publish, "_git", malformed)
    result = publish.publish_source(agent_source, _head(agent_source))
    assert result["reason"] == "publication_inspection_unavailable" and not result["publication_complete"]


def test_gitfile_fifo_is_rejected_without_blocking(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    os.mkfifo(project / ".git")
    context = multiprocessing.get_context("fork")
    outcome = context.Queue()

    def resolve():
        try:
            agent._handoff_directory(project, "f0c6d047-14d8-4f04-8c4b-b9d70e83cf1c")
        except RuntimeError:
            outcome.put("rejected")

    worker = context.Process(target=resolve)
    worker.start()
    try:
        worker.join(timeout=1)
        assert not worker.is_alive(), "FIFO Git metadata blocked publication before RPC"
        assert outcome.get(timeout=1) == "rejected"
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join()
        outcome.close()


def test_gitfile_symlink_is_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    gitfile = tmp_path / "gitfile"
    gitfile.write_text("gitdir: ../metadata\n")
    (project / ".git").symlink_to(gitfile)
    with pytest.raises(OSError):
        agent._handoff_directory(project, "f0c6d047-14d8-4f04-8c4b-b9d70e83cf1c")
