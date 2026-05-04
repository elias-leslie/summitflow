from __future__ import annotations

from datetime import datetime
from typing import Any

SESSION_COLUMNS = """
    session_id,
    project_id,
    title,
    target_url,
    target_mode,
    agent_hub_session_id,
    state,
    sensitive,
    control_owner,
    control_expires_at,
    browser_target_source,
    media_strategy,
    evidence_policy,
    created_by_kind,
    created_by_display,
    created_at,
    updated_at,
    closed_at
"""

PARTICIPANT_COLUMNS = """
    participant_id,
    session_id,
    participant_key,
    actor_kind,
    display_name,
    role,
    status,
    last_seen_at,
    joined_at
"""

ANNOTATION_COLUMNS = """
    annotation_id,
    session_id,
    kind,
    page_key,
    page_url_snapshot,
    selector,
    anchor,
    comment,
    created_by_kind,
    created_by_display,
    created_at
"""

EVIDENCE_COLUMNS = """
    evidence_id,
    session_id,
    annotation_id,
    title,
    url,
    page_url_snapshot,
    viewport,
    selector,
    bbox,
    context_summary,
    artifact_id,
    token_estimate,
    created_by_kind,
    created_by_display,
    created_at
"""

AUDIT_COLUMNS = """
    audit_id,
    session_id,
    actor_kind,
    action,
    detail,
    created_at
"""

CONNECTOR_PAIRING_COLUMNS = """
    pairing_id,
    session_id,
    state,
    connector_host,
    profile_label,
    connector_version,
    connector_state,
    expires_at,
    claimed_at,
    connector_last_seen_at,
    revoked_at,
    created_at,
    updated_at
"""

CONNECTOR_PAIRING_JOIN_COLUMNS = """
    collab_connector_pairings.pairing_id,
    collab_connector_pairings.session_id,
    collab_connector_pairings.state,
    collab_connector_pairings.connector_host,
    collab_connector_pairings.profile_label,
    collab_connector_pairings.connector_version,
    collab_connector_pairings.connector_state,
    collab_connector_pairings.expires_at,
    collab_connector_pairings.claimed_at,
    collab_connector_pairings.connector_last_seen_at,
    collab_connector_pairings.revoked_at,
    collab_connector_pairings.created_at,
    collab_connector_pairings.updated_at
"""


def iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def session_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "session_id": row[0],
        "project_id": row[1],
        "title": row[2],
        "target_url": row[3],
        "target_mode": row[4],
        "agent_hub_session_id": row[5],
        "state": row[6],
        "sensitive": row[7],
        "control_owner": row[8],
        "control_expires_at": iso(row[9]),
        "browser_target_source": row[10],
        "media_strategy": row[11],
        "evidence_policy": row[12],
        "created_by_kind": row[13],
        "created_by_display": row[14],
        "created_at": iso(row[15]),
        "updated_at": iso(row[16]),
        "closed_at": iso(row[17]),
    }


def participant_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "participant_id": row[0],
        "session_id": row[1],
        "participant_key": row[2],
        "actor_kind": row[3],
        "display_name": row[4],
        "role": row[5],
        "status": row[6],
        "last_seen_at": iso(row[7]),
        "joined_at": iso(row[8]),
    }


def annotation_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "annotation_id": row[0],
        "session_id": row[1],
        "kind": row[2],
        "page_key": row[3],
        "page_url_snapshot": row[4],
        "selector": row[5],
        "anchor": row[6] or {},
        "comment": row[7],
        "created_by_kind": row[8],
        "created_by_display": row[9],
        "created_at": iso(row[10]),
    }


def evidence_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "evidence_id": row[0],
        "session_id": row[1],
        "annotation_id": row[2],
        "title": row[3],
        "url": row[4],
        "page_url_snapshot": row[5],
        "viewport": row[6] or {},
        "selector": row[7],
        "bbox": row[8],
        "context_summary": row[9],
        "artifact_id": row[10],
        "token_estimate": row[11],
        "created_by_kind": row[12],
        "created_by_display": row[13],
        "created_at": iso(row[14]),
    }


def audit_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "audit_id": row[0],
        "session_id": row[1],
        "actor_kind": row[2],
        "action": row[3],
        "detail": row[4] or {},
        "created_at": iso(row[5]),
    }


def connector_pairing_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "pairing_id": row[0],
        "session_id": row[1],
        "state": row[2],
        "connector_host": row[3],
        "profile_label": row[4],
        "connector_version": row[5],
        "connector_state": row[6] or {},
        "expires_at": iso(row[7]),
        "claimed_at": iso(row[8]),
        "connector_last_seen_at": iso(row[9]),
        "revoked_at": iso(row[10]),
        "created_at": iso(row[11]),
        "updated_at": iso(row[12]),
    }
