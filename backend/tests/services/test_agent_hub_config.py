"""Tests for shared Agent Hub header/config helpers."""

from __future__ import annotations

from unittest.mock import patch

from app.services import _agent_hub_config as config


def test_build_agent_hub_headers_uses_module_defaults() -> None:
    """Default helper output should reflect configured module credentials."""
    with (
        patch.object(config, "SUMMITFLOW_CLIENT_ID", "client-123"),
        patch.object(config, "SUMMITFLOW_REQUEST_SOURCE", "source-abc"),
    ):
        assert config.build_agent_hub_headers() == {
            "X-Client-Id": "client-123",
            "X-Request-Source": "source-abc",
        }


def test_build_agent_hub_headers_supports_overrides_and_extra_headers() -> None:
    """Callers can override request source and append extra headers."""
    with (
        patch.object(config, "SUMMITFLOW_CLIENT_ID", "client-123"),
        patch.object(config, "SUMMITFLOW_REQUEST_SOURCE", "source-abc"),
    ):
        assert config.build_agent_hub_headers(
            client_id="override-client",
            request_source="override-source",
            extra_headers={"Content-Type": "application/json"},
        ) == {
            "X-Client-Id": "override-client",
            "X-Request-Source": "override-source",
            "Content-Type": "application/json",
        }


def test_build_agent_hub_headers_empty_string_client_id_omits_header() -> None:
    """Explicit empty string client_id should behave the same as None (no X-Client-Id header)."""
    with (
        patch.object(config, "SUMMITFLOW_CLIENT_ID", None),
        patch.object(config, "SUMMITFLOW_REQUEST_SOURCE", "source-abc"),
    ):
        headers = config.build_agent_hub_headers(client_id="")
        assert "X-Client-Id" not in headers
        assert headers == {"X-Request-Source": "source-abc"}


def test_build_agent_hub_headers_uses_default_request_source_when_config_missing() -> None:
    """Empty request-source config should fall back to the caller default."""
    with (
        patch.object(config, "SUMMITFLOW_CLIENT_ID", None),
        patch.object(config, "SUMMITFLOW_REQUEST_SOURCE", ""),
    ):
        assert config.build_agent_hub_headers(
            default_request_source="summitflow-observability",
        ) == {
            "X-Request-Source": "summitflow-observability",
        }
