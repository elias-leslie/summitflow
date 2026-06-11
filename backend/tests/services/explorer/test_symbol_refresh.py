"""Tests for targeted symbol refresh of changed files."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from app.services.explorer.symbol_refresh import refresh_symbols_for_paths
from app.storage import explorer_symbols
from app.storage.connection import get_connection


@pytest.fixture
def refresh_project(db_schema_initialized: None, tmp_path: Path) -> Generator[tuple[str, Path]]:
    """Create a project rooted at a temporary directory."""
    project_id = "symbol-refresh-project"
    root = tmp_path / "repo"
    root.mkdir()

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET root_path = EXCLUDED.root_path
            """,
            (project_id, "Symbol Refresh Project", "http://localhost:3001", str(root)),
        )
        conn.commit()

    yield project_id, root

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM explorer_symbols WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def _write_module(root: Path, rel_path: str, body: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class TestRefreshSymbolsForPaths:
    """Tests for refresh_symbols_for_paths."""

    def test_indexes_new_file_symbols(self, refresh_project: tuple[str, Path]) -> None:
        project_id, root = refresh_project
        _write_module(root, "backend/fresh.py", "def qqzz_fresh_symbol() -> None:\n    return None\n")

        result = refresh_symbols_for_paths(project_id, ["backend/fresh.py"])

        assert result == {"refreshed": 1, "cleared": 0, "skipped": 0}
        rows = explorer_symbols.list_symbols_for_file(project_id, "backend/fresh.py")
        assert [row["name"] for row in rows] == ["qqzz_fresh_symbol"]

    def test_clears_symbols_for_deleted_file(self, refresh_project: tuple[str, Path]) -> None:
        project_id, root = refresh_project
        _write_module(root, "backend/gone.py", "def stale_symbol() -> None:\n    return None\n")
        refresh_symbols_for_paths(project_id, ["backend/gone.py"])
        (root / "backend" / "gone.py").unlink()

        result = refresh_symbols_for_paths(project_id, ["backend/gone.py"])

        assert result == {"refreshed": 0, "cleared": 1, "skipped": 0}
        assert explorer_symbols.list_symbols_for_file(project_id, "backend/gone.py") == []

    def test_skips_unsupported_traversal_and_blank_paths(self, refresh_project: tuple[str, Path]) -> None:
        project_id, root = refresh_project
        _write_module(root, "notes.md", "# notes\n")

        result = refresh_symbols_for_paths(project_id, ["notes.md", "../outside.py", ""])

        assert result == {"refreshed": 0, "cleared": 0, "skipped": 3}

    def test_unknown_project_skips_everything(self, db_schema_initialized: None) -> None:
        result = refresh_symbols_for_paths("qqzz-no-such-project", ["a.py"])

        assert result == {"refreshed": 0, "cleared": 0, "skipped": 1}

    def test_deduplicates_repeated_paths(self, refresh_project: tuple[str, Path]) -> None:
        project_id, root = refresh_project
        _write_module(root, "backend/twice.py", "def once_only() -> None:\n    return None\n")

        result = refresh_symbols_for_paths(project_id, ["backend/twice.py", "backend/twice.py"])

        assert result == {"refreshed": 1, "cleared": 0, "skipped": 0}
