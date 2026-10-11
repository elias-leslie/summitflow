"""Control-plane reads that moved from raw HTTP onto agent-hub-client 0.6.0."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from agent_hub.exceptions import AgentHubError
from agent_hub.models import SessionListResponse

from app.services import _lane_inventory

_SESSION = {
    "id": "s1", "project_id": "p", "provider": "codex", "model": "m", "status": "active", "message_count": 0,
    "created_at": "2026-10-09T00:00:00Z", "updated_at": "2026-10-09T00:00:00Z",
    "external_id": "task-1", "declared_scope_paths": ["app.py"],
}


class _Sync:
    def __init__(self, ownership: dict | Exception) -> None:
        self.ownership = ownership

    def __enter__(self) -> _Sync:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_project_ownership(self, project_id: str) -> dict:
        if isinstance(self.ownership, Exception):
            raise self.ownership
        return self.ownership

    def list_sessions(self, project_id: str, status: str, **_: object) -> SessionListResponse:
        return SessionListResponse.model_validate({"sessions": [_SESSION], "total": 1, "page": 1, "page_size": 100})


def test_lane_inventory_reads_live_ownership() -> None:
    owner = {"session_id": "s1", "task_id": "task-1"}
    with patch.object(_lane_inventory, "get_sync_client", return_value=_Sync({"active_owners": [owner], "active_specialists": []})):
        owners, specialists = _lane_inventory.fetch_live_project_inventory("p")
    assert (owners[0]["id"], owners[0]["external_id"], specialists) == ("s1", "task-1", [])


def test_lane_inventory_falls_back_to_active_sessions_without_dropping_fields() -> None:
    with patch.object(_lane_inventory, "get_sync_client", return_value=_Sync(AgentHubError("missing", status_code=404))):
        owners, specialists = _lane_inventory.fetch_live_project_inventory("p")
    assert owners[0]["external_id"] == "task-1"
    assert owners[0]["declared_scope_paths"] == ["app.py"]
    assert specialists == []


def test_lane_inventory_raises_other_agent_hub_errors() -> None:
    with (
        patch.object(_lane_inventory, "get_sync_client", return_value=_Sync(AgentHubError("boom", status_code=500))),
        pytest.raises(AgentHubError),
    ):
        _lane_inventory.fetch_live_project_inventory("p")
