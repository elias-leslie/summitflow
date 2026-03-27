"""Shared type definitions for symbol extraction."""

from __future__ import annotations

from typing import TypedDict


class SymbolRecord(TypedDict):
    """Stored symbol metadata."""

    symbol_id: str
    qualified_name: str
    name: str
    kind: str
    signature: str
    language: str
    start_line: int
    end_line: int
    byte_offset: int
    byte_length: int
    content_hash: str
    summary: str | None
    keywords: list[str]
    decorators: list[str]
