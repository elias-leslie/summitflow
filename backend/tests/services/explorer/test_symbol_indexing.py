"""Integration tests for explorer symbol indexing during file scans."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from app.services.explorer.types.files import FileScanner
from app.storage import explorer_symbols
from app.storage.connection import get_connection


@pytest.fixture
def symbol_project(db_schema_initialized: None, tmp_path: Path) -> Generator[tuple[str, Path]]:
    """Create a project rooted at a temporary repo-like directory."""
    project_id = "symbol-project"
    root = tmp_path / "repo"
    (root / "backend" / "app" / "api").mkdir(parents=True)
    (root / "frontend" / "app" / "projects" / "[id]" / "files").mkdir(parents=True)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET root_path = EXCLUDED.root_path
            """,
            (project_id, "Symbol Project", "http://localhost:3001", str(root)),
        )
        conn.commit()

    yield project_id, root

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM explorer_symbols WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM explorer_entries WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


class TestFileScannerSymbolIndexing:
    """Tests for symbol indexing integration in FileScanner."""

    def test_run_indexes_python_and_tsx_symbols(self, symbol_project: tuple[str, Path]) -> None:
        """A file scan should populate symbol rows for supported code files."""
        project_id, root = symbol_project
        (root / "backend" / "app" / "api" / "files.py").write_text(
            """
def get_file_tree(path: str) -> dict[str, str]:
    \"\"\"List files.\"\"\"
    return {"path": path}
""",
            encoding="utf-8",
        )
        (root / "frontend" / "app" / "projects" / "[id]" / "files" / "FilesClient.tsx").write_text(
            """
export function FilesClient(): React.ReactElement {
  return <div>Files</div>
}
""",
            encoding="utf-8",
        )

        result = FileScanner(project_id).run()

        assert result.success is True
        backend_symbols = explorer_symbols.list_symbols_for_file(project_id, "backend/app/api/files.py")
        frontend_symbols = explorer_symbols.list_symbols_for_file(
            project_id,
            "frontend/app/projects/[id]/files/FilesClient.tsx",
        )
        assert [symbol["name"] for symbol in backend_symbols] == ["get_file_tree"]
        assert [symbol["name"] for symbol in frontend_symbols] == ["FilesClient"]

    def test_rescan_removes_symbols_for_deleted_files(self, symbol_project: tuple[str, Path]) -> None:
        """A subsequent file scan should delete symbol rows for removed files."""
        project_id, root = symbol_project
        backend_file = root / "backend" / "app" / "api" / "files.py"
        backend_file.write_text(
            """
def get_file_tree(path: str) -> dict[str, str]:
    return {"path": path}
""",
            encoding="utf-8",
        )

        first = FileScanner(project_id).run()
        assert first.success is True
        assert explorer_symbols.get_symbol(
            project_id,
            "backend/app/api/files.py::get_file_tree#function",
        ) is not None

        backend_file.unlink()

        second = FileScanner(project_id).run()
        assert second.success is True
        assert explorer_symbols.get_symbol(
            project_id,
            "backend/app/api/files.py::get_file_tree#function",
        ) is None
