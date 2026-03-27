"""Tests for notes API endpoints."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.storage import note_versions
from app.storage import notes as note_store
from app.storage.connection import get_connection


@pytest.fixture
def note_factory(db_schema_initialized: None) -> Generator[Callable[..., dict[str, Any]]]:
    """Create notes and clean them up after each test."""
    created_note_ids: list[str] = []

    def _create_note(**overrides: Any) -> dict[str, Any]:
        note = note_store.create_note(
            title=overrides.get("title", "Sprint"),
            content=overrides.get("content", "Original content"),
            project_scope=overrides.get("project_scope", "notes-api-test"),
            note_type=overrides.get("note_type", "note"),
            tags=overrides.get("tags", ["alpha"]),
            pinned=overrides.get("pinned", False),
            metadata=overrides.get("metadata"),
        )
        created_note_ids.append(note["id"])
        return note

    yield _create_note

    for note_id in created_note_ids:
        note_store.delete_note(note_id)


class TestNotesVersioning:
    """Tests for automatic note version checkpoints."""

    def test_update_note_creates_edit_checkpoint_on_first_meaningful_edit(
        self, client: TestClient, note_factory: Callable[..., dict[str, Any]]
    ) -> None:
        """First content edit snapshots the prior note state."""
        note = note_factory()

        response = client.patch(
            f"/api/notes/{note['id']}",
            json={"content": "Updated content"},
        )

        assert response.status_code == 200
        versions = note_versions.list_versions(note["id"])
        assert len(versions) == 1
        assert versions[0]["change_source"] == "edit_checkpoint"
        assert versions[0]["title"] == "Sprint"
        assert versions[0]["content"] == "Original content"
        assert versions[0]["tags"] == ["alpha"]

    def test_update_note_does_not_checkpoint_non_content_updates(
        self, client: TestClient, note_factory: Callable[..., dict[str, Any]]
    ) -> None:
        """Pin-only edits should not create a content version."""
        note = note_factory()

        response = client.patch(
            f"/api/notes/{note['id']}",
            json={"pinned": True},
        )

        assert response.status_code == 200
        assert note_versions.list_versions(note["id"]) == []

    def test_update_note_coalesces_rapid_edit_checkpoints(
        self, client: TestClient, note_factory: Callable[..., dict[str, Any]]
    ) -> None:
        """Rapid successive edits reuse the recent checkpoint."""
        note = note_factory()

        first = client.patch(f"/api/notes/{note['id']}", json={"content": "Updated once"})
        second = client.patch(f"/api/notes/{note['id']}", json={"content": "Updated twice"})

        assert first.status_code == 200
        assert second.status_code == 200
        versions = note_versions.list_versions(note["id"])
        assert len(versions) == 1
        assert versions[0]["content"] == "Original content"

    def test_update_note_creates_new_checkpoint_after_cooldown(
        self, client: TestClient, note_factory: Callable[..., dict[str, Any]]
    ) -> None:
        """Older checkpoints should allow a fresh snapshot of the current state."""
        note = note_factory()

        first = client.patch(f"/api/notes/{note['id']}", json={"content": "Updated once"})
        assert first.status_code == 200

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE note_versions
                SET created_at = NOW() - INTERVAL '10 minutes'
                WHERE note_id = %s
                """,
                (note["id"],),
            )
            conn.commit()

        second = client.patch(f"/api/notes/{note['id']}", json={"content": "Updated twice"})

        assert second.status_code == 200
        versions = note_versions.list_versions(note["id"])
        assert len(versions) == 2
        assert versions[0]["change_source"] == "edit_checkpoint"
        assert versions[0]["content"] == "Updated once"
        assert versions[1]["content"] == "Original content"
