"""Unit tests for systemd journal monitor.

Tests parsing of journalctl output and error deduplication.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import pytest
from pytest_mock import MockerFixture

from app.services.self_healing.monitor import (
    ERROR_PRIORITY_THRESHOLD,
    PRIORITY_CRIT,
    PRIORITY_DEBUG,
    PRIORITY_ERR,
    PRIORITY_INFO,
    PRIORITY_WARNING,
    JournalError,
    SystemdMonitor,
    compute_error_hash,
)


class TestComputeErrorHash:
    """Tests for error hash computation."""

    @pytest.mark.parametrize(
        "unit1,msg1,unit2,msg2,should_equal",
        [
            (
                "summitflow-backend",
                "Connection refused",
                "summitflow-backend",
                "Connection refused",
                True,
            ),
            ("summitflow-backend", "Error", "summitflow-frontend", "Error", False),
            ("unit", "Error A", "unit", "Error B", False),
            ("unit", "ERROR MESSAGE", "unit", "error message", True),  # Case insensitive
        ],
        ids=["stable_hash", "different_units", "different_messages", "case_insensitive"],
    )
    def test_hash_comparison(
        self, unit1: str, msg1: str, unit2: str, msg2: str, should_equal: bool
    ) -> None:
        """Test hash comparisons for various inputs."""
        hash1 = compute_error_hash(unit1, msg1)
        hash2 = compute_error_hash(unit2, msg2)
        if should_equal:
            assert hash1 == hash2
        else:
            assert hash1 != hash2

    def test_hash_length(self) -> None:
        """Hash is 16 characters."""
        hash_val = compute_error_hash("unit", "message")
        assert len(hash_val) == 16


class TestSystemdMonitor:
    """Tests for SystemdMonitor class."""

    @pytest.fixture
    def monitor(self) -> SystemdMonitor:
        """Create a monitor instance."""
        return SystemdMonitor(unit_pattern="summitflow-*", since="5 minutes ago")

    @pytest.mark.parametrize(
        "priority,expected_parsed",
        [
            (PRIORITY_ERR, True),
            (PRIORITY_CRIT, True),
            (PRIORITY_INFO, False),
            (PRIORITY_WARNING, False),
            (PRIORITY_DEBUG, False),
        ],
        ids=["error", "critical", "info", "warning", "debug"],
    )
    def test_parse_entry_by_priority(
        self, monitor: SystemdMonitor, priority: int, expected_parsed: bool
    ) -> None:
        """Test entry parsing by priority level."""
        entry = {
            "PRIORITY": str(priority),
            "_SYSTEMD_UNIT": "summitflow-backend.service",
            "MESSAGE": "Test message",
        }

        result = monitor._parse_entry(entry)

        if expected_parsed:
            assert result is not None
            assert result.priority == priority
        else:
            assert result is None

    def test_parse_entry_empty_message_skipped(self, monitor: SystemdMonitor) -> None:
        """Entries with empty message are skipped."""
        entry = {
            "PRIORITY": str(PRIORITY_ERR),
            "_SYSTEMD_UNIT": "summitflow-backend.service",
            "MESSAGE": "",
        }

        result = monitor._parse_entry(entry)

        assert result is None

    def test_parse_entry_uses_unit_fallback(self, monitor: SystemdMonitor) -> None:
        """Falls back to UNIT if _SYSTEMD_UNIT not present."""
        entry = {
            "PRIORITY": str(PRIORITY_ERR),
            "UNIT": "summitflow-backend.service",
            "MESSAGE": "Error",
        }

        result = monitor._parse_entry(entry)

        assert result is not None
        assert result.unit == "summitflow-backend.service"

    def test_parse_json_output(self, monitor: SystemdMonitor) -> None:
        """Parses multi-line JSON output correctly."""
        entries = [
            {
                "PRIORITY": str(PRIORITY_ERR),
                "_SYSTEMD_UNIT": "summitflow-backend.service",
                "MESSAGE": "Error 1",
            },
            {
                "PRIORITY": str(PRIORITY_INFO),
                "_SYSTEMD_UNIT": "summitflow-backend.service",
                "MESSAGE": "Info message",
            },
            {
                "PRIORITY": str(PRIORITY_CRIT),
                "_SYSTEMD_UNIT": "summitflow-frontend.service",
                "MESSAGE": "Error 2",
            },
        ]
        output = "\n".join(json.dumps(e) for e in entries)

        result = monitor._parse_json_output(output)

        # Only 2 errors (INFO skipped)
        assert len(result) == 2
        assert result[0].message == "Error 1"
        assert result[1].message == "Error 2"

    @pytest.mark.parametrize(
        "output,expected_count",
        [
            ("", 0),
            ('{"PRIORITY": "3", "MESSAGE": "Valid"}\nnot json\n', 1),
        ],
        ids=["empty_output", "skip_invalid_json"],
    )
    def test_parse_json_output_edge_cases(
        self, monitor: SystemdMonitor, output: str, expected_count: int
    ) -> None:
        """Test edge cases for JSON output parsing."""
        result = monitor._parse_json_output(output)
        assert len(result) == expected_count

    def test_get_new_errors_deduplicates(
        self, monitor: SystemdMonitor, mocker: MockerFixture
    ) -> None:
        """Duplicate errors are filtered out."""
        error1 = JournalError(
            unit="test.service",
            message="Error A",
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="hash1",
        )
        error2 = JournalError(
            unit="test.service",
            message="Error A",
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="hash1",  # Same hash
        )
        error3 = JournalError(
            unit="test.service",
            message="Error B",
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="hash2",
        )

        mocker.patch.object(monitor, "parse_journal", return_value=[error1, error2, error3])
        result = monitor.get_new_errors()

        # Only 2 unique errors
        assert len(result) == 2
        assert {e.error_hash for e in result} == {"hash1", "hash2"}

    def test_get_new_errors_remembers_seen(
        self, monitor: SystemdMonitor, mocker: MockerFixture
    ) -> None:
        """Previously seen errors are not returned again."""
        error = JournalError(
            unit="test.service",
            message="Error",
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="hash1",
        )

        mocker.patch.object(monitor, "parse_journal", return_value=[error])
        result1 = monitor.get_new_errors()
        result2 = monitor.get_new_errors()

        assert len(result1) == 1
        assert len(result2) == 0  # Already seen

    def test_mark_seen(self, monitor: SystemdMonitor, mocker: MockerFixture) -> None:
        """mark_seen adds hash to seen set."""
        monitor.mark_seen("existing_hash")

        error = JournalError(
            unit="test.service",
            message="Error",
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="existing_hash",
        )

        mocker.patch.object(monitor, "parse_journal", return_value=[error])
        result = monitor.get_new_errors()

        assert len(result) == 0  # Marked as already seen

    def test_clear_seen(self, monitor: SystemdMonitor) -> None:
        """clear_seen resets the seen set."""
        monitor._seen_hashes.add("hash1")
        monitor._seen_hashes.add("hash2")

        monitor.clear_seen()

        assert len(monitor._seen_hashes) == 0

    def test_parse_journal_calls_journalctl(
        self, monitor: SystemdMonitor, mocker: MockerFixture
    ) -> None:
        """parse_journal calls journalctl with correct args."""
        mock_run = mocker.patch("app.services.self_healing.monitor.subprocess.run")
        mock_run.return_value = mocker.MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        monitor.parse_journal()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "journalctl" in call_args
        assert "--user" in call_args
        assert "-u" in call_args
        assert "summitflow-*" in call_args
        assert "--since" in call_args
        assert "5 minutes ago" in call_args
        assert "-o" in call_args
        assert "json" in call_args

    @pytest.mark.parametrize(
        "error_type,side_effect",
        [
            ("failure", None),  # returncode=1
            ("timeout", subprocess.TimeoutExpired("journalctl", 30)),
            ("not_found", FileNotFoundError()),
        ],
        ids=["command_failure", "timeout", "not_found"],
    )
    def test_parse_journal_handles_errors(
        self,
        monitor: SystemdMonitor,
        mocker: MockerFixture,
        error_type: str,
        side_effect: Exception | None,
    ) -> None:
        """parse_journal handles various errors gracefully."""
        mock_run = mocker.patch("app.services.self_healing.monitor.subprocess.run")

        if side_effect:
            mock_run.side_effect = side_effect
        else:
            mock_run.return_value = mocker.MagicMock(
                returncode=1,
                stdout="",
                stderr="No such unit",
            )

        result = monitor.parse_journal()

        assert result == []


class TestPriorityConstants:
    """Tests for priority constant values."""

    def test_error_threshold(self) -> None:
        """Error threshold is at ERROR level."""
        assert ERROR_PRIORITY_THRESHOLD == PRIORITY_ERR
        assert ERROR_PRIORITY_THRESHOLD == 3

    def test_priority_ordering(self) -> None:
        """Priority levels are correctly ordered (lower = more severe)."""
        assert PRIORITY_CRIT < PRIORITY_ERR
        assert PRIORITY_ERR < PRIORITY_WARNING
        assert PRIORITY_WARNING < PRIORITY_INFO
        assert PRIORITY_INFO < PRIORITY_DEBUG
