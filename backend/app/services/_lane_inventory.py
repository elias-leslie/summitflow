"""Agent Hub inventory fetching and session normalization for task-session preflight."""

from __future__ import annotations

from typing import TypedDict, cast

import httpx

from ._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers

_LIST_SESSIONS_TIMEOUT = 10.0
_LIVE_OWNERSHIP_PATH = "/api/ownership/projects/{project_id}/live"
_LEGACY_SESSIONS_PATH = "/api/sessions"


class SpecialistSummary(TypedDict):
    agent_slug: str
    count: int
    request_sources: list[str]
    session_ids: list[str]
    newest_age_minutes: int
    oldest_age_minutes: int


def _owner_list(owner: dict[str, object], key: str) -> list[object]:
    """Return a list value from an owner dict, defaulting to empty list."""
    val = owner.get(key)
    return list(val) if isinstance(val, list) else []


def _as_object_dict(value: object) -> dict[str, object]:
    """Return a dict[str, object] view of a JSON object, or an empty dict."""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _owner_to_session(owner: dict[str, object]) -> dict[str, object]:
    """Convert a live-ownership record to the normalized session shape."""
    return {
        "id": owner.get("session_id"),
        "external_id": owner.get("task_id"),
        "current_branch": owner.get("branch"),
        "working_dir": owner.get("working_dir") or owner.get("checkout_path"),
        "status": owner.get("session_status"),
        "workstream_status": owner.get("workstream_status"),
        "workstream_note": owner.get("workstream_note"),
        "ownership_kind": owner.get("ownership_kind"),
        "scope_paths": _owner_list(owner, "scope_paths"),
        "declared_scope_paths": _owner_list(owner, "declared_scope_paths"),
        "observed_read_paths": _owner_list(owner, "observed_read_paths"),
        "observed_write_paths": _owner_list(owner, "observed_write_paths"),
        "scope_confidence": owner.get("scope_confidence"),
        "created_at": owner.get("created_at"),
        "updated_at": owner.get("updated_at"),
    }


def _parse_ownership_payload(
    payload: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    """Parse a successful live-ownership response. Returns None if format is unrecognized."""
    owners = payload.get("active_owners")
    specialists = payload.get("active_specialists")
    if isinstance(owners, list):
        owner_sessions = [_owner_to_session(_as_object_dict(o)) for o in owners if isinstance(o, dict)]
        specialist_rows = cast(
            list[dict[str, object]],
            [_as_object_dict(r) for r in specialists if isinstance(r, dict)] if isinstance(specialists, list) else [],
        )
        return owner_sessions, specialist_rows

    sessions_raw = payload.get("sessions")
    if isinstance(sessions_raw, list):
        return [_as_object_dict(r) for r in sessions_raw if isinstance(r, dict)], []
    return None


def fetch_live_project_inventory(
    project_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return (owner_sessions, specialist_rows) for the given project."""
    headers = build_agent_hub_headers(default_request_source="summitflow-task-session-preflight")
    with httpx.Client(timeout=_LIST_SESSIONS_TIMEOUT) as client:
        ownership_url = f"{AGENT_HUB_URL}{_LIVE_OWNERSHIP_PATH.format(project_id=project_id)}"
        ownership_response = client.get(ownership_url, headers=headers)

        if ownership_response.status_code != 404:
            ownership_response.raise_for_status()
            parsed = _parse_ownership_payload(ownership_response.json())
            if parsed is not None:
                return parsed

        return _fetch_legacy_sessions(client, headers, project_id)


def _fetch_legacy_sessions(
    client: httpx.Client,
    headers: dict[str, str],
    project_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Fallback to the legacy /api/sessions endpoint."""
    response = client.get(
        f"{AGENT_HUB_URL}{_LEGACY_SESSIONS_PATH}",
        headers=headers,
        params={"project_id": project_id, "status": "active", "page_size": 100},
    )
    response.raise_for_status()
    payload = response.json()
    sessions_raw = payload.get("sessions", [])
    sessions = [r for r in sessions_raw if isinstance(r, dict)] if isinstance(sessions_raw, list) else []
    return sessions, []


def summarize_active_specialists(
    rows: list[dict[str, object]],
) -> list[SpecialistSummary]:
    """Group live specialist sessions for context surfaces without changing blockers."""
    counts: dict[str, int] = {}
    sources: dict[str, set[str]] = {}
    session_ids: dict[str, list[str]] = {}
    newest: dict[str, int] = {}
    oldest: dict[str, int] = {}

    for row in rows:
        slug = str(row.get("agent_slug") or "unknown")
        raw_age = row.get("age_minutes")
        age = int(raw_age) if isinstance(raw_age, (int, float)) else 0
        counts[slug] = counts.get(slug, 0) + 1
        if slug not in sources:
            sources[slug] = set()
            session_ids[slug] = []
            newest[slug] = age
            oldest[slug] = age
        if row.get("request_source"):
            sources[slug].add(str(row["request_source"]))
        if row.get("session_id"):
            session_ids[slug].append(str(row["session_id"]))
        newest[slug] = min(newest[slug], age)
        oldest[slug] = max(oldest[slug], age)

    result: list[SpecialistSummary] = [
        {
            "agent_slug": slug,
            "count": counts[slug],
            "request_sources": sorted(sources[slug]),
            "session_ids": session_ids[slug][:3],
            "newest_age_minutes": newest[slug],
            "oldest_age_minutes": oldest[slug],
        }
        for slug in counts
    ]
    return sorted(result, key=lambda r: (-r["count"], r["agent_slug"]))
