"""Tests for explorer symbol retrieval endpoints."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.explorer.types.endpoints import EndpointScanner
from app.services.explorer.types.files import FileScanner
from app.services.explorer.types.pages import PageScanner
from app.storage.connection import get_connection


def _create_test_repo(root: Path) -> None:
    """Populate *root* with a minimal backend + frontend file tree."""
    backend_dir = root / "backend" / "app" / "api"
    frontend_dir = root / "frontend" / "app" / "projects" / "[id]" / "files"
    backend_dir.mkdir(parents=True)
    frontend_dir.mkdir(parents=True)

    (backend_dir / "files.py").write_text(
        '''
from fastapi import APIRouter

router = APIRouter(prefix="/files")


@router.get("/tree")
def get_file_tree(path: str) -> dict[str, str]:
    """List directory entries for file tree navigation."""
    marker = "special fallback token"
    return {"path": path, "marker": marker}
''',
        encoding="utf-8",
    )
    (frontend_dir / "page.tsx").write_text(
        """
export default function FilesPage(): React.ReactElement {
  return <FilesClient />
}
""",
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


def _cleanup_test_project(project_id: str) -> None:
    """Remove all DB rows created by the *symbol_api_project* fixture."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM explorer_symbols WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM explorer_entries WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


@pytest.fixture
def symbol_api_project(
    db_schema_initialized: None,
    tmp_path: Path,
) -> Generator[str]:
    """Create a project rooted at a temporary repo-like directory with scanned symbols."""
    project_id = "symbol-api-project"
    root = tmp_path / "repo"

    _create_test_repo(root)

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
    assert result.success
    assert EndpointScanner(project_id).run().success
    assert PageScanner(project_id).run().success

    yield project_id

    _cleanup_test_project(project_id)


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

    def test_precision_search_returns_prompt_context_and_metadata(
        self,
        client: TestClient,
        symbol_api_project: str,
    ) -> None:
        """Precision search should return prompt-ready context plus telemetry."""
        response = client.get(
            f"/api/projects/{symbol_api_project}/explorer/precision-search",
            params={"q": "get_file_tree", "budget": 1200},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "get_file_tree"
        assert "Precision Code Search: symbol-first" in data["prompt_context"]
        assert "`get_file_tree`" in data["prompt_context"]
        assert data["metadata"]["used_symbol_first"] is True
        assert data["metadata"]["symbol_count"] >= 1

    def test_search_text_returns_matching_lines(
        self,
        client: TestClient,
        symbol_api_project: str,
    ) -> None:
        """Text search should return matching file lines from indexed files."""
        response = client.get(
            f"/api/projects/{symbol_api_project}/explorer/text/search",
            params={"q": "special fallback token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "special fallback token"
        assert data["count"] == 1
        assert data["files_searched"] >= 1
        assert data["items"][0]["path"] == "backend/app/api/files.py"
        assert data["items"][0]["line"] >= 1
        assert "special fallback token" in data["items"][0]["content"]

    def test_precision_search_uses_text_fallback_on_symbol_miss(
        self,
        client: TestClient,
        symbol_api_project: str,
    ) -> None:
        """Precision search should use text fallback when symbol search misses."""
        response = client.get(
            f"/api/projects/{symbol_api_project}/explorer/precision-search",
            params={"q": "special fallback token", "budget": 1200},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "special fallback token"
        assert "Precision Code Search: text-fallback" in data["prompt_context"]
        assert "## Relevant Text Matches" in data["prompt_context"]
        assert "backend/app/api/files.py" in data["prompt_context"]
        assert data["metadata"]["used_symbol_first"] is False
        assert data["metadata"]["used_fallback"] is True
        assert data["metadata"]["fallback_mode"] == "text"
        assert data["metadata"]["text_match_count"] == 1


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
        assert [entry["path"] for entry in data["related_entries"]] == ["GET /files/tree"]

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
