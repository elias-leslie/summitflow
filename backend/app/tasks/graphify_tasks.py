"""Routine Graphify maintenance tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..services.graphify_tools import (
    graphify_code_refresh_needed,
    graphify_status,
    refresh_graph,
)
from ..storage import maintenance_runs as maintenance_store
from ..storage.projects import list_projects

GRAPHIFY_REFRESH_WORKFLOW = "refresh_graphify_graphs"


def refresh_existing_graphify_graphs() -> dict[str, Any]:
    """Refresh stale existing Graphify code graphs across registered projects."""
    from datetime import UTC, datetime

    started_at = datetime.now(UTC)
    refreshed: list[str] = []
    skipped_fresh: list[str] = []
    skipped_missing: list[str] = []
    skipped_invalid_root: list[str] = []
    failures: list[dict[str, str]] = []

    for project in list_projects():
        project_id = str(project.get("id") or "")
        root_path = project.get("root_path")
        if not project_id or not root_path:
            continue

        root = Path(str(root_path)).expanduser().resolve()
        if not root.is_dir():
            skipped_invalid_root.append(project_id)
            continue

        status = graphify_status(project_id, root)
        if not status.get("graph_exists"):
            skipped_missing.append(project_id)
            continue
        if not graphify_code_refresh_needed(status):
            skipped_fresh.append(project_id)
            continue

        try:
            refresh_graph(root)
        except Exception as exc:
            failures.append({"project_id": project_id, "error": str(exc)[-500:]})
            continue
        refreshed.append(project_id)

    result = {
        "status": "partial" if failures else "success",
        "projects": len(refreshed) + len(skipped_fresh) + len(skipped_missing) + len(skipped_invalid_root) + len(failures),
        "refreshed": len(refreshed),
        "skipped_fresh": len(skipped_fresh),
        "skipped_missing": len(skipped_missing),
        "skipped_invalid_root": len(skipped_invalid_root),
        "failed": len(failures),
        "refreshed_projects": refreshed[:20],
        "failures": failures[:20],
    }
    maintenance_store.record_maintenance_run(
        GRAPHIFY_REFRESH_WORKFLOW,
        result["status"],
        started_at=started_at,
        finished_at=datetime.now(UTC),
        rows_cleaned=result["refreshed"],
        summary=result,
        error_message="; ".join(item["error"] for item in failures[:3]) if failures else None,
    )
    return result
