"""Tests for Agent Hub proxy API helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.api.agent_hub import AGENT_HUB_URL
from app.main import app

client = TestClient(app)


class TestListCodingAgents:
    """Tests for GET /api/agent-hub/agents."""

    def test_list_coding_agents_filters_invalid_rows(self, mocker: MockerFixture) -> None:
        mock_get_json = AsyncMock(
            return_value={
                "agents": [
                    {
                        "slug": "coder",
                        "name": "Coder",
                        "description": "Writes code",
                        "is_coding_agent": True,
                    },
                    {"slug": "missing-name"},
                    "not-a-dict",
                ]
            }
        )
        mocker.patch("app.api.agent_hub._get_json", mock_get_json)

        response = client.get("/api/agent-hub/agents")

        assert response.status_code == 200
        assert response.json() == {
            "agents": [
                {
                    "slug": "coder",
                    "name": "Coder",
                    "description": "Writes code",
                    "is_coding_agent": True,
                }
            ]
        }

    def test_list_agents_omits_coding_filter_by_default(self, mocker: MockerFixture) -> None:
        mock_get_json = AsyncMock(return_value={"agents": []})
        mocker.patch("app.api.agent_hub._get_json", mock_get_json)

        response = client.get("/api/agent-hub/agents")

        assert response.status_code == 200
        mock_get_json.assert_awaited_once_with(
            f"{AGENT_HUB_URL}/api/agents",
            params=None,
        )

    def test_list_agents_passes_query_flag_to_agent_hub(self, mocker: MockerFixture) -> None:
        mock_get_json = AsyncMock(return_value={"agents": []})
        mocker.patch("app.api.agent_hub._get_json", mock_get_json)

        response = client.get("/api/agent-hub/agents?is_coding_agent=false")

        assert response.status_code == 200
        mock_get_json.assert_awaited_once_with(
            f"{AGENT_HUB_URL}/api/agents",
            params={"is_coding_agent": "false"},
        )


class TestListModels:
    """GET /api/agent-hub/models uses the SDK model catalog."""

    def test_list_models_returns_sdk_catalog(self, mocker: MockerFixture) -> None:
        sdk = AsyncMock()
        sdk.__aenter__.return_value = sdk
        sdk.list_models.return_value = {"models": [{"id": "m1"}]}
        mocker.patch("app.api.agent_hub.get_async_client", return_value=sdk)

        response = client.get("/api/agent-hub/models")

        assert response.status_code == 200
        assert response.json() == {"models": [{"id": "m1"}]}

    def test_list_models_maps_sdk_errors(self, mocker: MockerFixture) -> None:
        from agent_hub.exceptions import ServerError

        sdk = AsyncMock()
        sdk.__aenter__.return_value = sdk
        sdk.list_models.side_effect = ServerError("Server error: down", status_code=503)
        mocker.patch("app.api.agent_hub.get_async_client", return_value=sdk)

        response = client.get("/api/agent-hub/models")

        assert response.status_code == 503


def test_close_session_uses_sdk(mocker: MockerFixture) -> None:
    sdk = AsyncMock()
    sdk.__aenter__.return_value = sdk
    sdk.close_session.return_value = {"id": "sess-1", "status": "completed"}
    mocker.patch("app.api.agent_hub.get_async_client", return_value=sdk)

    response = client.post("/api/agent-hub/sessions/sess-1/close")

    assert response.status_code == 200
    assert response.json() == {"id": "sess-1", "status": "completed"}
    sdk.close_session.assert_awaited_once_with("sess-1")


def test_list_sessions_forwards_search_to_agent_hub(mocker: MockerFixture) -> None:
    # `st sessions show <short-id>` resolves through this search; dropping q
    # limited the lookup to the newest few hundred sessions.
    mock_get_json = AsyncMock(return_value={"sessions": []})
    mocker.patch("app.api.agent_hub._get_json", mock_get_json)

    response = client.get("/api/agent-hub/sessions?q=c9ffbd05&page_size=100")

    assert response.status_code == 200
    mock_get_json.assert_awaited_once_with(
        f"{AGENT_HUB_URL}/api/sessions",
        params={"page": 1, "page_size": 100, "q": "c9ffbd05"},
    )
