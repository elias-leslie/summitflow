"""Tests for feedback CLI argument validation."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.feedback import app

runner = CliRunner()


class TestFeedbackLimitValidation:
    """Feedback list/search should reject out-of-range limits locally."""

    def test_list_rejects_limit_above_api_cap(self) -> None:
        result = runner.invoke(app, ["list", "--limit", "201"])

        assert result.exit_code == 1
        assert "Limit must be between 1 and 200." in result.output

    def test_search_rejects_limit_above_api_cap(self) -> None:
        result = runner.invoke(app, ["search", "audit", "--limit", "201"])

        assert result.exit_code == 1
        assert "Limit must be between 1 and 200." in result.output

    def test_list_accepts_limit_at_api_cap(self) -> None:
        with patch("cli.commands.feedback.list_impl") as mock_list_impl:
            result = runner.invoke(app, ["list", "--limit", "200"])

        assert result.exit_code == 0
        mock_list_impl.assert_called_once()

    def test_search_accepts_limit_at_api_cap(self) -> None:
        with patch("cli.commands.feedback.search_impl") as mock_search_impl:
            result = runner.invoke(app, ["search", "audit", "--limit", "200"])

        assert result.exit_code == 0
        mock_search_impl.assert_called_once()
