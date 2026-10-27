"""Per-project `.index.yaml` generation and live page discovery."""

from __future__ import annotations

from ._project import get_project_root
from .generator import generate_index, write_all_index_files, write_index_file
from .pages import discover_pages

__all__ = [
    "discover_pages",
    "generate_index",
    "get_project_root",
    "write_all_index_files",
    "write_index_file",
]
