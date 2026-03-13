"""Tests for explorer symbol extraction."""

from __future__ import annotations

from pathlib import Path

from app.services.explorer.analyzers.symbol_extractor import extract_symbols


class TestExtractPythonSymbols:
    """Tests for Python symbol extraction."""

    def test_extracts_functions_classes_and_methods(self, tmp_path: Path) -> None:
        """Python extraction should emit top-level functions, classes, and methods."""
        code = '''
async def fetch_user(user_id: str) -> str:
    """Fetch a single user."""
    return user_id


class UserService:
    """Application service."""

    def get_user(self, user_id: str) -> str:
        """Get a user by id."""
        return user_id
'''
        file_path = tmp_path / "service.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/app/service.py")

        assert [symbol["symbol_id"] for symbol in symbols] == [
            "backend/app/service.py::fetch_user#function",
            "backend/app/service.py::UserService#class",
            "backend/app/service.py::UserService.get_user#method",
        ]
        assert symbols[0]["summary"] == "Fetch a single user."
        assert symbols[1]["signature"] == "class UserService"
        assert symbols[2]["qualified_name"] == "UserService.get_user"
        assert symbols[2]["start_line"] == 10
        assert symbols[2]["byte_length"] > 0

    def test_extracts_nested_class_method_qualified_names(self, tmp_path: Path) -> None:
        """Nested class methods should include class qualification."""
        code = """
class Outer:
    class Inner:
        def run(self) -> None:
            pass
"""
        file_path = tmp_path / "nested.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/app/nested.py")

        assert [symbol["qualified_name"] for symbol in symbols] == [
            "Outer",
            "Outer.Inner",
            "Outer.Inner.run",
        ]


class TestExtractTypeScriptSymbols:
    """Tests for TypeScript/TSX symbol extraction."""

    def test_extracts_named_tsx_symbols(self, tmp_path: Path) -> None:
        """TSX extraction should find exported functions, types, and interfaces."""
        code = """
import React from 'react'

interface FilesClientProps {
  projectId: string
}

export function FilesClient(): React.ReactElement {
  return <div>Files</div>
}

export const useFileTree = (projectId: string) => {
  return projectId
}

export type FileNode = {
  path: string
}
"""
        file_path = tmp_path / "FilesClient.tsx"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "frontend/app/projects/[id]/files/FilesClient.tsx")

        assert [symbol["symbol_id"] for symbol in symbols] == [
            "frontend/app/projects/[id]/files/FilesClient.tsx::FilesClientProps#type",
            "frontend/app/projects/[id]/files/FilesClient.tsx::FilesClient#function",
            "frontend/app/projects/[id]/files/FilesClient.tsx::useFileTree#function",
            "frontend/app/projects/[id]/files/FilesClient.tsx::FileNode#type",
        ]
        assert symbols[1]["language"] == "tsx"
        assert symbols[2]["signature"].startswith("export const useFileTree")
        assert symbols[3]["kind"] == "type"

    def test_skips_unsupported_extension(self, tmp_path: Path) -> None:
        """Unsupported files should produce no symbols."""
        file_path = tmp_path / "notes.md"
        file_path.write_text("# Notes", encoding="utf-8")

        assert extract_symbols(file_path, "docs/notes.md") == []

    def test_dedupes_duplicate_symbol_ids_with_line_suffix(self, tmp_path: Path) -> None:
        """Duplicate qualified names in a file should get unique symbol ids."""
        code = """
class Memory:
    @property
    def injection_tier(self) -> str:
        return "low"

    @injection_tier.setter
    def injection_tier(self, value: str) -> None:
        self._tier = value
"""
        file_path = tmp_path / "memory.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/app/models/memory.py")

        assert [symbol["symbol_id"] for symbol in symbols] == [
            "backend/app/models/memory.py::Memory#class",
            "backend/app/models/memory.py::Memory.injection_tier#method",
            "backend/app/models/memory.py::Memory.injection_tier#method@8",
        ]


class TestExtractModuleLevelConstants:
    """Module-level UPPER_CASE constants should be indexed as symbols."""

    def test_extracts_simple_constant(self, tmp_path: Path) -> None:
        code = '''
SKIP_DIRS = frozenset({"__pycache__", "node_modules"})

MAX_FILE_SIZE = 500_000
'''
        file_path = tmp_path / "constants.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/app/constants.py")
        names = [s["name"] for s in symbols]
        assert "SKIP_DIRS" in names
        assert "MAX_FILE_SIZE" in names

    def test_constant_has_correct_kind(self, tmp_path: Path) -> None:
        code = "DEFAULT_LIMIT = 50\n"
        file_path = tmp_path / "config.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/config.py")
        const = next(s for s in symbols if s["name"] == "DEFAULT_LIMIT")
        assert const["kind"] == "constant"

    def test_skips_private_underscored_constants(self, tmp_path: Path) -> None:
        code = '_INTERNAL_LIMIT = 10\n_CACHE_TTL = 300\nPUBLIC_CONST = "yes"\n'
        file_path = tmp_path / "config.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/config.py")
        names = [s["name"] for s in symbols]
        # Private constants with single underscore prefix are still indexed
        # (they're commonly searched for, like _SEARCH_LIMIT, _STOP_WORDS)
        assert "_INTERNAL_LIMIT" in names
        assert "PUBLIC_CONST" in names

    def test_skips_lowercase_assignments(self, tmp_path: Path) -> None:
        code = "logger = get_logger(__name__)\napp = typer.Typer()\n"
        file_path = tmp_path / "cli.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/cli.py")
        names = [s["name"] for s in symbols]
        assert "logger" not in names
        assert "app" not in names


class TestExtractDecorators:
    """Decorators should be captured in symbol metadata."""

    def test_captures_pytest_fixture_decorator(self, tmp_path: Path) -> None:
        code = '''
import pytest

@pytest.fixture
def db_connection():
    """Database connection fixture."""
    return "conn"
'''
        file_path = tmp_path / "conftest.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/tests/conftest.py")
        fixture = next(s for s in symbols if s["name"] == "db_connection")
        assert "pytest.fixture" in (fixture.get("decorators") or [])

    def test_captures_multiple_decorators(self, tmp_path: Path) -> None:
        code = '''
import pytest

@pytest.fixture(scope="session")
@pytest.mark.slow
def heavy_setup():
    pass
'''
        file_path = tmp_path / "conftest.py"
        file_path.write_text(code, encoding="utf-8")

        symbols = extract_symbols(file_path, "backend/tests/conftest.py")
        func = next(s for s in symbols if s["name"] == "heavy_setup")
        decorators = func.get("decorators") or []
        assert any("pytest.fixture" in d for d in decorators)
        assert any("pytest.mark.slow" in d for d in decorators)
