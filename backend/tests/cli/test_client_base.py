from __future__ import annotations

import httpx
import pytest

from cli._client_base import APIError, BaseHTTPClient


def test_handle_response_preserves_canonical_error_payload() -> None:
    client = BaseHTTPClient("http://summitflow.test", "summitflow")
    response = httpx.Response(
        503,
        json={
            "error": "http_error",
            "message": "Failed to start autonomous execution",
            "dispatch": {"status": "disabled"},
        },
    )

    with pytest.raises(APIError) as exc_info:
        client._handle_response(response)

    assert exc_info.value.detail == {
        "error": "http_error",
        "message": "Failed to start autonomous execution",
        "dispatch": {"status": "disabled"},
    }


def test_handle_response_keeps_legacy_detail() -> None:
    client = BaseHTTPClient("http://summitflow.test", "summitflow")
    response = httpx.Response(400, json={"detail": "legacy failure"})

    with pytest.raises(APIError) as exc_info:
        client._handle_response(response)

    assert exc_info.value.detail == "legacy failure"
