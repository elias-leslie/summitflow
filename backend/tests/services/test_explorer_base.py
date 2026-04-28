"""Tests for Explorer base scanner service."""

import pytest

from app.services.explorer import (
    BaseScanner,
    ExplorerEntryCreate,
    calculate_health,
    get_entries,
    get_stats,
)
from app.services.explorer.health import (
    calculate_bloat_level,
    calculate_staleness,
    endpoint_health_from_status,
    task_health_from_stats,
)


class TestCalculateHealth:
    """Tests for calculate_health function."""

    def test_healthy_when_no_issues(self) -> None:
        """Returns healthy when all metrics are good."""
        assert calculate_health(error_count=0, warning_count=0) == "healthy"

    def test_error_when_errors_present(self) -> None:
        """Returns error when error_count > 0."""
        assert calculate_health(error_count=1) == "error"
        assert calculate_health(error_count=5) == "error"

    def test_warning_when_warnings_present(self) -> None:
        """Returns warning when warning_count > 0."""
        assert calculate_health(warning_count=1) == "warning"

    def test_warning_when_stale(self) -> None:
        """Returns warning when content is stale."""
        assert calculate_health(last_modified_days=31) == "warning"
        assert calculate_health(last_modified_days=30) == "healthy"

    def test_warning_when_incomplete(self) -> None:
        """Returns warning when completeness is low."""
        assert calculate_health(completeness_pct=79) == "warning"
        assert calculate_health(completeness_pct=80) == "healthy"

    def test_warning_when_low_success_rate(self) -> None:
        """Returns warning when success rate is low."""
        assert calculate_health(success_rate_pct=94) == "warning"
        assert calculate_health(success_rate_pct=95) == "healthy"

    def test_error_takes_priority(self) -> None:
        """Error status takes priority over warnings."""
        assert calculate_health(error_count=1, warning_count=5, last_modified_days=100) == "error"


class TestCalculateStaleness:
    """Tests for calculate_staleness function."""

    def test_unknown_when_no_timestamp(self) -> None:
        """Returns unknown when no timestamp provided."""
        assert calculate_staleness(None) == "unknown"

    def test_stale_detection(self) -> None:
        """Detects stale content correctly."""
        from datetime import UTC, datetime, timedelta

        old = datetime.now(UTC) - timedelta(days=31)
        assert calculate_staleness(old) == "stale"

        recent = datetime.now(UTC) - timedelta(days=5)
        assert calculate_staleness(recent) == "fresh"


class TestCalculateBloatLevel:
    """Tests for calculate_bloat_level function."""

    def test_unknown_when_no_data(self) -> None:
        """Returns unknown when no metrics provided."""
        assert calculate_bloat_level() == "unknown"

    def test_ok_within_thresholds(self) -> None:
        """Returns ok when within thresholds."""
        assert calculate_bloat_level(size_bytes=50000) == "ok"
        assert calculate_bloat_level(lines_of_code=500) == "ok"

    def test_warning_over_threshold(self) -> None:
        """Returns warning when over threshold."""
        assert calculate_bloat_level(size_bytes=150000) == "warning"
        assert calculate_bloat_level(lines_of_code=1500) == "warning"

    def test_critical_when_multiple_issues(self) -> None:
        """Returns critical when multiple thresholds exceeded severely."""
        assert (
            calculate_bloat_level(size_bytes=600000, lines_of_code=4000, file_count=200)
            == "critical"
        )


class TestEndpointHealth:
    """Tests for endpoint_health_from_status function."""

    def test_unknown_when_no_status(self) -> None:
        """Returns unknown when no HTTP status."""
        assert endpoint_health_from_status(None) == "unknown"

    def test_healthy_for_200(self) -> None:
        """Returns healthy for 200 status."""
        assert endpoint_health_from_status(200) == "healthy"

    def test_error_for_500(self) -> None:
        """Returns error for server errors."""
        assert endpoint_health_from_status(500) == "error"
        assert endpoint_health_from_status(503) == "error"

    def test_error_for_client_errors(self) -> None:
        """Returns error for client errors except 404."""
        assert endpoint_health_from_status(400) == "error"
        assert endpoint_health_from_status(403) == "error"

    def test_warning_for_404(self) -> None:
        """Returns warning for 404."""
        assert endpoint_health_from_status(404) == "warning"

    def test_error_for_console_errors(self) -> None:
        """Returns error when console errors present."""
        assert endpoint_health_from_status(200, console_errors=1) == "error"

    def test_warning_for_slow_response(self) -> None:
        """Returns warning for slow responses."""
        assert endpoint_health_from_status(200, response_time_ms=5000) == "warning"


class TestTaskHealth:
    """Tests for task_health_from_stats function."""

    def test_unknown_when_no_runs(self) -> None:
        """Returns unknown when no executions."""
        assert task_health_from_stats(0, 0) == "unknown"

    def test_healthy_for_high_success_rate(self) -> None:
        """Returns healthy for high success rate."""
        assert task_health_from_stats(100, 0) == "healthy"
        assert task_health_from_stats(96, 4) == "healthy"

    def test_warning_for_moderate_success_rate(self) -> None:
        """Returns warning for moderate success rate."""
        assert task_health_from_stats(90, 10) == "warning"

    def test_error_for_low_success_rate(self) -> None:
        """Returns error for low success rate."""
        assert task_health_from_stats(70, 30) == "error"


class TestBaseScanner:
    """Tests for BaseScanner class."""

    def test_abstract_scan_method(self) -> None:
        """Cannot instantiate BaseScanner directly."""
        with pytest.raises(TypeError):
            BaseScanner("test-project")

    def test_concrete_scanner_works(self) -> None:
        """Concrete scanner implementation works."""

        class TestScanner(BaseScanner):
            entry_type = "test"

            def scan(self) -> list[ExplorerEntryCreate]:
                return [
                    ExplorerEntryCreate(
                        path="test/file.py",
                        name="file.py",
                        health_status="healthy",
                        metadata={"test": True},
                    )
                ]

        scanner = TestScanner("portfolio-ai")
        entries = scanner.scan()
        assert len(entries) == 1
        assert entries[0].path == "test/file.py"


class TestPublicInterface:
    """Tests for public interface functions."""

    def test_get_entries_returns_list(self) -> None:
        """get_entries returns a list."""
        entries = get_entries("portfolio-ai", {"type": "file", "limit": 5})
        assert isinstance(entries, list)

    def test_get_stats_returns_dict(self) -> None:
        """get_stats returns expected structure."""
        stats = get_stats("portfolio-ai")
        assert "by_type" in stats
        assert "by_health" in stats
        assert "total" in stats
        assert isinstance(stats["total"], int)
