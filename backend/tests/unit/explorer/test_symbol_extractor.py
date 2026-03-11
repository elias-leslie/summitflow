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
