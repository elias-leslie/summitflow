"""Overlap detection helpers for the sessions CLI."""

from __future__ import annotations

from itertools import combinations

from .._output_state import is_compact
from ..client import APIError, STClient
from ..output import handle_api_error, output_json
from .sessions_ownership import _resolve_projects, collect_project_owners

_SHARED_PLUMBING_PREFIXES = (
    "backend/app/adapters/",
    "backend/app/api/complete/",
    "backend/app/services/tools/",
)


def _owner_write_paths(owner: dict[str, object]) -> set[str]:
    write_paths = owner.get("observed_write_paths")
    declared_paths = owner.get("declared_scope_paths")
    fallback = owner.get("scope_paths")
    normalized: set[str] = set()
    for values in (declared_paths, write_paths, fallback):
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value:
                normalized.add(value)
        if normalized:
            return normalized
    return normalized


def _owner_read_paths(owner: dict[str, object]) -> set[str]:
    values = owner.get("observed_read_paths")
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str) and value}


def _shared_plumbing(paths: set[str]) -> list[str]:
    return sorted(path for path in paths if any(path.startswith(p) for p in _SHARED_PLUMBING_PREFIXES))


def _make_overlap_row(
    project_id: str,
    risk: str,
    kind: str,
    left_id: str,
    right_id: str,
    paths: list[str],
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "risk": risk,
        "kind": kind,
        "left_id": left_id,
        "right_id": right_id,
        "paths": paths,
    }


def _classify_pair(
    project_id: str,
    left_id: str,
    right_id: str,
    left_write: set[str],
    right_write: set[str],
    left_read: set[str],
    right_read: set[str],
) -> dict[str, object] | None:
    exact = sorted(left_write & right_write)
    if exact:
        return _make_overlap_row(project_id, "block", "exact_write", left_id, right_id, exact)

    shared = sorted(set(_shared_plumbing(left_write)) | set(_shared_plumbing(right_write)))
    if shared:
        return _make_overlap_row(project_id, "block", "shared_plumbing", left_id, right_id, shared)

    read_overlap = sorted((left_write & right_read) | (right_write & left_read))
    if read_overlap:
        return _make_overlap_row(project_id, "warn", "read_overlap", left_id, right_id, read_overlap)

    if not left_write and not left_read and not right_write and not right_read:
        return _make_overlap_row(project_id, "warn", "unscoped_pair", left_id, right_id, [])

    return None


def overlap_rows(project_id: str, owners: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for left, right in combinations(owners, 2):
        left_id = str(left.get("task_id") or left.get("session_id") or "?")
        right_id = str(right.get("task_id") or right.get("session_id") or "?")
        row = _classify_pair(
            project_id,
            left_id,
            right_id,
            _owner_write_paths(left),
            _owner_write_paths(right),
            _owner_read_paths(left),
            _owner_read_paths(right),
        )
        if row is not None:
            rows.append(row)
    return rows


def render_overlap_list(client: STClient, project_id: str | None) -> None:
    rows: list[dict[str, object]] = []

    try:
        for pid in _resolve_projects(client, project_id):
            owners = collect_project_owners(client, pid)
            rows.extend(overlap_rows(pid, owners))
    except APIError as e:
        handle_api_error(e)
        return

    if not is_compact():
        output_json({"overlaps": rows, "total": len(rows)})
        return

    print(f"OVERLAPS[{len(rows)}]")
    for row in rows:
        parts = [
            str(row.get("project_id") or "?"),
            str(row.get("risk") or "?"),
            str(row.get("kind") or "?"),
            str(row.get("left_id") or "?"),
            str(row.get("right_id") or "?"),
        ]
        if isinstance(row.get("paths"), list) and row["paths"]:
            parts.append(f"paths={','.join(str(path) for path in row['paths'][:3])}")
        print("OVR " + " | ".join(parts))
