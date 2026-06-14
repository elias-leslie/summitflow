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


def test_mockup_ratings_are_average_based_and_sortable(mockup_project: str) -> None:
    """Each viewer has one star rating; lists can sort by rating aggregates."""
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

    assert (
        mockups.set_mockup_rating(
            mockup_project,
            first["mockup_id"],
            5,
            voter_key="reviewer-a",
        )
        is not None
    )
    assert (
        mockups.set_mockup_rating(
            mockup_project,
            first["mockup_id"],
            3,
            voter_key="reviewer-b",
        )
        is not None
    )
    assert (
        mockups.set_mockup_rating(
            mockup_project,
            second["mockup_id"],
            2,
            voter_key="reviewer-c",
        )
        is not None
    )

    fetched = mockups.get_mockup(
        mockup_project,
        first["mockup_id"],
        voter_key="reviewer-a",
    )
    assert fetched is not None
    assert fetched["rating_average"] == 4
    assert fetched["rating_count"] == 2
    assert fetched["user_rating"] == 5

    cleared = mockups.set_mockup_rating(
        mockup_project,
        first["mockup_id"],
        0,
        voter_key="reviewer-a",
    )
    assert cleared is not None
    assert cleared["rating_average"] == 3
    assert cleared["rating_count"] == 1
    assert cleared["user_rating"] == 0

    by_rating, _ = mockups.list_mockups(mockup_project, sort_by="rating_average")
    assert by_rating[0]["mockup_id"] == first["mockup_id"]


def test_mockup_rating_rejects_invalid_value(mockup_project: str) -> None:
    """Ratings must be between 0 and 5."""
    mockup = mockups.create_mockup(
        project_id=mockup_project,
        name="Vote Validation UI",
        mockup_type="page",
        content="<main>Validate</main>",
    )

    with pytest.raises(ValueError, match="Invalid mockup rating"):
        mockups.set_mockup_rating(
            mockup_project,
            mockup["mockup_id"],
            6,
            voter_key="reviewer-a",
        )
