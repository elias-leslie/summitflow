"""Unit tests for systemd journal monitor.

Tests parsing of journalctl output and error deduplication.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

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

    def test_hash_is_stable(self) -> None:
        """Same input produces same hash."""
        hash1 = compute_error_hash("summitflow-backend", "Connection refused")
        hash2 = compute_error_hash("summitflow-backend", "Connection refused")
        assert hash1 == hash2

    def test_different_units_different_hashes(self) -> None:
        """Different units produce different hashes."""
        hash1 = compute_error_hash("summitflow-backend", "Error")
        hash2 = compute_error_hash("summitflow-frontend", "Error")
        assert hash1 != hash2

    def test_different_messages_different_hashes(self) -> None:
        """Different messages produce different hashes."""
        hash1 = compute_error_hash("unit", "Error A")
        hash2 = compute_error_hash("unit", "Error B")
        assert hash1 != hash2

    def test_hash_length(self) -> None:
        """Hash is 16 characters."""
        hash_val = compute_error_hash("unit", "message")
        assert len(hash_val) == 16

    def test_hash_case_insensitive(self) -> None:
        """Hash is case insensitive for message."""
        hash1 = compute_error_hash("unit", "ERROR MESSAGE")
        hash2 = compute_error_hash("unit", "error message")
        assert hash1 == hash2


class TestSystemdMonitor:
    """Tests for SystemdMonitor class."""

    @pytest.fixture
    def monitor(self) -> SystemdMonitor:
        """Create a monitor instance."""
        return SystemdMonitor(unit_pattern="summitflow-*", since="5 minutes ago")

    def test_parse_entry_error_priority(self, monitor: SystemdMonitor) -> None:
        """Error priority entries are parsed."""
        entry = {
            "PRIORITY": str(PRIORITY_ERR),
            "_SYSTEMD_UNIT": "summitflow-backend.service",
            "MESSAGE": "Database connection failed",
            "__REALTIME_TIMESTAMP": "1705600000000000",
        }

        result = monitor._parse_entry(entry)

        assert result is not None
        assert result.priority == PRIORITY_ERR
        assert result.unit == "summitflow-backend.service"
        assert result.message == "Database connection failed"

    def test_parse_entry_critical_priority(self, monitor: SystemdMonitor) -> None:
        """Critical priority entries are parsed."""
        entry = {
            "PRIORITY": str(PRIORITY_CRIT),
            "_SYSTEMD_UNIT": "summitflow-backend.service",
            "MESSAGE": "Fatal error",
        }

        result = monitor._parse_entry(entry)

        assert result is not None
        assert result.priority == PRIORITY_CRIT

    def test_parse_entry_info_priority_skipped(self, monitor: SystemdMonitor) -> None:
        """Info priority entries are skipped."""
        entry = {
            "PRIORITY": str(PRIORITY_INFO),
            "_SYSTEMD_UNIT": "summitflow-backend.service",
            "MESSAGE": "Server started",
        }

        result = monitor._parse_entry(entry)

        assert result is None

    def test_parse_entry_warning_priority_skipped(self, monitor: SystemdMonitor) -> None:
        """Warning priority entries are skipped (only errors and above)."""
        entry = {
            "PRIORITY": str(PRIORITY_WARNING),
            "_SYSTEMD_UNIT": "summitflow-backend.service",
            "MESSAGE": "Deprecation warning",
        }

        result = monitor._parse_entry(entry)

        assert result is None

    def test_parse_entry_debug_priority_skipped(self, monitor: SystemdMonitor) -> None:
        """Debug priority entries are skipped."""
        entry = {
            "PRIORITY": str(PRIORITY_DEBUG),
            "_SYSTEMD_UNIT": "summitflow-backend.service",
            "MESSAGE": "Debug info",
        }

        result = monitor._parse_entry(entry)

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

    def test_parse_json_output_handles_empty(self, monitor: SystemdMonitor) -> None:
        """Handles empty output gracefully."""
        result = monitor._parse_json_output("")
        assert result == []

    def test_parse_json_output_skips_invalid_json(self, monitor: SystemdMonitor) -> None:
        """Skips lines that aren't valid JSON."""
        output = '{"PRIORITY": "3", "MESSAGE": "Valid"}\nnot json\n'

        result = monitor._parse_json_output(output)

        assert len(result) == 1

    def test_get_new_errors_deduplicates(self, monitor: SystemdMonitor) -> None:
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

        with patch.object(monitor, "parse_journal", return_value=[error1, error2, error3]):
            result = monitor.get_new_errors()

        # Only 2 unique errors
        assert len(result) == 2
        assert {e.error_hash for e in result} == {"hash1", "hash2"}

    def test_get_new_errors_remembers_seen(self, monitor: SystemdMonitor) -> None:
        """Previously seen errors are not returned again."""
        error = JournalError(
            unit="test.service",
            message="Error",
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="hash1",
        )

        with patch.object(monitor, "parse_journal", return_value=[error]):
            result1 = monitor.get_new_errors()
            result2 = monitor.get_new_errors()

        assert len(result1) == 1
        assert len(result2) == 0  # Already seen

    def test_mark_seen(self, monitor: SystemdMonitor) -> None:
        """mark_seen adds hash to seen set."""
        monitor.mark_seen("existing_hash")

        error = JournalError(
            unit="test.service",
            message="Error",
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="existing_hash",
        )

        with patch.object(monitor, "parse_journal", return_value=[error]):
            result = monitor.get_new_errors()

        assert len(result) == 0  # Marked as already seen

    def test_clear_seen(self, monitor: SystemdMonitor) -> None:
        """clear_seen resets the seen set."""
        monitor._seen_hashes.add("hash1")
        monitor._seen_hashes.add("hash2")

        monitor.clear_seen()

        assert len(monitor._seen_hashes) == 0

    @patch("app.services.self_healing.monitor.subprocess.run")
    def test_parse_journal_calls_journalctl(
        self, mock_run: MagicMock, monitor: SystemdMonitor
    ) -> None:
        """parse_journal calls journalctl with correct args."""
        mock_run.return_value = MagicMock(
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

    @patch("app.services.self_healing.monitor.subprocess.run")
    def test_parse_journal_handles_failure(
        self, mock_run: MagicMock, monitor: SystemdMonitor
    ) -> None:
        """parse_journal handles journalctl failure gracefully."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="No such unit",
        )

        result = monitor.parse_journal()

        assert result == []

    @patch("app.services.self_healing.monitor.subprocess.run")
    def test_parse_journal_handles_timeout(
        self, mock_run: MagicMock, monitor: SystemdMonitor
    ) -> None:
        """parse_journal handles timeout gracefully."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("journalctl", 30)

        result = monitor.parse_journal()

        assert result == []

    @patch("app.services.self_healing.monitor.subprocess.run")
    def test_parse_journal_handles_not_found(
        self, mock_run: MagicMock, monitor: SystemdMonitor
    ) -> None:
        """parse_journal handles journalctl not found gracefully."""
        mock_run.side_effect = FileNotFoundError()

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
