"""Tests for pickup guard conditions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_hub.models import SessionListResponse

from app.tasks.autonomous.pickup_guards import (
    check_allowed_external_origin,
    check_allowed_task_type,
    check_autonomous_enabled,
    check_system_health,
    check_work_pickup_enabled,
    count_active_agent_hub_sessions,
    get_concurrency_snapshot,
    validate_autonomous_dispatch,
)


def test_external_origin_allowlist_rejects_null_and_unrelated_origins() -> None:
    with patch(
        "app.tasks.autonomous.pickup_guards.get_allowed_external_origins",
        return_value=["agent-hub-context-maintenance"],
    ):
        assert check_allowed_external_origin("summitflow", "agent-hub-context-maintenance") is None
        missing_origin = check_allowed_external_origin("summitflow", None)
        assert missing_origin is not None
        assert missing_origin["status"] == "external_origin_not_allowed"
        unrelated_origin = check_allowed_external_origin("summitflow", "other-client")
        assert unrelated_origin is not None
        assert unrelated_origin["status"] == "external_origin_not_allowed"


def test_manual_dispatch_skips_external_origin_allowlist() -> None:
    with (
        patch("app.tasks.autonomous.pickup_guards.get_allowed_external_origins", return_value=["agent-hub-context-maintenance"]),
        patch("app.tasks.autonomous.pickup_guards.check_agent_hub_execution_permission", return_value=None),
        patch("app.tasks.autonomous.pickup_guards.check_work_pickup_enabled", return_value=None),
        patch("app.tasks.autonomous.pickup_guards.check_system_health", return_value=None),
        patch("app.tasks.autonomous.pickup_guards.check_concurrency_limit", return_value=None),
        patch("app.tasks.autonomous.pickup_guards.check_max_tasks_per_day", return_value=None),
        patch("app.tasks.autonomous.pickup_guards.check_cooldown_period", return_value=None),
    ):
        assert validate_autonomous_dispatch(
            "summitflow",
            require_enabled=False,
            enforce_external_origin=False,
        ) is None


class _FakeClient:
    """Stands in for the Agent Hub SDK client and records each call."""

    def __init__(self, permission: dict | Exception | None = None, sessions: list[dict] | None = None) -> None:
        self.permission = permission
        self.sessions = sessions or []
        self.calls: list[tuple] = []
        self.factory_kwargs: dict = {}

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_execution_permission(self, project_id: str) -> dict:
        self.calls.append(("get_execution_permission", project_id))
        if isinstance(self.permission, Exception):
            raise self.permission
        return dict(self.permission or {})

    def list_sessions(self, project_id: str, status: str, **kwargs: object) -> SessionListResponse:
        self.calls.append(("list_sessions", project_id, status, kwargs))
        return SessionListResponse.model_validate({
            "sessions": [_session(**overrides) for overrides in self.sessions],
            "total": len(self.sessions), "page": 1, "page_size": 100,
        })


def _session(**overrides: object) -> dict:
    return {
        "id": f"s-{id(overrides)}", "project_id": "agent-hub", "provider": "codex", "model": "m",
        "status": "active", "message_count": 0,
        "created_at": "2026-10-09T00:00:00Z", "updated_at": "2026-10-09T00:00:00Z", **overrides,
    }


def _sdk(fake: _FakeClient):
    def factory(**kwargs: object) -> _FakeClient:
        fake.factory_kwargs = kwargs
        return fake

    return patch("app.tasks.autonomous.pickup_guards.get_sync_client", side_effect=factory)


class TestCheckAutonomousEnabled:
    """Tests for check_autonomous_enabled permission tier validation."""

    def test_legacy_write_tier_alias_permits_execution(self) -> None:
        """Legacy write tier is treated as full during rollout."""
        with _sdk(_FakeClient({"allowed": True, "permission_tier": "write"})):
            assert check_autonomous_enabled("proj") is None

    def test_reads_the_project_permission_as_the_pipeline(self) -> None:
        """The SDK read names the project and attributes the call to sf-pipeline."""
        fake = _FakeClient({"allowed": True, "permission_tier": "full"})
        with _sdk(fake):
            check_autonomous_enabled("monkey-fight")
        assert fake.calls == [("get_execution_permission", "monkey-fight")]
        assert fake.factory_kwargs["request_source"] == "sf-pipeline"

    def test_allowed_full_tier(self) -> None:
        """Full tier permits autonomous execution."""
        with _sdk(_FakeClient({"allowed": True, "permission_tier": "full"})):
            assert check_autonomous_enabled("proj") is None

    def test_read_tier_blocked(self) -> None:
        """Read-only tier blocks autonomous execution."""
        with _sdk(_FakeClient({"allowed": True, "permission_tier": "read"})):
            result = check_autonomous_enabled("proj")
        assert result is not None
        assert result["status"] == "disabled"
        assert "read" in result["reason"]

    def test_off_tier_blocked(self) -> None:
        """Off tier blocks autonomous execution (even if API says allowed)."""
        with _sdk(_FakeClient({"allowed": True, "permission_tier": "off"})):
            result = check_autonomous_enabled("proj")
        assert result is not None
        assert result["status"] == "disabled"

    def test_not_allowed_returns_disabled(self) -> None:
        """API returning allowed=false blocks dispatch."""
        with _sdk(_FakeClient({"allowed": False, "reason": "auto_exec_disabled"})):
            result = check_autonomous_enabled("proj")
        assert result is not None
        assert result["reason"] == "auto_exec_disabled"

    def test_unreachable_returns_disabled(self) -> None:
        """Network failure blocks dispatch."""
        with _sdk(_FakeClient(ConnectionError("down"))):
            result = check_autonomous_enabled("proj")
        assert result is not None
        assert "unreachable" in result["reason"]


class TestCheckAllowedTaskType:
    """Tests for autonomous task type guard."""

    @patch(
        "app.tasks.autonomous.pickup_guards.agent_configs.get_allowed_task_types",
        return_value=["feature", "bug", "task", "refactor", "debt", "regression"],
    )
    def test_ready_ranked_generic_task_type_is_allowed(self, _mock_allowed: MagicMock) -> None:
        assert check_allowed_task_type("agent-hub", "task") is None


class TestCheckWorkPickupEnabled:
    @patch("app.tasks.autonomous.pickup_guards.agent_configs.get_agent_config")
    def test_disabled_work_pickup_blocks_dispatch(self, mock_config: MagicMock) -> None:
        mock_config.return_value = {"work_pickup_enabled": False}

        result = check_work_pickup_enabled("agent-hub")

        assert result == {"status": "disabled", "reason": "work_pickup_disabled"}

    @patch("app.tasks.autonomous.pickup_guards.agent_configs.get_agent_config")
    def test_enabled_work_pickup_allows_dispatch(self, mock_config: MagicMock) -> None:
        mock_config.return_value = {"work_pickup_enabled": True}

        assert check_work_pickup_enabled("agent-hub") is None


def _mock_healthy_infra() -> tuple:
    """Return (mock_get_conn, mock_redis) configured for healthy postgres+redis."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = lambda s, *a: None
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = lambda s, *a: None
    mock_redis_client = MagicMock()
    mock_redis_client.ping.return_value = True
    return mock_conn, mock_redis_client


class TestCheckSystemHealth:
    """Tests for check_system_health backend HTTP check."""

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_backend_healthy_via_http(
        self, mock_get: MagicMock, mock_redis_from_url: MagicMock, mock_get_conn: MagicMock
    ) -> None:
        """Backend health check uses HTTP instead of systemctl."""
        mock_conn, mock_redis_client = _mock_healthy_infra()
        mock_get_conn.return_value = mock_conn
        mock_redis_from_url.return_value = mock_redis_client

        mock_get.return_value = MagicMock(status_code=200)

        result = check_system_health("proj")
        assert result is None  # all healthy

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_backend_unhealthy_via_http(
        self, mock_get: MagicMock, mock_redis_from_url: MagicMock, mock_get_conn: MagicMock
    ) -> None:
        """Backend returns non-200 marks as unhealthy."""
        mock_conn, mock_redis_client = _mock_healthy_infra()
        mock_get_conn.return_value = mock_conn
        mock_redis_from_url.return_value = mock_redis_client

        mock_get.return_value = MagicMock(status_code=503)

        result = check_system_health("proj")
        assert result is not None
        assert "backend" in result["failing_services"]

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_backend_unavailable_does_not_block(
        self, mock_get: MagicMock, mock_redis_from_url: MagicMock, mock_get_conn: MagicMock
    ) -> None:
        """Unreachable health endpoint treated as unknown, not unhealthy."""
        mock_conn, mock_redis_client = _mock_healthy_infra()
        mock_get_conn.return_value = mock_conn
        mock_redis_from_url.return_value = mock_redis_client

        mock_get.side_effect = ConnectionError("refused")

        result = check_system_health("proj")
        assert result is None  # should not block dispatch


class TestConcurrencySnapshot:
    """Tests for project concurrency accounting."""

    @patch("app.tasks.autonomous.pickup_guards.task_store.get_task", return_value=None)
    def test_active_session_count_excludes_current_task_and_transcript_sync(self, _mock_get_task: MagicMock) -> None:
        fake = _FakeClient(sessions=[
            {"external_id": "task-current", "request_source": "summitflow"},
            {"external_id": None, "request_source": "codex-transcript-sync"},
            {"request_source": "summitflow", "live_activity": {"lifecycle_state": "dead_candidate", "health": "stalled"}},
            {"request_source": "summitflow", "live_activity": {"lifecycle_state": "reapable", "health": "stalled"}},
            {"request_source": "summitflow", "live_activity": {"lifecycle_state": "quiet", "health": "completed"}},
            {"external_id": "task-other", "request_source": "summitflow",
             "live_activity": {"lifecycle_state": "quiet", "health": "quiet"}},
            {"request_source": "summitflow", "live_activity": {"lifecycle_state": "quiet", "health": "active"}},
        ])
        with _sdk(fake):
            assert count_active_agent_hub_sessions("agent-hub", exclude_task_id="task-current") == 1
        assert fake.calls == [("list_sessions", "agent-hub", "active", {"page_size": 100})]

    @patch("app.tasks.autonomous.pickup_guards.task_store.get_task")
    def test_active_session_for_terminal_task_does_not_consume_capacity(self, mock_get_task: MagicMock) -> None:
        fake = _FakeClient(sessions=[{
            "external_id": "task-finished", "request_source": "summitflow",
            "live_activity": {"lifecycle_state": "quiet", "health": "quiet"},
        }])
        mock_get_task.return_value = {"id": "task-finished", "project_id": "agent-hub", "status": "failed"}
        with _sdk(fake):
            assert count_active_agent_hub_sessions("agent-hub") == 0

    @patch("app.tasks.autonomous.pickup_guards.count_active_agent_hub_sessions", return_value=0)
    @patch("app.tasks.autonomous.pickup_guards.task_store.count_running_tasks", return_value=0)
    @patch("app.tasks.autonomous.pickup_guards.agent_configs.get_agent_config", return_value={"autonomous_max_concurrent": 1})
    def test_can_exclude_current_dispatch_task_from_running_count(
        self,
        _mock_config: MagicMock,
        mock_count_running: MagicMock,
        _mock_sessions: MagicMock,
    ) -> None:
        snapshot = get_concurrency_snapshot("agent-hub", exclude_task_id="task-177f0dec")

        mock_count_running.assert_called_once_with("agent-hub", exclude_task_id="task-177f0dec")
        assert snapshot["running_count"] == 0
        assert snapshot["remaining_capacity"] == 1


class TestValidateAutonomousDispatch:
    @patch("app.tasks.autonomous.pickup_guards.check_agent_hub_execution_permission", return_value=None)
    @patch(
        "app.tasks.autonomous.pickup_guards.check_work_pickup_enabled",
        return_value={"status": "disabled", "reason": "work_pickup_disabled"},
    )
    def test_disabled_work_pickup_blocks_even_manual_guard(
        self,
        mock_work_pickup: MagicMock,
        _mock_permission: MagicMock,
    ) -> None:
        result = validate_autonomous_dispatch("agent-hub", require_enabled=False)

        assert result == {"status": "disabled", "reason": "work_pickup_disabled"}
        mock_work_pickup.assert_called_once_with("agent-hub")

    @patch("app.tasks.autonomous.pickup_guards.check_cooldown_period", return_value=None)
    @patch("app.tasks.autonomous.pickup_guards.check_max_tasks_per_day", return_value=None)
    @patch("app.tasks.autonomous.pickup_guards.check_concurrency_limit")
    @patch("app.tasks.autonomous.pickup_guards.check_system_health", return_value=None)
    @patch("app.tasks.autonomous.pickup_guards.check_work_pickup_enabled", return_value=None)
    @patch("app.tasks.autonomous.pickup_guards.check_agent_hub_execution_permission", return_value=None)
    def test_skip_concurrency_leaves_queue_request_eligible(
        self,
        _mock_permission: MagicMock,
        _mock_work_pickup: MagicMock,
        _mock_health: MagicMock,
        mock_concurrency: MagicMock,
        _mock_daily: MagicMock,
        _mock_cooldown: MagicMock,
    ) -> None:
        mock_concurrency.return_value = {"status": "concurrency_limit"}

        result = validate_autonomous_dispatch("agent-hub", skip_concurrency=True)

        assert result is None
        mock_concurrency.assert_not_called()
