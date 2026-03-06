"""Tests for shared CLI HTTP transport error helpers."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from typer import Exit

from cli.commands._http_errors import raise_connect_error, raise_timeout_error


class TestHttpErrorHelpers:
    """Tests for shared transport error helpers."""

    def test_raise_connect_error_includes_root_cause_and_hint(self) -> None:
        """Connect errors should include the nested cause and a next-step hint."""
        with patch("cli.commands._http_errors.output_error") as mock_output:
            error = httpx.ConnectError(
                "outer connect error",
                request=httpx.Request("GET", "http://agent-hub.local"),
            )
            error.__cause__ = OSError("Connection refused")

            with pytest.raises(Exit) as exc_info:
                raise_connect_error("Agent Hub", "http://agent-hub.local", error)

        assert exc_info.value.exit_code == 1
        messages = [call.args[0] for call in mock_output.call_args_list]
        assert messages[0] == "Cannot connect to Agent Hub at http://agent-hub.local: Connection refused"
        assert "reachable from this shell" in messages[1]

    def test_raise_timeout_error_includes_timeout_and_hint(self) -> None:
        """Timeout errors should report timeout seconds and a retry hint."""
        with patch("cli.commands._http_errors.output_error") as mock_output:
            error = httpx.ReadTimeout(
                "read timed out",
                request=httpx.Request("GET", "http://agent-hub.local"),
            )

            with pytest.raises(Exit) as exc_info:
                raise_timeout_error("Agent Hub", "http://agent-hub.local", 30.0, error)

        assert exc_info.value.exit_code == 1
        messages = [call.args[0] for call in mock_output.call_args_list]
        assert messages[0] == "Request to Agent Hub at http://agent-hub.local timed out after 30s: read timed out"
        assert "retry with a larger timeout" in messages[1]
