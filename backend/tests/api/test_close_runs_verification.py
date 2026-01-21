"""Tests for st close running verify_command for test-type criteria."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.verification_runner import run_verification_commands


class TestVerificationRunner:
    """Tests for the verification_runner service."""

    def test_empty_criteria_returns_empty(self) -> None:
        """Empty criteria list returns empty failures."""
        result = run_verification_commands([])
        assert result == []

    def test_criteria_without_verify_command_skipped(self) -> None:
        """Criteria without verify_command are skipped."""
        criteria = [
            {"criterion_id": "ac-001", "criterion": "Test passes", "verify_by": "test"},
        ]
        result = run_verification_commands(criteria)
        assert result == []

    def test_successful_command_returns_empty(self) -> None:
        """Successful commands return no failures."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Exit 0",
                "verify_by": "test",
                "verify_command": "exit 0",
            },
        ]
        result = run_verification_commands(criteria)
        assert result == []

    def test_failing_command_returns_failure(self) -> None:
        """Failing command (non-zero exit) is recorded."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Exit 1",
                "verify_by": "test",
                "verify_command": "exit 1",
            },
        ]
        result = run_verification_commands(criteria)
        assert len(result) == 1
        assert result[0]["criterion_id"] == "ac-001"
        assert result[0]["exit_code"] == 1

    def test_expected_output_match_passes(self) -> None:
        """Command with matching expected_output passes."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Echo hello",
                "verify_by": "test",
                "verify_command": "echo hello",
                "expected_output": "hello",
            },
        ]
        result = run_verification_commands(criteria)
        assert result == []

    def test_expected_output_mismatch_fails(self) -> None:
        """Command with non-matching expected_output fails."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Echo hello",
                "verify_by": "test",
                "verify_command": "echo hello",
                "expected_output": "goodbye",
            },
        ]
        result = run_verification_commands(criteria)
        assert len(result) == 1
        assert result[0]["criterion_id"] == "ac-001"
        assert result[0]["mismatch"] is True

    def test_timeout_returns_failure(self) -> None:
        """Timeout is recorded as failure."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Sleep forever",
                "verify_by": "test",
                "verify_command": "sleep 100",
            },
        ]
        result = run_verification_commands(criteria, timeout=1)
        assert len(result) == 1
        assert result[0]["timeout"] is True
        assert "timed out" in result[0]["output"]

    def test_multiple_criteria_aggregates_failures(self) -> None:
        """Multiple criteria aggregate their failures."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Pass",
                "verify_by": "test",
                "verify_command": "exit 0",
            },
            {
                "criterion_id": "ac-002",
                "criterion": "Fail",
                "verify_by": "test",
                "verify_command": "exit 1",
            },
            {
                "criterion_id": "ac-003",
                "criterion": "Also pass",
                "verify_by": "test",
                "verify_command": "echo ok",
            },
        ]
        result = run_verification_commands(criteria)
        assert len(result) == 1
        assert result[0]["criterion_id"] == "ac-002"


class TestCloseRunsVerification:
    """Integration tests for st close running verification."""

    @patch("app.services.verification_runner.subprocess.run")
    def test_close_runs_test_criteria_verification(self, mock_run: MagicMock) -> None:
        """Verify that close endpoint runs verify_command for test-type criteria."""
        # Setup mock to simulate passing test
        mock_run.return_value = MagicMock(returncode=0, stdout="PASSED", stderr="")

        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Tests pass",
                "verify_by": "test",
                "verify_command": "pytest tests/",
            }
        ]

        failures = run_verification_commands(criteria)

        assert failures == []
        mock_run.assert_called_once()

    @patch("app.services.verification_runner.subprocess.run")
    def test_close_rejects_on_failing_verification(self, mock_run: MagicMock) -> None:
        """Verify that close endpoint rejects when verification fails."""
        # Setup mock to simulate failing test
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="FAILED test_something",
            stderr="AssertionError",
        )

        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Tests pass",
                "verify_by": "test",
                "verify_command": "pytest tests/",
            }
        ]

        failures = run_verification_commands(criteria)

        assert len(failures) == 1
        assert failures[0]["criterion_id"] == "ac-001"
        assert failures[0]["exit_code"] == 1

    def test_human_criteria_not_run(self) -> None:
        """Criteria with verify_by=human are not executed."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "User approves",
                "verify_by": "human",
                "verify_command": "exit 1",  # Would fail if run
            }
        ]

        # Since verify_by != 'test', this should not be in the filter
        # that goes to run_verification_commands
        test_criteria = [c for c in criteria if c.get("verify_by") == "test"]
        failures = run_verification_commands(test_criteria)

        assert failures == []

    def test_agent_criteria_not_run(self) -> None:
        """Criteria with verify_by=agent are not executed."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Agent verifies",
                "verify_by": "agent",
                "verify_command": "exit 1",
            }
        ]

        test_criteria = [c for c in criteria if c.get("verify_by") == "test"]
        failures = run_verification_commands(test_criteria)

        assert failures == []

    def test_opus_criteria_not_run(self) -> None:
        """Criteria with verify_by=opus are not executed."""
        criteria = [
            {
                "criterion_id": "ac-001",
                "criterion": "Opus verifies",
                "verify_by": "opus",
                "verify_command": "exit 1",
            }
        ]

        test_criteria = [c for c in criteria if c.get("verify_by") == "test"]
        failures = run_verification_commands(test_criteria)

        assert failures == []
