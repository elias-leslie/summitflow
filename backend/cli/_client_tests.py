"""Test operations for SummitFlow Tasks API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


def list_tests(client: httpx.Client, url_fn: Any, handle_response: Any, test_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List tests for the project."""
    params: dict[str, Any] = {"limit": limit}
    if test_type:
        params["type"] = test_type
    response = client.get(url_fn("/tests"), params=params)
    return cast(list[dict[str, Any]], handle_response(response))


def import_tests(client: httpx.Client, url_fn: Any, handle_response: Any, framework: str) -> dict[str, Any]:
    """Import tests from a framework."""
    response = client.post(url_fn("/tests/import"), json={"framework": framework})
    return cast(dict[str, Any], handle_response(response))
