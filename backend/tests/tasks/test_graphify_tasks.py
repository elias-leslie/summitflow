from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tasks.graphify_tasks import refresh_existing_graphify_graphs


def test_refresh_existing_graphify_graphs_refreshes_only_stale_existing_graphs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stale_root = tmp_path / "stale"
    fresh_root = tmp_path / "fresh"
    missing_root = tmp_path / "missing"
    invalid_root = tmp_path / "invalid"
    for root in (stale_root, fresh_root, missing_root):
        root.mkdir()

    monkeypatch.setattr(
        "app.tasks.graphify_tasks.list_projects",
        lambda: [
            {"id": "stale", "root_path": str(stale_root)},
            {"id": "fresh", "root_path": str(fresh_root)},
            {"id": "missing", "root_path": str(missing_root)},
            {"id": "invalid", "root_path": str(invalid_root)},
        ],
    )

    def fake_status(project_id: str, root: Path) -> dict[str, Any]:
        if project_id == "stale":
            return {"graph_exists": True, "diagnostics": ["graph_stale"]}
        if project_id == "fresh":
            return {"graph_exists": True, "diagnostics": []}
        return {"graph_exists": False, "diagnostics": ["graph_missing"]}

    refreshed: list[Path] = []
    monkeypatch.setattr(
        "app.tasks.graphify_tasks.maintenance_store.record_maintenance_run",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("app.tasks.graphify_tasks.graphify_status", fake_status)
    monkeypatch.setattr("app.tasks.graphify_tasks.refresh_graph", lambda root: refreshed.append(root))

    result = refresh_existing_graphify_graphs()

    assert result["status"] == "success"
    assert result["projects"] == 4
    assert result["refreshed"] == 1
    assert result["skipped_fresh"] == 1
    assert result["skipped_missing"] == 1
    assert result["skipped_invalid_root"] == 1
    assert refreshed == [stale_root.resolve()]
