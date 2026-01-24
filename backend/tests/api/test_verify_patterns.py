"""Tests for verify_patterns API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestRecordEndpoint:
    """Tests for POST /api/verify-patterns/record."""

    def test_record_success(self):
        """Recording a success returns pattern data."""
        response = client.post(
            "/api/verify-patterns/record",
            json={
                "command": "echo 'test_record_api'",
                "success": True,
                "duration_ms": 100,
                "exit_code": 0,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "pattern_hash" in data
        assert "success_count" in data

    def test_record_failure(self):
        """Recording a failure returns pattern data."""
        response = client.post(
            "/api/verify-patterns/record",
            json={
                "command": "echo 'test_record_fail'",
                "success": False,
                "duration_ms": 50,
                "exit_code": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["fail_count"] >= 1


class TestLookupEndpoint:
    """Tests for GET /api/verify-patterns/lookup."""

    def test_lookup_unknown_command(self):
        """Unknown commands return default stats."""
        response = client.get(
            "/api/verify-patterns/lookup",
            params={"command": "some_unique_command_12345"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is False
        assert data["total_runs"] == 0

    def test_lookup_returns_stats_structure(self):
        """Lookup returns expected structure."""
        response = client.get(
            "/api/verify-patterns/lookup",
            params={"command": "echo test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "success_rate" in data
        assert "total_runs" in data
        assert "avg_duration_ms" in data
        assert "pattern_type" in data


class TestSuggestEndpoint:
    """Tests for GET /api/verify-patterns/suggest."""

    def test_suggest_returns_list(self):
        """Suggest endpoint returns a list."""
        response = client.get(
            "/api/verify-patterns/suggest",
            params={"type": "deploy"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_suggest_respects_limit(self):
        """Suggest endpoint respects limit parameter."""
        response = client.get(
            "/api/verify-patterns/suggest",
            params={"type": "deploy", "limit": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 2

    def test_suggest_requires_type(self):
        """Suggest endpoint requires type parameter."""
        response = client.get("/api/verify-patterns/suggest")
        assert response.status_code == 422  # Validation error
