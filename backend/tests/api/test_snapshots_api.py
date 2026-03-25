"""Tests for the snapshots API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from cli.lib.quick_snapshots import QuickSnapshot, SnapshotScope

client = TestClient(app)


class _FakePolicy:
    def to_dict(self) -> dict[str, int]:
        return {
            "lane_interval_minutes": 60,
            "project_interval_minutes": 1440,
            "baseline_stale_minutes": 30,
            "lane_auto_keep_per_scope": 24,
            "project_auto_keep_per_scope": 7,
            "archived_lane_auto_keep_per_scope": 3,
            "archived_lane_keep_per_project": 3,
            "manual_keep_per_scope": 20,
        }


def _snapshot(
    *,
    scope_type: str,
    scope_name: str,
    source: str,
    created_at: str,
) -> QuickSnapshot:
    return QuickSnapshot(
        id=f"{scope_name}-{source}",
        name=source,
        project_id="summitflow",
        repo_root="/repo",
        worktree_path=f"/workspaces/{scope_name}",
        scope_type=scope_type,
        scope_name=scope_name,
        snapshot_path=f"/snaps/{scope_name}-{source}",
        branch=f"{scope_name}/main" if scope_type == "lane" else "main",
        head_oid=f"oid-{scope_name}",
        head_ref="refs/heads/main",
        git_dir="/repo/.git",
        index_artifact_path=None,
        created_at=created_at,
        source=source,
    )


def _patch_snapshot_libs(monkeypatch) -> None:
    active_scope = SnapshotScope("lane", "task-live", Path("/workspaces/task-live"))
    archived_scope = SnapshotScope("lane", "task-old", Path("/workspaces/task-old"))
    manifests = {
        ("summitflow", "task-live"): [
            _snapshot(
                scope_type="lane",
                scope_name="task-live",
                source="auto-periodic",
                created_at="2026-03-24T19:36:22+00:00",
            )
        ],
        ("summitflow", "task-old"): [
            _snapshot(
                scope_type="lane",
                scope_name="task-old",
                source="auto-baseline",
                created_at="2026-03-24T10:35:22+00:00",
            )
        ],
    }

    def fake_load_manifest(project_id: str, scope: SnapshotScope):
        return manifests[(project_id, scope.scope_name)]

    def fake_enumerate_snapshot_scopes(*, include_archived: bool = False):
        scopes = [("summitflow", active_scope, "active")]
        if include_archived:
            scopes.append(("summitflow", archived_scope, "archived"))
        return scopes

    monkeypatch.setattr("app.api.snapshots._is_timer_active", lambda: False)
    monkeypatch.setattr(
        "app.api.snapshots._get_cli_libs",
        lambda: (None, None, None, fake_load_manifest, _FakePolicy(), fake_enumerate_snapshot_scopes, None),
    )


def test_snapshot_scopes_default_omits_archived_scopes(monkeypatch) -> None:
    _patch_snapshot_libs(monkeypatch)

    response = client.get("/api/snapshots/scopes")

    assert response.status_code == 200
    assert response.json() == [
        {
            "project_id": "summitflow",
            "scope_type": "lane",
            "scope_name": "task-live",
            "scope_state": "active",
            "snapshot_count": 1,
            "total_bytes": None,
            "newest_at": "2026-03-24T19:36:22+00:00",
            "oldest_at": "2026-03-24T19:36:22+00:00",
        }
    ]


def test_snapshot_scopes_include_archived_when_requested(monkeypatch) -> None:
    _patch_snapshot_libs(monkeypatch)

    response = client.get("/api/snapshots/scopes", params={"include_archived": "true"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {item["scope_state"] for item in body} == {"active", "archived"}


def test_snapshot_summary_reports_active_and_archived_counts(monkeypatch) -> None:
    _patch_snapshot_libs(monkeypatch)

    response = client.get("/api/snapshots/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["scope_count"] == 2
    assert body["active_scope_count"] == 1
    assert body["archived_scope_count"] == 1
    assert body["active_snapshot_count"] == 1
    assert body["archived_snapshot_count"] == 1
    assert body["total_snapshots"] == 2
    assert body["policy"]["archived_lane_auto_keep_per_scope"] == 3
    assert body["policy"]["archived_lane_keep_per_project"] == 3


def test_list_all_snapshots_filters_exact_archived_scope(monkeypatch) -> None:
    _patch_snapshot_libs(monkeypatch)

    response = client.get(
        "/api/snapshots",
        params={
            "project_id": "summitflow",
            "scope_type": "lane",
            "scope_name": "task-old",
            "include_archived": "true",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["scope_name"] == "task-old"
    assert body[0]["source"] == "auto-baseline"
