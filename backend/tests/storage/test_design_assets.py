"""Storage tests for first-class design assets."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.storage import design_assets
from app.storage.connection import get_connection


@pytest.fixture
def asset_project(db_schema_initialized: None) -> Generator[str]:
    """Provision a test project for asset tests."""
    project_id = "test-design-assets"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Design Assets", "http://localhost:3001"),
        )
        conn.commit()
    yield project_id
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def test_create_and_query_design_asset(asset_project: str) -> None:
    """Persist an asset and query it back."""
    asset = design_assets.create_asset(
        project_id=asset_project,
        name="Hero Sprite",
        description="Playable character base pose",
        asset_type="sprite",
        workflow="production",
        prompt="Single hero sprite with bold silhouette",
        width=512,
        height=512,
        background="transparent",
        transparent_background=True,
        tags=["hero", "player"],
        metadata={"source": "test"},
    )

    fetched = design_assets.get_asset(asset_project, asset["asset_id"])
    assert fetched is not None
    assert fetched["name"] == "Hero Sprite"
    assert fetched["tags"] == ["hero", "player"]



def test_update_design_asset_status_can_clear_review_state(asset_project: str) -> None:
    """Approving then resetting an asset clears approval metadata."""
    asset = design_assets.create_asset(
        project_id=asset_project,
        name="Concept Frame",
        asset_type="concept_art",
        workflow="concept",
        prompt="Tactical survival concept frame",
        width=1024,
        height=1024,
        background="scene",
        transparent_background=False,
    )

    approved = design_assets.update_asset_status(
        asset_project,
        asset["asset_id"],
        "approved",
        approved_by="codex",
    )
    assert approved is not None
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "codex"
    assert approved["approved_at"] is not None

    reset = design_assets.update_asset_status(
        asset_project,
        asset["asset_id"],
        "generated",
        approved_by="codex",
    )
    assert reset is not None
    assert reset["status"] == "generated"
    assert reset["approved_by"] is None
    assert reset["approved_at"] is None

def test_list_design_assets_filters_by_type(asset_project: str) -> None:
    """List assets by type."""
    design_assets.create_asset(
        project_id=asset_project,
        name="Enemy Portrait",
        asset_type="portrait",
        workflow="concept",
        prompt="Portrait of a masked villain",
        width=1024,
        height=1024,
        background="scene",
        transparent_background=False,
    )
    design_assets.create_asset(
        project_id=asset_project,
        name="Forest Background",
        asset_type="environment",
        workflow="production",
        prompt="Dense forest battle backdrop",
        width=1920,
        height=1080,
        background="scene",
        transparent_background=False,
    )

    items, total = design_assets.list_assets(asset_project, asset_type="environment")
    assert total >= 1
    assert all(item["asset_type"] == "environment" for item in items)



def test_design_asset_ratings_are_average_based_and_sortable(asset_project: str) -> None:
    """Each viewer has one star rating; lists can sort by rating aggregates."""
    first = design_assets.create_asset(
        project_id=asset_project,
        name="First Concept",
        asset_type="concept_art",
        workflow="concept",
        prompt="First art direction",
        width=1024,
        height=1024,
        background="scene",
        transparent_background=False,
    )
    second = design_assets.create_asset(
        project_id=asset_project,
        name="Second Concept",
        asset_type="concept_art",
        workflow="concept",
        prompt="Second art direction",
        width=1024,
        height=1024,
        background="scene",
        transparent_background=False,
    )

    assert (
        design_assets.set_asset_rating(
            asset_project,
            first["asset_id"],
            5,
            voter_key="reviewer-a",
        )
        is not None
    )
    assert (
        design_assets.set_asset_rating(
            asset_project,
            first["asset_id"],
            3,
            voter_key="reviewer-b",
        )
        is not None
    )
    assert (
        design_assets.set_asset_rating(
            asset_project,
            second["asset_id"],
            2,
            voter_key="reviewer-c",
        )
        is not None
    )

    fetched = design_assets.get_asset(
        asset_project,
        first["asset_id"],
        voter_key="reviewer-a",
    )
    assert fetched is not None
    assert fetched["rating_average"] == 4
    assert fetched["rating_count"] == 2
    assert fetched["user_rating"] == 5

    cleared = design_assets.set_asset_rating(
        asset_project,
        first["asset_id"],
        0,
        voter_key="reviewer-a",
    )
    assert cleared is not None
    assert cleared["rating_average"] == 3
    assert cleared["rating_count"] == 1
    assert cleared["user_rating"] == 0

    by_rating, _ = design_assets.list_assets(asset_project, sort_by="rating_average")
    assert by_rating[0]["asset_id"] == first["asset_id"]


def test_design_asset_rating_rejects_invalid_value(asset_project: str) -> None:
    """Ratings must be between 0 and 5."""
    asset = design_assets.create_asset(
        project_id=asset_project,
        name="Vote Validation Concept",
        asset_type="concept_art",
        workflow="concept",
        prompt="Validate vote",
        width=1024,
        height=1024,
        background="scene",
        transparent_background=False,
    )

    with pytest.raises(ValueError, match="Invalid asset rating"):
        design_assets.set_asset_rating(
            asset_project,
            asset["asset_id"],
            6,
            voter_key="reviewer-a",
        )


def test_design_asset_comments_are_counted_editable_and_deletable(
    asset_project: str,
) -> None:
    """Comments are per-user, counted on assets, and owner-editable."""
    asset = design_assets.create_asset(
        project_id=asset_project,
        name="Commented Concept",
        asset_type="concept_art",
        workflow="concept",
        prompt="Comment target",
        width=1024,
        height=1024,
        background="scene",
        transparent_background=False,
    )

    first = design_assets.create_asset_comment(
        asset_project,
        asset["asset_id"],
        "Looks strong.",
        author_email="reviewer-a@example.com",
    )
    second = design_assets.create_asset_comment(
        asset_project,
        asset["asset_id"],
        "Try more contrast.",
        author_email="reviewer-b@example.com",
    )
    assert first is not None
    assert second is not None

    fetched = design_assets.get_asset(asset_project, asset["asset_id"])
    assert fetched is not None
    assert fetched["comment_count"] == 2
    comments = design_assets.list_asset_comments(asset_project, asset["asset_id"])
    assert [comment["author_email"] for comment in comments] == [
        "reviewer-a@example.com",
        "reviewer-b@example.com",
    ]

    updated = design_assets.update_asset_comment(
        asset_project,
        asset["asset_id"],
        first["id"],
        "Looks excellent.",
        author_email="reviewer-a@example.com",
    )
    assert updated is not None
    assert updated["body"] == "Looks excellent."
    assert (
        design_assets.update_asset_comment(
            asset_project,
            asset["asset_id"],
            first["id"],
            "Wrong owner edit",
            author_email="reviewer-b@example.com",
        )
        is None
    )

    assert design_assets.delete_asset_comment(
        asset_project,
        asset["asset_id"],
        second["id"],
        author_email="reviewer-b@example.com",
    )
    fetched = design_assets.get_asset(asset_project, asset["asset_id"])
    assert fetched is not None
    assert fetched["comment_count"] == 1


def test_design_asset_comment_rejects_empty_body(asset_project: str) -> None:
    """Comments must contain visible text."""
    asset = design_assets.create_asset(
        project_id=asset_project,
        name="Comment Validation Concept",
        asset_type="concept_art",
        workflow="concept",
        prompt="Validate comment",
        width=1024,
        height=1024,
        background="scene",
        transparent_background=False,
    )

    with pytest.raises(ValueError, match="Comment cannot be empty"):
        design_assets.create_asset_comment(
            asset_project,
            asset["asset_id"],
            "   ",
            author_email="reviewer-a@example.com",
        )

def test_create_export_for_asset(asset_project: str) -> None:
    """Persist export metadata linked to an asset."""
    asset = design_assets.create_asset(
        project_id=asset_project,
        name="Boss Sheet",
        asset_type="sprite_sheet",
        workflow="production",
        prompt="Boss sprite sheet",
        width=1024,
        height=512,
        background="transparent",
        transparent_background=True,
        sheet_columns=4,
        sheet_rows=2,
        frame_width=256,
        frame_height=256,
    )
    export_record = design_assets.create_asset_export(
        asset["id"],
        "sprite_frames",
        "/tmp/test-export",
        manifest_path="/tmp/test-export/atlas.json",
        metadata={"frame_count": 8},
    )

    exports = design_assets.list_asset_exports(asset_project, asset["asset_id"])
    assert export_record["export_id"] == exports[0]["export_id"]
    assert exports[0]["metadata"]["frame_count"] == 8
