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
