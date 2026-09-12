"""Tasks storage - Core CRUD operations.

This module provides basic data access for task records.
"""

from __future__ import annotations

from typing import Any

from psycopg import Cursor

from .._task_spirit_write import insert_task_spirit
from ..connection import generate_prefixed_id, get_connection, get_cursor
from .columns import TASK_COLUMNS, TASK_COLUMNS_WITH_SPIRIT
from .execution_mode import normalize_execution_fields
from .mapping import row_to_dict, row_to_dict_with_spirit
from .update import update_task_fields


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    return generate_prefixed_id("task")


def canonicalize_task_id(task_id: str) -> str:
    """Normalize user/agent input to the canonical stored task id format."""
    raw = task_id.strip()
    if raw.startswith("task-"):
        return raw
    return f"task-{raw}"


def _fetch_task_row(task_id: str) -> Any | None:
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS_WITH_SPIRIT}
            FROM tasks t
            LEFT JOIN task_spirit ts ON t.id = ts.task_id
            WHERE t.id = %s
            """,
            (task_id,),
        )
        return cur.fetchone()


class ExternalTaskConflict(ValueError):
    """An external request key already describes a different payload."""


class ExternalTaskUnavailable(ValueError):
    """Identity is retained but its task has no available live/archive record."""


def _reserve_external_request(
    cur: Cursor, identity: dict[str, str], task_id: str,
) -> dict[str, Any] | None:
    """Unique insertion waits for concurrent intake to commit, then reconciles."""
    key = (identity["principal_scope"], identity["external_origin"], identity["external_request_key"])
    cur.execute(
        """INSERT INTO task_external_requests
        (principal_scope, external_origin, external_request_key, external_payload_digest, task_id)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING task_id""",
        (*key, identity["external_payload_digest"], task_id),
    )
    if cur.fetchone():
        return None
    cur.execute(
        """SELECT task_id, external_payload_digest FROM task_external_requests
        WHERE principal_scope = %s AND external_origin = %s AND external_request_key = %s""", key,
    )
    existing = cur.fetchone()
    if existing is None:
        raise ExternalTaskUnavailable("External task identity could not be reconciled")
    if existing[1] != identity["external_payload_digest"]:
        raise ExternalTaskConflict("External request key already has a different payload")
    cur.execute(
        f"SELECT {TASK_COLUMNS_WITH_SPIRIT} FROM tasks t LEFT JOIN task_spirit ts ON t.id = ts.task_id WHERE t.id = %s",
        (existing[0],),
    )
    if row := cur.fetchone():
        return {**row_to_dict_with_spirit(row), "_external_reused": True}
    cur.execute(
        "SELECT snapshot FROM task_deletions WHERE task_id = %s ORDER BY deleted_at DESC, id DESC LIMIT 1",
        (existing[0],),
    )
    if archived := cur.fetchone():
        return {**archived[0]["task"], "archived": True, "_external_reused": True}
    raise ExternalTaskUnavailable(f"External task {existing[0]} is no longer available")


def _insert_task(
    params: tuple[Any, ...], *, external_identity: dict[str, str] | None = None,
    initial_spirit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute INSERT for a task row and return the created dict."""
    with get_connection() as conn, conn.cursor() as cur:
        if external_identity:
            existing = _reserve_external_request(cur, external_identity, str(params[0]))
            if existing is not None:
                return existing
        cur.execute(
            f"""
            INSERT INTO tasks (id, project_id, capability_id, title, description,
                               priority, task_type, parent_task_id, tier,
                               current_phase, raw_request, enrichment_status,
                               complexity, execution_mode, labels, ai_review)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {TASK_COLUMNS}
            """,
            params,
        )
        row = cur.fetchone()
        if initial_spirit:
            insert_task_spirit(cur, str(params[0]), **initial_spirit)
        conn.commit()
    return row_to_dict(row)


def create_task(
    project_id: str,
    title: str,
    capability_id: int | None = None,
    description: str | None = None,
    task_id: str | None = None,
    priority: int = 2,
    task_type: str = "task",
    parent_task_id: str | None = None,
    tier: int | None = None,
    current_phase: str = "plan",
    raw_request: str | None = None,
    enrichment_status: str = "none",
    complexity: str | None = None,
    execution_mode: str | None = None,
    labels: list[str] | None = None,
    ai_review: bool = True,
    *,
    external_identity: dict[str, str] | None = None,
    initial_spirit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new task and return its dict.

    Spirit fields (objective, constraints, done_when, etc.) live in task_spirit;
    use storage.task_spirit functions. Verification is at step level (storage.steps).
    """
    task_id = _generate_task_id() if task_id is None else canonicalize_task_id(task_id)
    execution_fields = normalize_execution_fields(
        task_type=task_type,
        execution_mode=execution_mode,
        autonomous=None,
    )
    params = (
        task_id, project_id, capability_id, title, description,
        priority, task_type, parent_task_id, tier,
        current_phase, raw_request, enrichment_status,
        complexity, execution_fields["execution_mode"],
        labels or [], ai_review,
    )
    return _insert_task(params, external_identity=external_identity, initial_spirit=initial_spirit)


def get_task(task_id: str) -> dict[str, Any] | None:
    """Get a task by ID with spirit fields, or None if not found."""
    canonical_task_id = canonicalize_task_id(task_id)
    row = _fetch_task_row(task_id) if canonical_task_id != task_id else None
    if row is None:
        row = _fetch_task_row(canonical_task_id)
    if not row:
        return None
    return row_to_dict_with_spirit(row)


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update task fields. Returns updated dict or None if not found.

    Raises:
        ValueError: If no fields provided or invalid field name.
    """
    resolved_task_id = canonicalize_task_id(task_id)
    # `autonomous` is no longer a column; map any legacy callers to execution_mode.
    legacy_autonomous = fields.pop("autonomous", None)
    if "execution_mode" in fields or legacy_autonomous is not None or "task_type" in fields:
        existing = get_task(resolved_task_id)
        if existing is None:
            return None
        execution_fields = normalize_execution_fields(
            task_type=str(fields.get("task_type", existing.get("task_type", "task"))),
            execution_mode=fields.get("execution_mode", existing.get("execution_mode")),
            autonomous=legacy_autonomous if legacy_autonomous is not None else existing.get("autonomous"),
        )
        fields["execution_mode"] = execution_fields["execution_mode"]
    return update_task_fields(resolved_task_id, **fields)


def delete_task(
    task_id: str,
    *,
    deletion_source: str = "storage:delete_task",
    deletion_reason: str | None = None,
) -> bool:
    """Delete a task after archiving its final snapshot for postmortems."""
    from .deletions import archive_task_snapshots

    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        archived_ids = archive_task_snapshots(
            cur,
            [resolved_task_id],
            deletion_source=deletion_source,
            deletion_reason=deletion_reason,
        )
        if not archived_ids:
            conn.commit()
            return False
        cur.execute(
            "DELETE FROM tasks WHERE id = %s RETURNING id",
            (resolved_task_id,),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


# Re-export for backwards compatibility
from .columns import (  # noqa: E402
    EXPECTED_TASK_COLUMNS,
    EXPECTED_TASK_COLUMNS_WITH_SPIRIT,
    TASK_COLUMNS_ALIASED,
)
from .sessions import add_agent_hub_session, get_agent_hub_sessions  # noqa: E402

# Private functions re-exported for package use
_row_to_dict = row_to_dict
_row_to_dict_with_spirit = row_to_dict_with_spirit

__all__ = [
    "EXPECTED_TASK_COLUMNS",
    "EXPECTED_TASK_COLUMNS_WITH_SPIRIT",
    "TASK_COLUMNS",
    "TASK_COLUMNS_ALIASED",
    "TASK_COLUMNS_WITH_SPIRIT",
    "_row_to_dict",
    "_row_to_dict_with_spirit",
    "add_agent_hub_session",
    "canonicalize_task_id",
    "create_task",
    "delete_task",
    "get_agent_hub_sessions",
    "get_task",
    "update_task",
]
