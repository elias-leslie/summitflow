"""Compact output helpers for `st search`."""

from __future__ import annotations

from typing import Any

from .search_checkout import _normalize_path_prefix
from .search_hints import HINT_PREFIX, generate_hint


def _scope_suffix(scope: str | None) -> str:
    """Return a compact scope suffix when results are not canonical-project only."""
    if not scope or scope == "project":
        return ""
    return f"|scope={scope}"


def _path_suffix(path_prefix: str | None) -> str:
    """Return a compact path suffix when search is restricted to a subtree/file."""
    normalized_prefix = _normalize_path_prefix(path_prefix)
    return f"|path={normalized_prefix}" if normalized_prefix else ""


def _print_precision_compact(
    query: str, prompt_context: str, metadata: dict[str, Any], *, show_hint: bool = True
) -> None:
    """Print TOON-style compact output for agent consumption."""
    symbol_count = metadata.get("symbol_count", 0)
    if metadata.get("used_symbol_first"):
        mode = "combined" if metadata.get("used_fallback") else "symbol-first"
    else:
        mode = "text-fallback"
    tokens_saved = metadata.get("estimated_tokens_saved", 0)
    final_tokens = metadata.get("final_tokens", 0)
    suffix = f"{_scope_suffix(metadata.get('scope'))}{_path_suffix(metadata.get('path_prefix'))}"

    if not prompt_context:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0{suffix}")
        _print_hint(query, "empty", metadata, show_hint)
        return

    print(f"SEARCH:{query}|mode={mode}|symbols={symbol_count}|tokens={final_tokens}|saved={tokens_saved}{suffix}")
    _print_hint(query, mode, metadata, show_hint)
    print()
    print(prompt_context)


def _print_text_compact(query: str, result: dict[str, Any]) -> None:
    """Print TOON-style compact text search output."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)
    files_searched = result.get("files_searched", 0)
    suffix = f"{_scope_suffix(result.get('scope'))}{_path_suffix(result.get('path_prefix'))}"

    if not items:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0{suffix}")
        return

    print(f"SEARCH:{query}|mode=text|matches={count}|files={files_searched}{suffix}")
    print()
    for item in items:
        if isinstance(item, dict):
            print(f"- {item.get('path', 'unknown')}:{item.get('line', '?')} | {item.get('content', '')}")


def _print_symbols_compact(query: str, result: dict[str, Any]) -> None:
    """Print TOON-style compact symbol search output."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)
    suffix = f"{_scope_suffix(result.get('scope'))}{_path_suffix(result.get('path_prefix'))}"

    if not items:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0{suffix}")
        return

    print(f"SEARCH:{query}|mode=symbols|symbols={count}{suffix}")
    print()
    for item in items:
        if isinstance(item, dict):
            print(
                f"- `{item.get('qualified_name', item.get('name', 'unknown'))}` "
                f"({item.get('kind', 'unknown')}) {item.get('file_path', 'unknown')}:{item.get('start_line', '?')}"
            )


def _print_file_symbols_compact(file_path: str, result: dict[str, Any], *, show_hint: bool = True) -> None:
    """Print TOON-style compact output for file symbol listing."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)
    scope_suffix = _scope_suffix(result.get("scope"))
    resolved_suffix = f"|resolved_from={result['resolved_from']}" if result.get("resolved_from") else ""

    if not items:
        print(f"SEARCH:--file {file_path}|mode=empty|symbols=0|tokens=0{scope_suffix}{resolved_suffix}")
        if show_hint:
            _print_file_empty_hint(file_path, result)
        return

    print(f"SEARCH:--file {file_path}|mode=file-symbols|symbols={count}{scope_suffix}{resolved_suffix}")
    print()
    for item in items:
        if isinstance(item, dict):
            print(_format_file_symbol(item))


def _print_file_empty_hint(file_path: str, result: dict[str, Any]) -> None:
    candidates = result.get("candidates") or []
    if candidates:
        listed = ", ".join(f"`{c}`" for c in candidates)
        print(f"{HINT_PREFIX}`{file_path}` matches multiple files — rerun with one exact path: {listed}")
    elif result.get("file_exists") or result.get("resolved_from"):
        print(
            f"{HINT_PREFIX}`{file_path}` has no extractable symbols (unsupported language or no definitions) — "
            'use `st search --text "<phrase>"` or read the file directly'
        )
    else:
        print(
            f"{HINT_PREFIX}no file matching `{file_path}` found — a basename or path-suffix fragment also resolves; "
            "check the spelling, or if the file is brand-new the index may not include it yet"
        )


def _print_hint(query: str, mode: str, metadata: dict[str, Any], show_hint: bool) -> None:
    if show_hint and (hint_text := generate_hint(query, mode, metadata)):
        print(f"{HINT_PREFIX}{hint_text}")


def _format_file_symbol(item: dict[str, Any]) -> str:
    kind = item.get("kind", "unknown")
    name = item.get("qualified_name", item.get("name", "unknown"))
    line = item.get("start_line", "?")
    detail = item.get("signature", "") or item.get("summary", "")
    suffix = f" - {detail}" if detail else ""
    return f"- `{name}` ({kind}) :{line}{suffix}"
