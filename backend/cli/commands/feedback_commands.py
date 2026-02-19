"""Implementation of st feedback subcommands."""

from __future__ import annotations

from typing import Any

import typer

from ..output import output_error
from .feedback_api import feedback_request
from .feedback_formatters import (
    output_duplicate_candidates,
    output_feedback_created,
    output_feedback_detail,
    output_feedback_list,
    output_feedback_voted,
    output_summary,
)

VALID_TYPES = ("friction", "idea", "improvement", "praise")
VALID_SEVERITIES = ("low", "medium", "high")
VALID_STATUSES = ("open", "acknowledged", "resolved", "wont_fix")
VALID_SORTS = ("votes", "newest", "oldest")


def _get_component_suggestions(bad_id: str) -> list[str]:
    """Get component ID suggestions for fuzzy matching."""
    try:
        from app.services.memory.scorecard_component_map import get_all_component_ids

        all_ids = get_all_component_ids()
    except Exception:
        return []

    prefix = bad_id.split(".")[0] + "."
    return [cid for cid in all_ids if cid.startswith(prefix)]


def _validate_component_id(component_id: str) -> None:
    """Validate component ID, show suggestions on failure."""
    try:
        from app.services.memory.scorecard_component_map import is_valid_component_id

        if is_valid_component_id(component_id):
            return
    except Exception:
        return  # Can't validate, let server handle it

    suggestions = _get_component_suggestions(component_id)
    msg = f'Unknown component "{component_id}".'
    if suggestions:
        msg += f' Did you mean: {", ".join(suggestions[:5])}?'
    else:
        try:
            from app.services.memory.scorecard_component_map import get_all_component_ids
            all_ids = get_all_component_ids()
            msg += f'\nValid components: {", ".join(all_ids[:10])}...'
        except Exception:
            pass
    output_error(msg)
    raise typer.Exit(1)


def report_impl(
    component_id: str,
    title: str,
    *,
    feedback_type: str = "friction",
    severity: str | None = None,
    description: str | None = None,
    project_id: str = "summitflow",
    session_id: str | None = None,
    agent_slug: str | None = None,
    model_used: str | None = None,
    session_type: str | None = None,
    auto_dedup: bool = False,
) -> None:
    """Create a new feedback item."""
    _validate_component_id(component_id)

    if feedback_type not in VALID_TYPES:
        output_error(
            f'Invalid type "{feedback_type}". Valid types: {", ".join(VALID_TYPES)}'
        )
        raise typer.Exit(1)

    if severity and severity not in VALID_SEVERITIES:
        output_error(
            f'Invalid severity "{severity}". Valid: {", ".join(VALID_SEVERITIES)}'
        )
        raise typer.Exit(1)

    body: dict[str, Any] = {
        "component_id": component_id,
        "feedback_type": feedback_type,
        "title": title,
        "project_id": project_id,
        "auto_dedup": auto_dedup,
    }
    if description:
        body["description"] = description
    if severity:
        body["severity"] = severity
    if session_id:
        body["session_id"] = session_id
    if agent_slug:
        body["agent_slug"] = agent_slug
    if model_used:
        body["model_used"] = model_used
    if session_type:
        body["session_type"] = session_type

    result = feedback_request("POST", "/api/feedback", json=body)

    item = result.get("item", {})
    created = result.get("created", True)
    candidates = result.get("duplicate_candidates", [])

    if not created:
        # Auto-dedup voted on existing
        output_feedback_voted(item)
        return

    if candidates:
        output_duplicate_candidates(candidates)

    output_feedback_created(item)


def search_impl(
    query: str,
    *,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    sort: str = "votes",
    limit: int = 20,
) -> None:
    """Search feedback items."""
    params: dict[str, Any] = {"query": query, "sort": sort, "limit": limit}
    if component_id:
        params["component_id"] = component_id
    if feedback_type:
        params["feedback_type"] = feedback_type
    if status:
        params["status"] = status
    if project_id:
        params["project_id"] = project_id

    result = feedback_request("GET", "/api/feedback", params=params)
    items = result.get("items", [])
    total = result.get("total", len(items))
    output_feedback_list(items, total)


def list_impl(
    *,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    sort: str = "votes",
    limit: int = 50,
) -> None:
    """List feedback items."""
    params: dict[str, Any] = {"sort": sort, "limit": limit}
    if component_id:
        params["component_id"] = component_id
    if feedback_type:
        params["feedback_type"] = feedback_type
    if status:
        params["status"] = status
    if project_id:
        params["project_id"] = project_id

    result = feedback_request("GET", "/api/feedback", params=params)
    items = result.get("items", [])
    total = result.get("total", len(items))
    output_feedback_list(items, total)


def get_impl(item_id: str) -> None:
    """Get feedback item details with votes."""
    result = feedback_request("GET", f"/api/feedback/{item_id}")
    output_feedback_detail(result)


def vote_impl(
    item_id: str,
    *,
    session_id: str | None = None,
    comment: str | None = None,
    agent_slug: str | None = None,
    model_used: str | None = None,
) -> None:
    """Vote on a feedback item."""
    if not session_id:
        output_error("--session-id is required for voting")
        raise typer.Exit(1)

    body: dict[str, Any] = {"session_id": session_id}
    if comment:
        body["comment"] = comment
    if agent_slug:
        body["agent_slug"] = agent_slug
    if model_used:
        body["model_used"] = model_used

    result = feedback_request("POST", f"/api/feedback/{item_id}/vote", json=body)

    if "message" in result and result.get("message") == "Already voted":
        print(f"VOTE:ALREADY_VOTED:{item_id[:8]}|{session_id[:8]}")
        return

    # Re-fetch item for updated vote count
    item = feedback_request("GET", f"/api/feedback/{item_id}")
    output_feedback_voted(item)


def resolve_impl(
    item_id: str,
    *,
    note: str | None = None,
) -> None:
    """Resolve a feedback item."""
    body: dict[str, Any] = {"status": "resolved"}
    if note:
        body["resolution_note"] = note

    result = feedback_request("PATCH", f"/api/feedback/{item_id}", json=body)
    print(f"FEEDBACK:RESOLVED:{result.get('id', item_id)[:8]}|{result.get('title', '')}")


def delete_impl(item_id: str) -> None:
    """Delete a feedback item."""
    feedback_request("DELETE", f"/api/feedback/{item_id}")
    print(f"FEEDBACK:DELETED:{item_id[:8]}")


def summary_impl(
    *,
    project_id: str | None = None,
    days: int = 30,
) -> None:
    """Get feedback summary."""
    params: dict[str, Any] = {"days": days}
    if project_id:
        params["project_id"] = project_id

    result = feedback_request("GET", "/api/feedback/summary", params=params)
    output_summary(result)
