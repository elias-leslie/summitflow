"""Routing synchronization helpers for the Agent Hub agents CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

_ROUTING_MODES = {"manual_locked", "auto_shadow", "auto_canary", "auto"}


def default_manual_route(routing: dict[str, Any]) -> dict[str, Any] | None:
    routes = routing.get("manual_routes")
    if not isinstance(routes, list):
        return None
    for route in routes:
        if (
            isinstance(route, dict)
            and route.get("workload_profile") is None
            and route.get("enabled", True) is not False
        ):
            return route
    return None


def sync_manual_route(
    slug: str,
    *,
    primary_model: str | None,
    fallback_model: list[str] | None,
    escalation_model: str | None,
    routing_mode: str | None,
    change_reason: str | None,
    agents_api: Callable[..., dict[str, Any]],
    output_error: Callable[[str], None],
) -> None:
    """Mirror CLI model flags into Agent Hub routing tables."""
    if routing_mode is not None and routing_mode not in _ROUTING_MODES:
        output_error(f"Invalid routing mode: {routing_mode}")
        raise typer.Exit(1)
    if not any([primary_model, fallback_model is not None, escalation_model, routing_mode]):
        return

    payload: dict[str, Any] = {}
    if routing_mode is not None:
        payload["default_routing_mode"] = routing_mode

    should_sync_route = bool(primary_model or escalation_model)
    if fallback_model is not None and not should_sync_route:
        should_sync_route = routing_mode is not None
    if should_sync_route:
        payload.setdefault("default_routing_mode", "manual_locked")
        routing = agents_api("GET", f"/{slug}/routing")
        current_route = default_manual_route(routing) or {}
        current_primary = current_route.get("primary_model_id")
        resolved_primary = primary_model or (str(current_primary) if current_primary else None)
        if not resolved_primary:
            output_error("--primary-model is required when no default manual route exists.")
            raise typer.Exit(1)
        current_fallbacks = current_route.get("fallback_models")
        payload["manual_route"] = {
            "primary_model_id": resolved_primary,
            "fallback_models": fallback_model if fallback_model is not None else list(current_fallbacks or []),
            "escalation_model_id": escalation_model
            if escalation_model is not None
            else current_route.get("escalation_model_id"),
            "reason": change_reason or "st agents update manual route",
            "owner": "st agents update",
            "enabled": True,
        }

    if not payload:
        return

    agents_api("PUT", f"/{slug}/routing", json=payload)
