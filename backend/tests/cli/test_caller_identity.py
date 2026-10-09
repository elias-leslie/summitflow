"""One session owner across core tasks and trusted owner extensions."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import typer

from cli import _client_tasks, extensions
from cli.commands import claim, done_task
from cli.extension_contract import ExtensionBinding
from cli.lib import task_claims


@pytest.fixture(autouse=True)
def isolated_identity(monkeypatch):
    for key in ("ST_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_SESSION_ID",
                "CODEX_THREAD_ID", "AGENT_HUB_SESSION_ID", "AGENT_HUB_AGENT_SLUG",
                "PI_SESSION_ID", "TMUX_PANE", "ST_CALLER_IDENTITY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(task_claims.socket, "gethostname", lambda: "shared-host")


@pytest.mark.parametrize(("key", "provider", "slug"), [
    ("CODEX_SESSION_ID", "codex_cli", "codex"),
    ("CLAUDE_SESSION_ID", "claude_code", "claude-code"),
    ("AGENT_HUB_SESSION_ID", "agent_hub_specialist", "reviewer"),
    ("PI_SESSION_ID", "pi", "pi"),
    ("ST_SESSION_ID", "st", "st"),
])
def test_full_native_identity_is_stable_and_provider_agnostic(monkeypatch, key, provider, slug):
    monkeypatch.setenv("AGENT_HUB_AGENT_SLUG", "reviewer")
    monkeypatch.setenv(key, "abcdef-root-one")
    first = task_claims.current_caller_identity()
    assert first == {"member_id": f"{provider}:{slug}:abcdef-root-one",
                     "provider": provider, "session_id": "abcdef-root-one"}
    assert task_claims.current_worker_id() == first["member_id"]
    monkeypatch.setenv(key, "abcdef-root-two")
    assert task_claims.current_worker_id() != first["member_id"]
    monkeypatch.setenv(key, "abcdef-root-one")
    assert task_claims.current_caller_identity() == first


@pytest.mark.parametrize("value", ["", " invalid", "bad\nidentity", "x" * 129, "../session"])
def test_invalid_native_identity_keeps_legacy_non_session_fallback(monkeypatch, value):
    monkeypatch.setenv("CODEX_SESSION_ID", value)
    monkeypatch.setenv("CODEX_THREAD_ID", "inherited-thread")
    monkeypatch.setenv("TMUX_PANE", "%42")
    assert task_claims.current_caller_identity() == {"member_id": "shared-host", "provider": "hostname"}


def test_native_session_never_adopts_legacy_hostname_claim(monkeypatch):
    assert task_claims.current_worker_id() == "shared-host"
    monkeypatch.setenv("CODEX_SESSION_ID", "native-root")
    assert not claim._is_same_caller("shared-host")
    assert claim._is_same_caller(task_claims.current_worker_id())


def test_public_claim_default_and_explicit_worker_contract(monkeypatch):
    monkeypatch.setenv("CODEX_SESSION_ID", "native-root")
    client = Mock()
    _client_tasks.claim_task(client, lambda path: path, lambda response: {}, "task-one")
    assert client.post.call_args.kwargs["json"]["worker_id"] == task_claims.current_worker_id()
    _client_tasks.claim_task(client, lambda path: path, lambda response: {}, "task-one", worker_id="dispatch-worker")
    assert client.post.call_args.kwargs["json"]["worker_id"] == "dispatch-worker"


def test_extension_envelope_is_computed_and_matches_core_owner(monkeypatch):
    monkeypatch.setenv("CODEX_SESSION_ID", "native-root")
    monkeypatch.setenv("ST_CALLER_IDENTITY", '{"member_id":"shared-host"}')
    monkeypatch.setenv("PRIVATE_SESSION_SECRET", "excluded")
    binding = ExtensionBinding.model_validate({
        "id": "fixture.extension", "owner": "fixture-owner", "namespace": "fixture",
        "manifest": "extensions/fixture.json", "executable": "fixture",
        "grant": {"enabled": True, "effects": ["read-local"]},
        "environment": ["ST_CALLER_IDENTITY"],
    })
    env = extensions._environment(binding, {"contract_version": 1})
    assert json.loads(env["ST_CALLER_IDENTITY"]) == task_claims.current_caller_identity()
    assert "PRIVATE_SESSION_SECRET" not in env
    assert "CODEX_SESSION_ID" not in env


@pytest.mark.parametrize(("owner", "other_root"), [
    ("abcdef-root-one", "abcdef-root-two"),
    ("abcdef-root-two", "abcdef-root-one"),
])
def test_same_host_roots_cannot_renew_accept_or_complete_each_other(
    monkeypatch, tmp_path, test_project_id, cleanup_task, owner, other_root
):
    from app.storage import projects, tasks

    monkeypatch.setattr(task_claims, "get_config_optional", lambda: SimpleNamespace(
        api_base="http://localhost:8001/api", project_id=test_project_id, project_root=str(tmp_path)))
    monkeypatch.setattr(projects, "get_project_root_path", lambda _: str(tmp_path))
    monkeypatch.setenv("CODEX_SESSION_ID", owner)
    task = tasks.create_task(test_project_id, "Same host session isolation")
    cleanup_task(task["id"])
    owned = tasks.claim_task(task["id"], task_claims.current_worker_id())
    assert owned is not None

    def stored_task():
        current = tasks.get_task(task["id"])
        assert current is not None
        return current

    client = Mock()
    client.get_task.side_effect = lambda _: stored_task()
    client.claim_task.side_effect = lambda tid, **kwargs: tasks.claim_task(
        tid, task_claims.current_worker_id(), **kwargs)
    monkeypatch.setattr(claim, "get_snapshot_info", lambda _: {"base_branch": "main"})
    monkeypatch.setattr(claim, "preflight", Mock())

    resumed = claim._claim_task(client, task["id"])
    assert resumed["action"] == "resumed"
    assert stored_task()["claimed_at"] == owned["claimed_at"]
    renewed = task_claims.renew_local_owned_claim(tmp_path, task["id"])
    receipt: dict[str, object] = {"state": "success", "source_commit": "a" * 40}
    assert task_claims.attach_owned_acceptance(tmp_path, renewed, receipt)
    assert done_task._owned_completion_claim(tmp_path, task["id"], test_project_id)["claimed_by"] == owned["claimed_by"]

    monkeypatch.setenv("CODEX_SESSION_ID", other_root)
    with pytest.raises(typer.Exit):
        claim._claim_task(client, task["id"])
    for operation in (
        lambda: task_claims.renew_local_owned_claim(tmp_path, task["id"]),
        lambda: task_claims.attach_owned_acceptance(tmp_path, renewed, receipt),
        lambda: done_task._owned_completion_claim(tmp_path, task["id"], test_project_id),
    ):
        with pytest.raises(task_claims.TaskClaimRenewalError):
            operation()
    assert stored_task()["status"] == "running"
    assert stored_task()["claimed_by"] == owned["claimed_by"]

    monkeypatch.setenv("CODEX_SESSION_ID", owner)
    assert claim._claim_task(client, task["id"])["action"] == "resumed"
    exact_claim = done_task._owned_completion_claim(tmp_path, task["id"], test_project_id)
    monkeypatch.setattr(done_task, "_auto_verify_readiness", Mock())
    assert done_task._close_task_safely(client, task["id"], None, owned_claim=exact_claim)["status"] == "completed"
