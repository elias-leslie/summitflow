"""Section builders for precision code search output formatting."""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger
from ...storage.explorer import get_symbol, list_related_entries_for_file
from .. import explorer as explorer_service

logger = get_logger(__name__)

_SOURCE_SYMBOL_LIMIT = 2
_RELATED_ENTRY_LIMIT = 2


def _as_object_dict(value: object) -> dict[str, object]:
    """Normalize untyped metadata payloads into plain object dicts."""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def read_symbol_source(
    project_id: str,
    symbol: dict[str, object],
    *,
    context_lines: int = 2,
) -> str | None:
    """Read source code for a symbol, optionally with surrounding context lines."""
    root_path = explorer_service.get_project_root(project_id)
    if not root_path:
        return None

    root = Path(root_path).resolve()
    file_path = (root / str(symbol["file_path"])).resolve()
    if not file_path.is_relative_to(root) or not file_path.exists():
        return None

    try:
        if context_lines == 0:
            return _read_symbol_bytes(file_path, symbol)
        return _read_symbol_lines(file_path, symbol, context_lines)
    except OSError:
        logger.debug("precision_code_search_source_read_failed", exc_info=True)
        return None


def _read_symbol_bytes(file_path: Path, symbol: dict[str, object]) -> str:
    """Read exact bytes for a symbol using byte offset/length."""
    with file_path.open("rb") as handle:
        handle.seek(int(str(symbol["byte_offset"])))
        source_bytes = handle.read(int(str(symbol["byte_length"])))
    return source_bytes.decode("utf-8", errors="replace")


def _read_symbol_lines(file_path: Path, symbol: dict[str, object], context_lines: int) -> str:
    """Read symbol source with surrounding context lines."""
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(0, int(str(symbol["start_line"])) - 1 - context_lines)
    end = min(len(lines), int(str(symbol["end_line"])) + context_lines)
    return "\n".join(lines[start:end])


def estimate_naive_file_tokens(
    project_id: str,
    symbols: list[dict[str, object]],
) -> int:
    """Estimate token count for full files containing the given symbols."""
    root_path = explorer_service.get_project_root(project_id)
    if not root_path or not symbols:
        return 0

    root = Path(root_path).resolve()
    total = 0
    seen_paths: set[str] = set()

    for symbol in symbols:
        file_path = str(symbol.get("file_path", ""))
        if not file_path or file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        absolute_path = (root / file_path).resolve()
        if not absolute_path.is_relative_to(root) or not absolute_path.exists():
            continue
        try:
            total += max(absolute_path.stat().st_size // 4, 0)
        except OSError:
            logger.debug("precision_code_search_stat_failed", exc_info=True)
    return total


def _format_related_entry(entry: dict[str, object]) -> str | None:
    """Format a related explorer entry as a one-line string."""
    entry_type = entry.get("entry_type")
    path = str(entry.get("path", "unknown"))
    metadata = _as_object_dict(entry.get("metadata"))

    if entry_type == "endpoint":
        tables_value = metadata.get("depends_on_tables")
        tables = list(tables_value) if isinstance(tables_value, list) else []
        suffix = f" | tables: {', '.join(str(t) for t in tables)}" if tables else ""
        return f"endpoint {path}{suffix}"

    if entry_type == "page":
        return f"page {path}"

    return None


def build_symbol_section(project_id: str, symbols: list[dict[str, object]]) -> str:
    """Build the '## Relevant Symbols' and '## Exact Source Slices' markdown sections."""
    unique_paths = {str(s["file_path"]) for s in symbols}
    related_map = {fp: list_related_entries_for_file(project_id, fp) for fp in unique_paths}

    lines = ["## Relevant Symbols", ""]
    for symbol in symbols:
        summary = symbol.get("summary") or symbol.get("signature") or ""
        file_path = str(symbol["file_path"])
        lines.append(
            f"- `{symbol['qualified_name']}` ({symbol['kind']}) in {file_path}:{symbol['start_line']}"
            f" - {summary}"
        )
        for entry in related_map.get(file_path, [])[:_RELATED_ENTRY_LIMIT]:
            formatted = _format_related_entry(entry)
            if formatted:
                lines.append(f"  related: {formatted}")

    source_lines = _build_source_slices(project_id, symbols)
    if source_lines:
        lines.extend(["", "## Exact Source Slices", ""])
        lines.extend(source_lines)

    return "\n".join(lines).strip()


def _build_source_slices(project_id: str, symbols: list[dict[str, object]]) -> list[str]:
    """Build source code snippet lines for the top symbols."""
    source_lines: list[str] = []
    for summary_row in symbols[:_SOURCE_SYMBOL_LIMIT]:
        symbol = get_symbol(project_id, str(summary_row["symbol_id"])) or summary_row
        source = read_symbol_source(project_id, symbol, context_lines=2)
        if not source:
            continue
        source_lines.append(
            f"### `{symbol['qualified_name']}`"
            f" ({symbol['file_path']}:{symbol['start_line']}-{symbol['end_line']})"
        )
        source_lines.extend(["```", source, "```", ""])
    return source_lines


def build_text_section(text_results: dict[str, object]) -> str:
    """Build the '## Relevant Text Matches' markdown section."""
    items = text_results.get("items", [])
    if not isinstance(items, list) or not items:
        return ""

    lines = ["## Relevant Text Matches", ""]
    for item in items:
        if not isinstance(item, dict):
            continue
        item_dict = _as_object_dict(item)
        path = str(item_dict.get("path") or "unknown")
        line = item_dict.get("line")
        content = str(item_dict.get("content") or "").strip()
        lines.append(f"- {path}:{line} - {content}")

    return "\n".join(lines).strip()
