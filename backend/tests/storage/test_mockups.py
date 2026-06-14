"""Storage tests for UI mockups."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.storage import mockups
from app.storage.connection import get_connection


@pytest.fixture
def mockup_project(db_schema_initialized: None) -> Generator[str]:
    """Provision a test project for mockup tests."""
    project_id = "test-ui-mockups"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "UI Mockups", "http://localhost:3001"),
        )
        conn.commit()
    yield project_id
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def test_mockup_votes_are_cumulative_and_sortable(mockup_project: str) -> None:
    """Each click adds a vote; lists can sort by vote aggregates."""
    first = mockups.create_mockup(
        project_id=mockup_project,
        name="First UI Direction",
        mockup_type="page",
        description="First direction",
        content="<main>First</main>",
    )
    second = mockups.create_mockup(
        project_id=mockup_project,
        name="Second UI Direction",
        mockup_type="page",
        description="Second direction",
        content="<main>Second</main>",
    )

    assert mockups.create_mockup_vote(mockup_project, first["mockup_id"], "up") is not None
    assert mockups.create_mockup_vote(mockup_project, first["mockup_id"], "up") is not None
    assert mockups.create_mockup_vote(mockup_project, first["mockup_id"], "down") is not None
    assert mockups.create_mockup_vote(mockup_project, second["mockup_id"], "up") is not None

    fetched = mockups.get_mockup(mockup_project, first["mockup_id"])
    assert fetched is not None
    assert fetched["thumbs_up"] == 2
    assert fetched["thumbs_down"] == 1
    assert fetched["vote_score"] == 1

    by_up, _ = mockups.list_mockups(mockup_project, sort_by="thumbs_up")
    assert by_up[0]["mockup_id"] == first["mockup_id"]

    by_net, _ = mockups.list_mockups(mockup_project, sort_by="vote_score")
    assert by_net[0]["vote_score"] >= by_net[-1]["vote_score"]


def test_mockup_vote_rejects_invalid_direction(mockup_project: str) -> None:
    """Votes must be thumbs-up or thumbs-down."""
    mockup = mockups.create_mockup(
        project_id=mockup_project,
        name="Vote Validation UI",
        mockup_type="page",
        content="<main>Validate</main>",
    )

    with pytest.raises(ValueError, match="Invalid mockup vote"):
        mockups.create_mockup_vote(mockup_project, mockup["mockup_id"], "maybe")
