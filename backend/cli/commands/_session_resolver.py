"""Resolve short session IDs to the full UUID expected by Agent Hub APIs.

``st sessions list`` prints an 8-character short ID per row to keep its
compact output readable, but Agent Hub's session-detail / close / events
endpoints require the full UUID. Without resolution, operators have to copy
a different value than the one they just saw on screen and any of
``sessions show``, ``sessions close``, ``agent status``, ``agent stop``, or
``session-events`` would fail with an API 404.

This helper accepts either form and returns the full ID:

* A value that parses as a session UUID is returned unchanged.
* Anything else is treated as a prefix and matched against
``list_sessions`` in the current project/recent session window. Exactly one
  match is resolved; multiple or zero matches both exit with a clear error so
  the operator gets actionable feedback instead of a downstream 404.
"""

from __future__ import annotations

import re
from typing import Any

import typer

from ..client import APIError
from ..output import output_error

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Agent Hub caps session page_size at 100. Prefix lookup stays deliberately
# bounded so a convenience lookup cannot hang on all historical sessions.
_PAGE_SIZE = 100
_MAX_PAGES = 5


def _client_project_id(client: Any) -> str | None:
    project_id = getattr(client, "project_id", None)
    return project_id if isinstance(project_id, str) and project_id.strip() else None


def resolve_session_id(
    session_id: str,
    client: Any | None = None,
    *,
    project_id: str | None = None,
    max_pages: int = _MAX_PAGES,
) -> str:
    """Return the full session UUID for a possibly-truncated ``session_id``.

    ``client`` must expose ``list_sessions(limit=..., page=...)`` (any object
    that satisfies that interface works, including ``STClient``). A
    project-less ``STClient`` is constructed when ``client`` is omitted so the
    helper can be called from places that do not already hold one.
    """
    if not session_id or _UUID_RE.match(session_id):
        return session_id

    if client is None:
        from ..client import STClient

        client = STClient(require_project=False)

    matched: list[str] = []
    lookup_project_id = project_id or _client_project_id(client)
    for page in range(1, max(max_pages, 1) + 1):
        try:
            batch = client.list_sessions(
                limit=_PAGE_SIZE,
                page=page,
                project_id=lookup_project_id,
            )
        except APIError as exc:
            output_error(f"Could not resolve session ID '{session_id}': {exc}")
            raise typer.Exit(1) from exc
        if not isinstance(batch, list):
            break
        for session in batch:
            if not isinstance(session, dict):
                continue
            sid = session.get("id")
            if isinstance(sid, str) and sid.startswith(session_id):
                matched.append(sid)
        if len(batch) < _PAGE_SIZE:
            break

    if len(matched) == 1:
        return matched[0]

    if len(matched) > 1:
        preview = ", ".join(matched[:5])
        suffix = "..." if len(matched) > 5 else ""
        output_error(
            f"Ambiguous session ID '{session_id}'. Matches: {preview}{suffix}"
        )
        raise typer.Exit(1)

    scope = f" for project '{lookup_project_id}'" if lookup_project_id else ""
    output_error(
        f"No recent session found with ID starting with '{session_id}'{scope}. "
        "Use the full UUID for older sessions."
    )
    raise typer.Exit(1)
