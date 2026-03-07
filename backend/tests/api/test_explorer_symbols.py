"""Tests for explorer symbol retrieval endpoints."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.explorer.types.files import FileScanner
from app.storage.connection import get_connection


@pytest.fixture
def symbol_api_project(
    db_schema_initialized: None,
    tmp_path: Path,
) -> Generator[str]:
    """Create a project rooted at a temporary repo-like directory with scanned symbols."""
    project_id = "symbol-api-project"
    root = tmp_path / "repo"
    backend_dir = root / "backend" / "app" / "api"
    frontend_dir = root / "frontend" / "app" / "projects" / "[id]" / "files"
    backend_dir.mkdir(parents=True)
    frontend_dir.mkdir(parents=True)

    (backend_dir / "files.py").write_text(
        '''
def get_file_tree(path: str) -> dict[str, str]:
    """List directory entries for file tree navigation."""
    return {"path": path}
''',
        encoding="utf-8",
    )
    (frontend_dir / "FilesClient.tsx").write_text(
        """
export function FilesClient(): React.ReactElement {
  return <div>Files</div>
}
""",
        encoding="utf-8",
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET root_path = EXCLUDED.root_path
            """,
            (project_id, "Symbol API Project", "http://localhost:3001", str(root)),
        )
        conn.commit()

    result = FileScanner(project_id).run()
    assert result.success is True

    yield project_id

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM explorer_symbols WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM explorer_entries WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


class TestExplorerSymbolSearchEndpoint:
    """Tests for GET /api/projects/{project_id}/explorer/symbols/search."""

    def test_search_symbols_returns_matches(
        self,
        client: TestClient,
        symbol_api_project: str,
    ) -> None:
        """Search should return matching symbols with metadata only."""
        response = client.get(
            f"/api/projects/{symbol_api_project}/explorer/symbols/search",
            params={"q": "get_file_tree"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "get_file_tree"
        assert data["count"] == 1
        assert data["items"][0]["symbol_id"] == "backend/app/api/files.py::get_file_tree#function"
        assert data["items"][0]["file_path"] == "backend/app/api/files.py"
        assert "source" not in data["items"][0]

    def test_search_symbols_applies_filters(
        self,
        client: TestClient,
        symbol_api_project: str,
    ) -> None:
        """Language and kind filters should narrow the result set."""
        response = client.get(
            f"/api/projects/{symbol_api_project}/explorer/symbols/search",
            params={"q": "FilesClient", "language": "tsx", "kind": "function"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "FilesClient"
        assert data["items"][0]["language"] == "tsx"
        assert data["items"][0]["kind"] == "function"


class TestExplorerSymbolDetailEndpoint:
    """Tests for GET /api/projects/{project_id}/explorer/symbols/detail."""

    def test_get_symbol_detail_returns_source_and_file_entry(
        self,
        client: TestClient,
        symbol_api_project: str,
    ) -> None:
        """Detail should return symbol metadata, sliced source, and linked file entry."""
        response = client.get(
            f"/api/projects/{symbol_api_project}/explorer/symbols/detail",
            params={"symbol_id": "backend/app/api/files.py::get_file_tree#function"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["symbol"]["name"] == "get_file_tree"
        assert "def get_file_tree" in data["source"]
        assert data["file_entry"]["path"] == "backend/app/api/files.py"
        assert data["file_entry"]["metadata"]["symbol_count"] == 1

    def test_get_symbol_detail_returns_404_for_missing_symbol(
        self,
        client: TestClient,
        symbol_api_project: str,
    ) -> None:
        """Missing symbols should return 404."""
        response = client.get(
            f"/api/projects/{symbol_api_project}/explorer/symbols/detail",
            params={"symbol_id": "missing::symbol#function"},
        )

        assert response.status_code == 404
        assert response.json()["message"] == "Symbol not found"
