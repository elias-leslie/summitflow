"""Storage tests for first-class design assets."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.storage import design_assets
from app.storage.connection import get_connection


@pytest.fixture
def asset_project() -> Generator[str]:
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
