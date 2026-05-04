"""Checkout precision result builders for `st search`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.context_gatherer.token_utils import estimate_tokens

from .search_budget import truncate_prompt_to_budget
from .search_checkout_paths import _normalize_path_prefix
from .search_checkout_symbols import _search_checkout_symbols
from .search_checkout_text import _search_checkout_text


def _read_checkout_snippet(root: Path, rel_path: str, start_line: int, end_line: int | None) -> str:
    absolute_path = (root / rel_path).resolve()
    try:
        lines = absolute_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""

    line_start = max(1, start_line - 1)
    line_end = min(len(lines), max(end_line or start_line, start_line) + 1)
    return "\n".join(lines[line_start - 1 : line_end]).rstrip()


def _build_checkout_symbol_prompt(root: Path, items: list[dict[str, Any]]) -> str:
    lines = ["## Current Checkout Overrides", ""]
    for item in items:
        detail = item.get("summary") or item.get("signature") or ""
        suffix = f" - {detail}" if detail else ""
        lines.append(
            f"- `{item.get('qualified_name', item.get('name', 'unknown'))}` "
            f"({item.get('kind', 'unknown')}) in {item.get('file_path', 'unknown')}:{item.get('start_line', '?')}{suffix}"
        )
    _append_checkout_symbol_slices(lines, root, items)
    return "\n".join(lines).strip()


def _append_checkout_symbol_slices(lines: list[str], root: Path, items: list[dict[str, Any]]) -> None:
    for item in items[: min(len(items), 5)]:
        snippet = _read_checkout_snippet(
            root,
            str(item.get("file_path", "")),
            int(item.get("start_line", 1) or 1),
            int(item.get("end_line", 0) or 0) or None,
        )
        if snippet:
            lines.extend(
                [
                    "",
                    f"### `{item.get('qualified_name', item.get('name', 'unknown'))}` "
                    f"({item.get('file_path', 'unknown')}:{item.get('start_line', '?')}-{item.get('end_line', '?')})",
                    "```",
                    snippet,
                    "```",
                ]
            )


def _build_checkout_text_prompt(result: dict[str, Any]) -> str:
    lines = ["## Current Checkout Matches", ""]
    for item in result.get("items", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('path', 'unknown')}:{item.get('line', '?')} - {item.get('content', '')}")
    return "\n".join(lines).strip()


def _build_checkout_precision_result(
    query: str,
    checkout_root: Path,
    budget: int,
    limit: int,
    *,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """Build a prompt-ready precision result from the current checkout only."""
    normalized_prefix = _normalize_path_prefix(path_prefix)
    symbol_result = _search_checkout_symbols(checkout_root, query, limit=limit, path_prefix=normalized_prefix)
    if symbol_result.get("items"):
        return _checkout_precision_symbol_result(query, checkout_root, normalized_prefix, symbol_result, budget)

    text_result = _search_checkout_text(checkout_root, query, limit=limit, path_prefix=normalized_prefix)
    if text_result.get("items"):
        return _checkout_precision_text_result(query, checkout_root, normalized_prefix, text_result, budget)
    return _checkout_precision_empty_result(query, checkout_root, normalized_prefix, text_result)


def _checkout_precision_symbol_result(
    query: str,
    checkout_root: Path,
    normalized_prefix: str | None,
    symbol_result: dict[str, Any],
    budget: int,
) -> dict[str, Any]:
    body = _build_checkout_symbol_prompt(checkout_root, symbol_result["items"])
    prompt_context = truncate_prompt_to_budget(body, budget)
    return {
        "query": query,
        "prompt_context": prompt_context,
        "metadata": _checkout_metadata(checkout_root, normalized_prefix, prompt_context, symbol_result.get("count", 0), 0, 0, True, False),
    }


def _checkout_precision_text_result(
    query: str,
    checkout_root: Path,
    normalized_prefix: str | None,
    text_result: dict[str, Any],
    budget: int,
) -> dict[str, Any]:
    body = _build_checkout_text_prompt(text_result)
    prompt_context = truncate_prompt_to_budget(body, budget)
    return {
        "query": query,
        "prompt_context": prompt_context,
        "metadata": _checkout_metadata(
            checkout_root,
            normalized_prefix,
            prompt_context,
            0,
            text_result.get("count", 0),
            text_result.get("files_searched", 0),
            False,
            True,
        ),
    }


def _checkout_precision_empty_result(
    query: str,
    checkout_root: Path,
    normalized_prefix: str | None,
    text_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "query": query,
        "prompt_context": "",
        "metadata": _checkout_metadata(
            checkout_root,
            normalized_prefix,
            "",
            0,
            0,
            text_result.get("files_searched", 0),
            False,
            False,
        ),
    }


def _checkout_metadata(
    checkout_root: Path,
    path_prefix: str | None,
    prompt_context: str,
    symbol_count: int,
    text_match_count: int,
    text_files_searched: int,
    used_symbol_first: bool,
    used_fallback: bool,
) -> dict[str, Any]:
    return {
        "scope": "checkout",
        "checkout_root": str(checkout_root),
        "path_prefix": path_prefix,
        "symbol_count": symbol_count,
        "text_match_count": text_match_count,
        "text_files_searched": text_files_searched,
        "used_symbol_first": used_symbol_first,
        "used_fallback": used_fallback,
        "estimated_tokens_saved": 0,
        "final_tokens": estimate_tokens(prompt_context),
    }
