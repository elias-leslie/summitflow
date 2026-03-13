"""Tests for explorer symbol storage."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.storage import explorer_symbols
from app.storage.connection import get_connection


@pytest.fixture
def cleanup_symbols(db_schema_initialized: None, project_id: str) -> Generator[str]:
    """Remove symbol rows for the test project after each test."""
    yield project_id
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM explorer_symbols WHERE project_id = %s", (project_id,))
        conn.commit()


def _make_symbol(
    *,
    symbol_id: str,
    name: str,
    qualified_name: str | None = None,
    kind: str = "function",
    signature: str | None = None,
    language: str = "python",
    start_line: int = 1,
    end_line: int = 3,
    byte_offset: int = 0,
    byte_length: int = 42,
    content_hash: str = "hash-1",
    summary: str | None = None,
    keywords: list[str] | None = None,
) -> dict[str, object]:
    """Build a symbol payload."""
    return {
        "symbol_id": symbol_id,
        "name": name,
        "qualified_name": qualified_name or name,
        "kind": kind,
        "signature": signature or f"def {name}() -> None",
        "language": language,
        "start_line": start_line,
        "end_line": end_line,
        "byte_offset": byte_offset,
        "byte_length": byte_length,
        "content_hash": content_hash,
        "summary": summary,
        "keywords": keywords or [],
    }


class TestReplaceFileSymbols:
    """Tests for file-scoped symbol replacement."""

    def test_replace_file_symbols_inserts_rows(self, cleanup_symbols: str) -> None:
        """Replacing symbols for a file inserts retrievable rows."""
        count = explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            "backend/app/api/files.py",
            [
                _make_symbol(
                    symbol_id="backend/app/api/files.py::get_file_tree#function",
                    name="get_file_tree",
                    start_line=24,
                    end_line=38,
                    summary="List directory entries for file tree navigation.",
                    keywords=["files", "tree"],
                ),
                _make_symbol(
                    symbol_id="backend/app/api/files.py::get_file_content#function",
                    name="get_file_content",
                    start_line=41,
                    end_line=56,
                    summary="Read file content with language detection.",
                    keywords=["files", "content"],
                ),
            ],
        )

        assert count == 2

        rows = explorer_symbols.list_symbols_for_file(cleanup_symbols, "backend/app/api/files.py")
        assert [row["name"] for row in rows] == ["get_file_tree", "get_file_content"]
        assert rows[0]["summary"] == "List directory entries for file tree navigation."
        assert rows[1]["keywords"] == ["files", "content"]

    def test_replace_file_symbols_replaces_stale_rows(self, cleanup_symbols: str) -> None:
        """Replacing a file's symbols removes rows absent from the new snapshot."""
        file_path = "backend/app/api/files.py"
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            file_path,
            [
                _make_symbol(symbol_id=f"{file_path}::old#function", name="old"),
                _make_symbol(symbol_id=f"{file_path}::keep#function", name="keep"),
            ],
        )

        count = explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            file_path,
            [
                _make_symbol(
                    symbol_id=f"{file_path}::keep#function",
                    name="keep",
                    summary="Updated summary",
                    content_hash="hash-2",
                ),
                _make_symbol(symbol_id=f"{file_path}::new#function", name="new"),
            ],
        )

        assert count == 2
        rows = explorer_symbols.list_symbols_for_file(cleanup_symbols, file_path)
        assert [row["symbol_id"] for row in rows] == [
            f"{file_path}::keep#function",
            f"{file_path}::new#function",
        ]
        assert rows[0]["summary"] == "Updated summary"
        assert explorer_symbols.get_symbol(cleanup_symbols, f"{file_path}::old#function") is None

    def test_replace_file_symbols_empty_snapshot_clears_file_rows(self, cleanup_symbols: str) -> None:
        """An empty snapshot removes all symbols for the file."""
        file_path = "backend/app/api/files.py"
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            file_path,
            [_make_symbol(symbol_id=f"{file_path}::get_file_tree#function", name="get_file_tree")],
        )

        count = explorer_symbols.replace_file_symbols(cleanup_symbols, file_path, [])

        assert count == 0
        assert explorer_symbols.list_symbols_for_file(cleanup_symbols, file_path) == []


class TestLookupAndSearch:
    """Tests for explorer symbol lookup and search."""

    def test_get_symbol_returns_symbol_record(self, cleanup_symbols: str) -> None:
        """A stored symbol can be fetched by stable symbol id."""
        symbol_id = "backend/app/api/agent_hub.py::proxy_complete#function"
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            "backend/app/api/agent_hub.py",
            [
                _make_symbol(
                    symbol_id=symbol_id,
                    name="proxy_complete",
                    qualified_name="proxy_complete",
                    signature="async def proxy_complete(request: Request) -> StreamingResponse",
                    start_line=232,
                    end_line=251,
                    summary="Proxy streaming completion request to Agent Hub.",
                    keywords=["agent-hub", "streaming"],
                )
            ],
        )

        record = explorer_symbols.get_symbol(cleanup_symbols, symbol_id)

        assert record is not None
        assert record["file_path"] == "backend/app/api/agent_hub.py"
        assert record["start_line"] == 232
        assert record["summary"] == "Proxy streaming completion request to Agent Hub."

    def test_search_symbols_matches_name_and_summary(self, cleanup_symbols: str) -> None:
        """Search matches exact names first, then summary and qualified name text."""
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            "backend/app/api/agent_hub.py",
            [
                _make_symbol(
                    symbol_id="backend/app/api/agent_hub.py::proxy_complete#function",
                    name="proxy_complete",
                    signature="async def proxy_complete(request: Request) -> StreamingResponse",
                    summary="Proxy streaming completion request to Agent Hub.",
                    keywords=["agent-hub", "streaming"],
                ),
                _make_symbol(
                    symbol_id="backend/app/api/agent_hub.py::get_session#function",
                    name="get_session",
                    summary="Proxy to Agent Hub to get session data.",
                    keywords=["agent-hub", "session"],
                ),
            ],
        )

        by_name = explorer_symbols.search_symbols(cleanup_symbols, "proxy_complete")
        by_summary = explorer_symbols.search_symbols(cleanup_symbols, "session data")

        assert by_name[0]["symbol_id"] == "backend/app/api/agent_hub.py::proxy_complete#function"
        assert by_summary[0]["symbol_id"] == "backend/app/api/agent_hub.py::get_session#function"

    def test_search_symbols_filters_by_language_and_kind(self, cleanup_symbols: str) -> None:
        """Search filters down to matching language and symbol kind."""
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            "frontend/app/projects/[id]/files/FilesClient.tsx",
            [
                _make_symbol(
                    symbol_id="frontend/app/projects/[id]/files/FilesClient.tsx::FilesClient#function",
                    name="FilesClient",
                    kind="function",
                    language="tsx",
                    signature="function FilesClient(): React.ReactElement",
                ),
                _make_symbol(
                    symbol_id="frontend/app/projects/[id]/files/FilesClient.tsx::FilesClientProps#type",
                    name="FilesClientProps",
                    kind="type",
                    language="tsx",
                    signature="interface FilesClientProps",
                ),
            ],
        )

        rows = explorer_symbols.search_symbols(
            cleanup_symbols,
            "FilesClient",
            language="tsx",
            kind="function",
        )

        assert [row["symbol_id"] for row in rows] == [
            "frontend/app/projects/[id]/files/FilesClient.tsx::FilesClient#function"
        ]


class TestSearchSymbolsByFilePath:
    """Search should match file_path so module-name queries find symbols."""

    def test_search_by_module_name_finds_symbols_in_file(self, cleanup_symbols: str) -> None:
        """Searching 'test_precision_query' should find symbols in that file."""
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            "backend/tests/services/test_precision_query.py",
            [
                _make_symbol(
                    symbol_id="backend/tests/services/test_precision_query.py::TestHasPathSegments#class",
                    name="TestHasPathSegments",
                    kind="class",
                    summary="Tests for path segment detection.",
                ),
                _make_symbol(
                    symbol_id="backend/tests/services/test_precision_query.py::TestHasPathSegments.test_detects_slash_paths#method",
                    name="test_detects_slash_paths",
                    qualified_name="TestHasPathSegments.test_detects_slash_paths",
                    kind="method",
                ),
            ],
        )

        results = explorer_symbols.search_symbols(cleanup_symbols, "test_precision_query")
        assert len(results) >= 1
        assert all("test_precision_query" in r["file_path"] for r in results)

    def test_search_conftest_finds_conftest_symbols(self, cleanup_symbols: str) -> None:
        """Searching 'conftest' should find symbols in conftest.py files."""
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            "backend/tests/conftest.py",
            [
                _make_symbol(
                    symbol_id="backend/tests/conftest.py::db_connection#function",
                    name="db_connection",
                    summary="Database connection fixture.",
                ),
            ],
        )

        results = explorer_symbols.search_symbols(cleanup_symbols, "conftest")
        assert len(results) >= 1
        assert results[0]["file_path"] == "backend/tests/conftest.py"


class TestSymbolStats:
    """Tests for aggregate symbol index stats."""

    def test_get_symbol_stats_returns_count_and_last_updated(self, cleanup_symbols: str) -> None:
        explorer_symbols.replace_file_symbols(
            cleanup_symbols,
            "backend/app/api/files.py",
            [
                _make_symbol(
                    symbol_id="backend/app/api/files.py::get_file_tree#function",
                    name="get_file_tree",
                )
            ],
        )

        stats = explorer_symbols.get_symbol_stats(cleanup_symbols)

        assert stats["count"] == 1
        assert stats["last_updated"] is not None
