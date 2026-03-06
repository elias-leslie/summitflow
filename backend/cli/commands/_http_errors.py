"""Shared HTTP transport error helpers for CLI commands."""

from __future__ import annotations

import httpx
import typer

from ..output import output_error


def _extract_root_error_message(error: BaseException) -> str:
    """Return the deepest useful exception message."""
    current: BaseException = error
    seen: set[int] = set()

    while id(current) not in seen:
        seen.add(id(current))
        nested = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if nested is None:
            break
        current = nested

    message = str(current).strip()
    return message or current.__class__.__name__


def raise_connect_error(service_name: str, url: str, error: httpx.ConnectError) -> None:
    """Emit a detailed connect error and exit."""
    detail = _extract_root_error_message(error)
    output_error(f"Cannot connect to {service_name} at {url}: {detail}")
    output_error("Verify the service URL/protocol and that it is reachable from this shell.")
    raise typer.Exit(1) from None


def raise_timeout_error(service_name: str, url: str, timeout: float, error: httpx.TimeoutException) -> None:
    """Emit a detailed timeout error and exit."""
    detail = _extract_root_error_message(error)
    output_error(f"Request to {service_name} at {url} timed out after {timeout:.0f}s: {detail}")
    output_error("Verify the service is healthy or retry with a larger timeout if the operation is expected to be slow.")
    raise typer.Exit(1) from None
