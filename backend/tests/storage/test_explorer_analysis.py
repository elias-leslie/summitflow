"""Tests for explorer analysis queries."""

from __future__ import annotations

from app.storage import explorer_analysis, explorer_entries, explorer_symbols
from app.storage.connection import get_connection


def _make_file_entry(path: str, *, priority: str = "high") -> dict[str, object]:
    """Build a refactorable file entry payload."""
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1],
        "health_status": "warning",
        "metadata": {
            "extension": ".py",
            "lines_of_code": 420,
            "function_count": 3,
            "class_count": 1,
            "complexity_score": 18.5,
            "refactor_priority": priority,
            "commit_count_90d": 6,
            "test_file_exists": False,
            "complexity_method": "heuristic",
            "health_flags": {"bloat": True},
            "refactor_issues": ["High complexity"],
        },
    }


def _make_symbol(
    file_path: str,
    symbol_id: str,
    name: str,
    *,
    qualified_name: str | None = None,
    kind: str = "function",
    start_line: int = 1,
    end_line: int = 10,
) -> dict[str, object]:
    """Build a stored symbol payload."""
    return {
        "symbol_id": symbol_id,
        "qualified_name": qualified_name or name,
        "name": name,
        "kind": kind,
        "signature": f"def {name}()",
        "language": "python",
        "start_line": start_line,
        "end_line": end_line,
        "byte_offset": 0,
        "byte_length": 32,
        "content_hash": f"hash-{name}",
        "summary": f"Summary for {name}",
        "keywords": [name],
    }


def test_get_refactor_targets_includes_top_symbols(
    db_schema_initialized: None,
) -> None:
    """Refactor targets should surface the leading indexed symbols for each file."""
    project_id = "explorer-analysis-project"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET root_path = EXCLUDED.root_path
            """,
            (project_id, "Explorer Analysis Project", "http://localhost:3001", "/tmp/analysis"),
        )
        conn.commit()

    file_path = "backend/app/services/heavy_service.py"
    explorer_entries.upsert_entries(project_id, "file", [_make_file_entry(file_path)])
    explorer_symbols.replace_file_symbols(
        project_id,
        file_path,
        [
            _make_symbol(file_path, f"{file_path}::HeavyService#class", "HeavyService", kind="class"),
            _make_symbol(
                file_path,
                f"{file_path}::HeavyService.run#function",
                "run",
                qualified_name="HeavyService.run",
                start_line=12,
                end_line=38,
            ),
        ],
    )

    result = explorer_analysis.get_refactor_targets(project_id, limit=5)

    assert result["targets"][0]["path"] == file_path
    assert result["targets"][0]["top_symbols"] == [
        {
            "symbol_id": f"{file_path}::HeavyService#class",
            "name": "HeavyService",
            "kind": "class",
            "qualified_name": "HeavyService",
            "start_line": 1,
            "end_line": 10,
        },
        {
            "symbol_id": f"{file_path}::HeavyService.run#function",
            "name": "run",
            "kind": "function",
            "qualified_name": "HeavyService.run",
            "start_line": 12,
            "end_line": 38,
        },
    ]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM explorer_symbols WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM explorer_entries WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()
