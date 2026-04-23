from __future__ import annotations

from app.storage import route_evidence as route_evidence_store
from app.storage.connection import get_connection


def _anchor() -> dict[str, object]:
    return {
        "x": 120,
        "y": 240,
        "scroll_x": 0,
        "scroll_y": 480,
        "viewport_width": 1440,
        "viewport_height": 900,
        "bbox": {
            "left": 100,
            "top": 220,
            "width": 80,
            "height": 24,
        },
    }


def _clear_route_evidence(project_id: str) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM route_evidence WHERE project_id = %s", (project_id,))
        conn.commit()


def test_normalize_page_key_strips_query_hash_and_trailing_slash() -> None:
    assert route_evidence_store.normalize_page_key("/design/?tab=1#comment") == "/design"
    assert route_evidence_store.normalize_page_key("/design#comment") == "/design"
    assert route_evidence_store.normalize_page_key("/") == "/"


def test_create_and_list_route_evidence_normalize_page_keys(ensure_test_project: str) -> None:
    project_id = ensure_test_project
    _clear_route_evidence(project_id)

    created = route_evidence_store.create_route_evidence(
        project_id=project_id,
        page_key="/design/?tab=grid#pin-1",
        page_url_snapshot="http://localhost:3001/design?tab=grid#pin-1",
        comment="Keep this toolbar tighter.",
        selector='[data-testid="toolbar"]',
        anchor=_anchor(),
        created_by_display="Elias",
    )

    listed = route_evidence_store.list_route_evidence(
        project_id=project_id,
        page_key="/design/",
        limit=10,
    )

    assert created["page_key"] == "/design"
    assert created["created_by_kind"] == "user"
    assert listed[0]["evidence_id"] == created["evidence_id"]
    assert listed[0]["page_key"] == "/design"
    assert listed[0]["comment"] == "Keep this toolbar tighter."
    assert listed[0]["selector"] == '[data-testid="toolbar"]'


def test_get_page_evidence_summaries_returns_count_latest_and_recent_items(ensure_test_project: str) -> None:
    project_id = ensure_test_project
    _clear_route_evidence(project_id)

    route_evidence_store.create_route_evidence(
        project_id=project_id,
        page_key="/design/",
        page_url_snapshot=None,
        comment="First note",
        selector=None,
        anchor=_anchor(),
        created_by_display="Elias",
    )
    route_evidence_store.create_route_evidence(
        project_id=project_id,
        page_key="/design",
        page_url_snapshot=None,
        comment="Second note",
        selector='[data-testid="hero"]',
        anchor=_anchor(),
        created_by_display=None,
    )

    summaries = route_evidence_store.get_page_evidence_summaries(
        project_id=project_id,
        page_keys=["/design", "/missing"],
        recent_limit=10,
    )

    design = summaries["/design"]
    missing = summaries["/missing"]

    assert design["evidence_count"] == 2
    assert design["last_evidence_at"] is not None
    assert [item["comment"] for item in design["recent_items"]] == [
        "Second note",
        "First note",
    ]
    assert all(item["page_key"] == "/design" for item in design["recent_items"])

    assert missing["evidence_count"] == 0
    assert missing["last_evidence_at"] is None
    assert missing["recent_items"] == []
