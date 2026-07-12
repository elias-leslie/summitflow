"""Tests for liveness, readiness, and startup schema ownership."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Response, status

from app.main import (
    _check_schema_health,
    app,
    health_check,
    lifespan,
    readiness_check,
)
from app.schemas.health import ComponentHealth


@pytest.mark.asyncio
async def test_liveness_does_not_probe_dependencies() -> None:
    with (
        patch("app.main._check_database_health", side_effect=AssertionError),
        patch("app.main._check_cache_health", side_effect=AssertionError),
        patch("app.main._check_schema_health", side_effect=AssertionError),
    ):
        result = await health_check()

    assert result == {"status": "healthy", "service": "summitflow"}


@pytest.mark.asyncio
async def test_readiness_is_healthy_only_after_fresh_dependency_checks() -> None:
    healthy = ComponentHealth(status="healthy", message="ok")
    response = Response()

    with (
        patch("app.main._check_database_health", return_value=healthy) as database,
        patch("app.main._check_cache_health", return_value=healthy) as cache,
        patch("app.main._check_schema_health", return_value=healthy) as schema,
    ):
        result = await readiness_check(response)

    assert result.status == "ready"
    assert response.status_code == status.HTTP_200_OK
    database.assert_called_once_with()
    cache.assert_called_once_with()
    schema.assert_called_once_with()


@pytest.mark.asyncio
async def test_readiness_returns_503_for_schema_drift() -> None:
    healthy = ComponentHealth(status="healthy", message="ok")
    stale = ComponentHealth(status="unhealthy", message="migration required")
    response = Response()

    with (
        patch("app.main._check_database_health", return_value=healthy),
        patch("app.main._check_cache_health", return_value=healthy),
        patch("app.main._check_schema_health", return_value=stale),
    ):
        result = await readiness_check(response)

    assert result.status == "not_ready"
    assert result.schema_status == stale
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_schema_health_requires_database_to_match_all_alembic_heads() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [("revision-a",), ("revision-b",)]
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor

    with (
        patch("app.main._expected_schema_heads", return_value=frozenset({"revision-a", "revision-b"})),
        patch("app.storage.connection.get_cursor", return_value=cursor_context),
    ):
        result = _check_schema_health()

    assert result.status == "healthy"
    cursor.execute.assert_called_once_with("SELECT version_num FROM alembic_version")


def test_schema_health_reports_current_and_expected_revisions() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [("old-revision",)]
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor

    with (
        patch("app.main._expected_schema_heads", return_value=frozenset({"head-revision"})),
        patch("app.storage.connection.get_cursor", return_value=cursor_context),
    ):
        result = _check_schema_health()

    assert result.status == "unhealthy"
    assert result.message is not None
    assert "current=old-revision" in result.message
    assert "expected=head-revision" in result.message


@pytest.mark.asyncio
async def test_lifespan_does_not_run_ddl_or_owner_dml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    runtime_task = object()

    with (
        patch("app.storage.connection.open_pool") as open_pool,
        patch("app.storage.connection.close_pool") as close_pool,
        patch("app.storage.connection.init_schema") as init_schema,
        patch("app.access_control.bootstrap_configured_owners") as bootstrap_owners,
        patch(
            "app.services.runtime_metrics_sampler.start_runtime_metrics_sampler",
            return_value=runtime_task,
        ) as start_sampler,
        patch(
            "app.services.runtime_metrics_sampler.stop_runtime_metrics_sampler",
            new_callable=AsyncMock,
        ) as stop_sampler,
    ):
        async with lifespan(app):
            open_pool.assert_called_once_with()
            start_sampler.assert_called_once_with()

    init_schema.assert_not_called()
    bootstrap_owners.assert_not_called()
    stop_sampler.assert_awaited_once_with()
    close_pool.assert_called_once_with()
