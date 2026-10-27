"""Integration tests for explorer symbol indexing during file scans."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from app.services.explorer.types.files import FileScanner
from app.storage import explorer_entries, explorer_symbols
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

        assert result.success
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
        assert first.success
        assert explorer_symbols.get_symbol(
            project_id,
            "backend/app/api/files.py::get_file_tree#function",
        ) is not None

        backend_file.unlink()

        second = FileScanner(project_id).run()
        assert second.success
        assert explorer_symbols.get_symbol(
            project_id,
            "backend/app/api/files.py::get_file_tree#function",
        ) is None

    def test_run_skips_tool_cache_and_vendor_dirs(self, symbol_project: tuple[str, Path]) -> None:
        """A file scan should not index tool output or dependency cache trees."""
        project_id, root = symbol_project
        source_file = root / "backend" / "app" / "api" / "files.py"
        source_file.write_text("def get_file_tree() -> dict[str, str]:\n    return {}\n", encoding="utf-8")
        cache_file = root / ".dev-tools" / "cleanroom-pydeps" / "site-packages" / "heavy.py"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("def cached_dependency() -> None:\n    pass\n", encoding="utf-8")

        result = FileScanner(project_id).run()

        assert result.success
        assert explorer_entries.get_entry(project_id, "file", "backend/app/api/files.py") is not None
        assert (
            explorer_entries.get_entry(
                project_id,
                "file",
                ".dev-tools/cleanroom-pydeps/site-packages/heavy.py",
            )
            is None
        )


def test_full_scan_preserves_inventory_but_excludes_evaluation_artifact_symbols(symbol_project: tuple[str, Path]) -> None:
    project_id, root = symbol_project
    for rel in ("tests/evaluation/runs/old/module.py", "tests/evaluation/test_runner.py", "src/snapshots/module.py"):
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("def target(): pass\n")
    assert FileScanner(project_id).run().success
    assert explorer_entries.get_entry(project_id, "file", "tests/evaluation/runs/old/module.py") is not None
    assert explorer_symbols.list_symbols_for_file(project_id, "tests/evaluation/runs/old/module.py") == []
    assert explorer_symbols.list_symbols_for_file(project_id, "tests/evaluation/test_runner.py")
    assert explorer_symbols.list_symbols_for_file(project_id, "src/snapshots/module.py")


@pytest.mark.parametrize("data_dir", ["data", "backend/data", "packages/foo/data"])
def test_full_scan_retains_refreshed_data_symbols_without_inventory_entries(symbol_project: tuple[str, Path], data_dir: str) -> None:
    from app.services.explorer.symbol_refresh import refresh_symbols_for_paths

    project_id, root = symbol_project
    rel_source = f"{data_dir}/source.py"
    source = root / rel_source
    source.parent.mkdir(parents=True)
    source.write_text("def data_source_target(): pass\n")
    artifact = root / "data/artifacts/source-scans/id/snapshot/module.py"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("def data_source_target(): pass\n")
    assert refresh_symbols_for_paths(project_id, [rel_source])["refreshed"] == 1
    assert FileScanner(project_id).run().success
    assert explorer_entries.get_entry(project_id, "file", rel_source) is None
    result = explorer_symbols.search_symbols_page(project_id, "data_source_target")
    assert result["count"] == 1
    assert [row["file_path"] for row in result["items"]] == [rel_source]


def test_full_symbol_scan_rejects_aliases_to_sensitive_and_artifact_targets(symbol_project: tuple[str, Path]) -> None:
    project_id, root = symbol_project
    for index, rel in enumerate(("secrets/private.py", "data/artifacts/source-scans/id/snapshot/module.py")):
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("def synthetic_private_target(): pass\n")
        (root / f"public_{index}.py").symlink_to(file)
    assert FileScanner(project_id).run().success
    assert explorer_symbols.search_symbols_page(project_id, "synthetic_private_target")["count"] == 0


def test_rescan_drops_git_ignored_material_but_keeps_untracked_source(symbol_project: tuple[str, Path]) -> None:
    """Ignored case archives and raw captures stay out; a rescan clears rows indexed before the ignore rules."""
    project_id, root = symbol_project
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel in (
        "archive/export/module.py",
        "archive/tracked.py",
        "findings/case-1/raw/capture.py",
        "findings/case-1/summary.py",
        "data/raw/dump.py",
        "data/source.py",
        "draft.py",
    ):
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("def ignore_rule_target(): pass\n")
    subprocess.run(["git", "-C", str(root), "add", "-f", "archive/tracked.py"], check=True)
    assert FileScanner(project_id).run().success
    assert explorer_entries.get_entry(project_id, "file", "archive/export/module.py") is not None
    assert explorer_entries.get_entry(project_id, "file", "findings/case-1/raw") is not None

    (root / ".gitignore").write_text("archive/\nfindings/*/raw/\ndata/raw/\n")
    assert FileScanner(project_id).run().success

    for rel in ("archive/export/module.py", "findings/case-1/raw/capture.py"):
        assert explorer_entries.get_entry(project_id, "file", rel) is None
    assert explorer_entries.get_entry(project_id, "file", "archive/export") is None
    assert explorer_entries.get_entry(project_id, "file", "findings/case-1/raw") is None
    for rel in ("archive/tracked.py", "findings/case-1/summary.py", "draft.py"):
        assert explorer_entries.get_entry(project_id, "file", rel) is not None
    indexed = explorer_symbols.search_symbols_page(project_id, "ignore_rule_target")["items"]
    assert sorted(row["file_path"] for row in indexed) == [
        "archive/tracked.py",
        "data/source.py",
        "draft.py",
        "findings/case-1/summary.py",
    ]
