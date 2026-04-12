"""Tests for shared Agent Hub header/config helpers."""

from __future__ import annotations

from pathlib import Path
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


def test_load_env_local_credentials_reads_home_env_file(tmp_path: Path) -> None:
    """Credential helper should read SummitFlow client headers from ~/.env.local."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env.local").write_text(
        "SUMMITFLOW_CLIENT_ID=file-client\nSUMMITFLOW_REQUEST_SOURCE=file-source\n",
        encoding="utf-8",
    )

    with patch.object(config.Path, "home", return_value=home):
        creds = config._load_env_local_credentials()

    assert creds == {
        "SUMMITFLOW_CLIENT_ID": "file-client",
        "SUMMITFLOW_REQUEST_SOURCE": "file-source",
    }


def test_load_env_local_credentials_strips_quotes_and_export_prefix(tmp_path: Path) -> None:
    """Env-local parsing should match CLI credential parsing semantics."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env.local").write_text(
        'export SUMMITFLOW_CLIENT_ID="quoted-client"\n'
        "SUMMITFLOW_REQUEST_SOURCE='quoted-source'\n",
        encoding="utf-8",
    )

    with patch.object(config.Path, "home", return_value=home):
        creds = config._load_env_local_credentials()

    assert creds == {
        "SUMMITFLOW_CLIENT_ID": "quoted-client",
        "SUMMITFLOW_REQUEST_SOURCE": "quoted-source",
    }
