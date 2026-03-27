"""Symbol extraction for explorer precision retrieval."""

from __future__ import annotations

from pathlib import Path

from ._python_extractor import extract_python_symbols
from ._ts_extractor import extract_typescript_symbols
from .symbol_types import SymbolRecord

__all__ = ["SymbolRecord", "extract_symbols"]


def extract_symbols(file_path: Path, rel_path: str) -> list[SymbolRecord]:
    """Extract supported-language symbols for a file."""
    ext = file_path.suffix.lower()
    if ext not in {".py", ".ts", ".tsx"}:
        return []
    try:
        source = file_path.read_text(encoding="utf-8")
        if ext == ".py":
            return _dedupe_symbol_ids(extract_python_symbols(source, rel_path))
        language = "tsx" if ext == ".tsx" else "typescript"
        return _dedupe_symbol_ids(extract_typescript_symbols(source, rel_path, language))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []


def _dedupe_symbol_ids(symbols: list[SymbolRecord]) -> list[SymbolRecord]:
    seen: set[str] = set()
    for symbol in symbols:
        symbol_id = symbol["symbol_id"]
        if symbol_id in seen:
            symbol["symbol_id"] = f"{symbol_id}@{symbol['start_line']}"
        seen.add(symbol["symbol_id"])
    return symbols
