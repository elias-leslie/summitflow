from __future__ import annotations

from app.storage import explorer_entries
from app.storage.connection import get_connection


def _anchor() -> dict[str, object]:
    return {
        "x": 80,
        "y": 160,
        "scroll_x": 0,
        "scroll_y": 300,
        "viewport_width": 1280,
        "viewport_height": 720,
    }


def _clear_project_rows(project_id: str) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM route_evidence WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM explorer_entries WHERE project_id = %s", (project_id,))
        conn.commit()


def test_create_route_evidence_returns_expected_contract(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_project_rows(project_id)

    response = client.post(
        f"/api/projects/{project_id}/route-evidence",
        headers={"X-User-Name": "Elias Leslie"},
        json={
            "page_key": "/projects/summitflow/design/?tab=grid#top",
            "page_url_snapshot": "http://localhost:3001/projects/summitflow/design?tab=grid#top",
            "comment": "Tighten the top bar spacing.",
            "selector": '[data-testid="top-bar"]',
            "anchor": _anchor(),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["evidence_id"].startswith("evidence-")
    assert body["project_id"] == project_id
    assert body["page_key"] == "/projects/summitflow/design"
    assert body["page_url_snapshot"] == "http://localhost:3001/projects/summitflow/design?tab=grid#top"
    assert body["comment"] == "Tighten the top bar spacing."
    assert body["selector"] == '[data-testid="top-bar"]'
    assert body["anchor"]["x"] == 80
    assert body["created_by_kind"] == "user"
    assert body["created_by_display"] == "Elias Leslie"
    assert body["created_at"] is not None


def test_route_evidence_list_is_newest_first_and_uses_normalized_page_key(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_project_rows(project_id)

    first = client.post(
        f"/api/projects/{project_id}/route-evidence",
        json={
            "page_key": "/design/",
            "comment": "First note",
            "selector": None,
            "anchor": _anchor(),
        },
    )
    second = client.post(
        f"/api/projects/{project_id}/route-evidence",
        json={
            "page_key": "/design?tab=review",
            "comment": "Second note",
            "selector": '[data-testid="hero"]',
            "anchor": _anchor(),
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201

    response = client.get(
        f"/api/projects/{project_id}/route-evidence",
        params={"page_key": "/design/", "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["comment"] for item in body] == ["Second note", "First note"]
    assert all(item["page_key"] == "/design" for item in body)


def test_route_evidence_rejects_empty_comment_and_malformed_anchor(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_project_rows(project_id)

    empty_comment = client.post(
        f"/api/projects/{project_id}/route-evidence",
        json={
            "page_key": "/design",
            "comment": "   ",
            "anchor": _anchor(),
        },
    )
    malformed_anchor = client.post(
        f"/api/projects/{project_id}/route-evidence",
        json={
            "page_key": "/design",
            "comment": "Bad anchor",
            "anchor": {
                **_anchor(),
                "viewport_width": -1,
            },
        },
    )

    assert empty_comment.status_code == 400
    assert malformed_anchor.status_code == 400


def test_explorer_page_entries_include_route_evidence_summary_and_recent_items(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_project_rows(project_id)

    explorer_entries.upsert_entries(
        project_id,
        "page",
        [
            {
                "path": "/design",
                "name": "Design",
                "health_status": "healthy",
                "metadata": {"source_file": "frontend/app/design/page.tsx"},
            },
            {
                "path": "/other",
                "name": "Other",
                "health_status": "healthy",
                "metadata": {"source_file": "frontend/app/other/page.tsx"},
            },
        ],
    )

    created = client.post(
        f"/api/projects/{project_id}/route-evidence",
        json={
            "page_key": "/design/",
            "comment": "Evidence for design page",
            "selector": '[data-testid="design-shell"]',
            "anchor": _anchor(),
        },
    )
    assert created.status_code == 201

    response = client.get(
        f"/api/projects/{project_id}/explorer",
        params={"type": "page"},
    )

    assert response.status_code == 200
    entries = response.json()["entries"]
    by_path = {entry["path"]: entry for entry in entries}

    design_entry = by_path["/design"]
    other_entry = by_path["/other"]

    assert design_entry["evidence_count"] == 1
    assert design_entry["last_evidence_at"] is not None
    assert design_entry["metadata"]["recent_route_evidence"][0]["evidence_id"] == created.json()["evidence_id"]
    assert design_entry["metadata"]["recent_route_evidence"][0]["comment"] == "Evidence for design page"

    assert other_entry["evidence_count"] == 0
    assert other_entry["last_evidence_at"] is None
    assert other_entry["metadata"]["recent_route_evidence"] == []
