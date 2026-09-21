from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli.lib import task_claims


def config(root: Path, *, api_base: str = "http://localhost:8001/api") -> SimpleNamespace:
    return SimpleNamespace(api_base=api_base, project_id="summitflow", project_root=str(root))


def test_local_renewal_rejects_remote_api_before_touching_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        task_claims, "get_config_optional", lambda: config(tmp_path, api_base="https://st.example/api")
    )

    with pytest.raises(task_claims.TaskClaimRenewalError, match="remote ST API"):
        task_claims.renew_local_owned_claim(tmp_path, "task-one")


def test_local_renewal_requires_matching_checkout_and_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(task_claims, "get_config_optional", lambda: config(other))

    with pytest.raises(task_claims.TaskClaimRenewalError, match="does not match"):
        task_claims.renew_local_owned_claim(tmp_path, "task-one")


def test_local_renewal_uses_exact_current_worker_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.storage import projects
    from app.storage import tasks as task_store

    renew = Mock(return_value={"id": "task-one", "status": "running"})
    monkeypatch.setattr(task_claims, "get_config_optional", lambda: config(tmp_path))
    monkeypatch.setattr(task_claims, "current_worker_id", lambda: "worker-one")
    monkeypatch.setattr(projects, "get_project_root_path", lambda _project_id: str(tmp_path))
    monkeypatch.setattr(task_store, "get_task", lambda _task_id: {"project_id": "summitflow"})
    monkeypatch.setattr(task_store, "renew_task_claim", renew)

    result = task_claims.renew_local_owned_claim(tmp_path, "task-one")

    assert result["status"] == "running"
    renew.assert_called_once_with("task-one", "worker-one")


def test_local_renewal_never_claims_pending_or_wrong_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.storage import projects
    from app.storage import tasks as task_store

    monkeypatch.setattr(task_claims, "get_config_optional", lambda: config(tmp_path))
    monkeypatch.setattr(projects, "get_project_root_path", lambda _project_id: str(tmp_path))
    monkeypatch.setattr(task_store, "get_task", lambda _task_id: {"project_id": "summitflow"})
    monkeypatch.setattr(task_store, "renew_task_claim", lambda *_args: None)

    with pytest.raises(task_claims.TaskClaimRenewalError, match="not actively owned"):
        task_claims.renew_local_owned_claim(tmp_path, "task-one")


def test_remote_renewal_uses_public_owner_bound_claim_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = Mock()
    client.get_task.return_value = {
        "project_id": "summitflow",
        "status": "running",
        "claimed_by": "worker-one",
    }
    client.claim_task.return_value = {"id": "task-one", "status": "running"}
    monkeypatch.setattr(
        task_claims,
        "get_config_optional",
        lambda: config(tmp_path, api_base="https://st.example/api"),
    )
    monkeypatch.setattr(task_claims, "current_worker_id", lambda: "worker-one")
    monkeypatch.setattr("cli.client.STClient", lambda **_kwargs: client)

    result = task_claims.renew_owned_claim(tmp_path, "task-one")

    assert result["status"] == "running"
    client.claim_task.assert_called_once_with(
        "task-one", worker_id="worker-one", renew_only=True
    )


def test_remote_old_api_conflict_never_falls_back_to_local_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cli.client import APIError

    client = Mock()
    client.get_task.return_value = {
        "project_id": "summitflow",
        "status": "running",
        "claimed_by": "worker-one",
    }
    client.claim_task.side_effect = APIError(409, "already running")
    monkeypatch.setattr(
        task_claims,
        "get_config_optional",
        lambda: config(tmp_path, api_base="https://st.example/api"),
    )
    monkeypatch.setattr(task_claims, "current_worker_id", lambda: "worker-one")
    monkeypatch.setattr("cli.client.STClient", lambda **_kwargs: client)
    local = Mock()
    monkeypatch.setattr(task_claims, "renew_local_owned_claim", local)

    with pytest.raises(task_claims.TaskClaimRenewalError, match="upgrade it first"):
        task_claims.renew_owned_claim(tmp_path, "task-one")

    local.assert_not_called()
