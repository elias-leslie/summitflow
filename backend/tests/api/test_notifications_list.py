"""List/count totals for project-scoped and global notification endpoints."""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.storage import notifications as notification_store
from app.storage.connection import get_connection


@pytest.fixture
def three_notifications(test_project_id: str) -> Generator[list[str]]:
    run = uuid4().hex[:8]
    ids = [
        notification_store.create_notification(
            project_id=test_project_id,
            notification_type="system",
            title=f"List total check {index}",
            message="total regression",
            dedupe_key=f"list-total-check-{run}-{index}",
        )["id"]
        for index in range(3)
    ]
    yield ids
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM notifications WHERE id = ANY(%s)", (ids,))
        conn.commit()


def test_project_list_total_counts_all_matches_not_the_page(
    client: TestClient, test_project_id: str, three_notifications: list[str]
) -> None:
    resp = client.get(f"/api/projects/{test_project_id}/notifications", params={"limit": 1})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["total"] >= 3
    assert body["pending_count"] >= 3


def test_global_list_and_count_span_projects(
    client: TestClient, three_notifications: list[str]
) -> None:
    listing = client.get("/api/notifications", params={"limit": 2})
    count = client.get("/api/notifications/count")

    assert listing.status_code == 200 and count.status_code == 200
    assert len(listing.json()["items"]) == 2
    assert listing.json()["total"] >= 3
    assert count.json()["pending"] >= 3
    assert count.json()["pending"] == listing.json()["pending_count"]
