"""Tests for verify_patterns storage layer."""

import pytest

from app.storage.verify_patterns import (
    get_pattern_stats,
    get_suggested_patterns,
    normalize_pattern,
    record_outcome,
)


class TestNormalizePattern:
    """Tests for pattern normalization."""

    def test_normalize_task_ids(self):
        """Task IDs are replaced with task-ID."""
        cmd = "rg 'test' backend/tasks/task-abc12345/plan.json"
        result = normalize_pattern(cmd)
        assert "task-ID" in result
        assert "task-abc12345" not in result

    def test_normalize_home_paths(self):
        """Home directory paths are replaced with ~."""
        cmd = "/home/kasadis/summitflow/scripts/test.sh"
        result = normalize_pattern(cmd)
        assert "~" in result
        assert "/home/kasadis" not in result

    def test_normalize_ports(self):
        """Port numbers are replaced with PORT."""
        cmd = "curl http://localhost:8001/health"
        result = normalize_pattern(cmd)
        assert "localhost:PORT" in result
        assert "8001" not in result

    def test_normalize_frontend_ports(self):
        """Frontend ports (300X) are also normalized."""
        cmd = "curl http://localhost:3001/api/test"
        result = normalize_pattern(cmd)
        assert "localhost:PORT" in result
        assert "3001" not in result


class TestRecordOutcome:
    """Tests for recording pattern outcomes."""

    def test_record_outcome_success(self):
        """Recording a success creates/updates pattern."""
        result = record_outcome(
            command="echo 'hello_world'",
            success=True,
            duration_ms=100,
            exit_code=0,
        )
        assert result["success_count"] >= 1
        assert result["pattern_type"] == "other"

    def test_record_outcome_failure(self):
        """Recording a failure updates fail count."""
        result = record_outcome(
            command="echo 'test_failure'",
            success=False,
            duration_ms=50,
            exit_code=1,
        )
        assert result["fail_count"] >= 1

    def test_record_outcome_detects_deploy_type(self):
        """Deploy commands are categorized correctly."""
        result = record_outcome(
            command="./scripts/rebuild.sh --backend",
            success=True,
            duration_ms=2000,
        )
        assert result["pattern_type"] == "deploy"

    def test_record_outcome_detects_curl_type(self):
        """Curl commands are categorized correctly."""
        result = record_outcome(
            command="curl -sf http://localhost:8001/health",
            success=True,
            duration_ms=100,
        )
        assert result["pattern_type"] == "curl"

    def test_record_outcome_detects_grep_type(self):
        """Grep/rg commands are categorized correctly."""
        result = record_outcome(
            command="rg 'pattern' backend/",
            success=True,
            duration_ms=50,
        )
        assert result["pattern_type"] == "grep"


class TestGetPatternStats:
    """Tests for getting pattern statistics."""

    def test_get_pattern_stats_unknown(self):
        """Unknown patterns return default stats."""
        stats = get_pattern_stats("some_completely_unique_command_xyz123")
        assert stats["found"] is False
        assert stats["total_runs"] == 0
        assert stats["success_rate"] is None

    def test_get_pattern_stats_after_record(self):
        """Stats reflect recorded outcomes."""
        # Record some outcomes first
        record_outcome("echo 'stats_test_cmd'", success=True, duration_ms=100)
        record_outcome("echo 'stats_test_cmd'", success=True, duration_ms=100)
        record_outcome("echo 'stats_test_cmd'", success=False, duration_ms=100)

        stats = get_pattern_stats("echo 'stats_test_cmd'")
        assert stats["found"] is True
        assert stats["total_runs"] >= 3
        assert stats["success_rate"] is not None


class TestGetSuggestedPatterns:
    """Tests for getting suggested patterns."""

    def test_get_suggested_patterns_empty_type(self):
        """Returns empty list for unknown type."""
        patterns = get_suggested_patterns("nonexistent_type")
        assert isinstance(patterns, list)

    def test_get_suggested_patterns_respects_limit(self):
        """Respects the limit parameter."""
        patterns = get_suggested_patterns("deploy", limit=1)
        assert len(patterns) <= 1
