"""Checkout symbol search helpers for `st search`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.explorer.analyzers import extract_symbols
from app.services.explorer.analyzers.symbol_types import SymbolRecord

from .search_checkout_paths import (
    CHECKOUT_CANDIDATE_LIMIT,
    SUPPORTED_SYMBOL_EXTENSIONS,
    _iter_checkout_files,
    _normalize_rel_path,
    _path_matches_prefix,
    _resolve_checkout_path_prefix,
    _ripgrep_candidate_paths,
)


def _expand_symbol_queries(query: str) -> list[str]:
    from app.services.context_gatherer._precision_query import (
        is_natural_language_query,
        nl_to_symbol_terms,
        normalize_queries,
        split_path_and_symbol_terms,
    )

    normalized_queries = normalize_queries([query])
    if not normalized_queries:
        return []
    if is_natural_language_query(normalized_queries):
        queries = nl_to_symbol_terms(normalized_queries) or normalized_queries
    else:
        _path_terms, symbol_terms = split_path_and_symbol_terms(normalized_queries)
        queries = symbol_terms or normalized_queries
    raw_query = query.strip()
    if raw_query and raw_query not in queries:
        queries.append(raw_query)
    return queries


def _symbol_score(symbol: SymbolRecord, rel_path: str, queries: list[str]) -> int:
    best_score = 0
    for query in queries:
        best_score = max(best_score, _symbol_score_for_query(symbol, rel_path, query))
    return best_score


def _symbol_score_for_query(symbol: SymbolRecord, rel_path: str, query: str) -> int:
    exact = query.strip().lower()
    if not exact:
        return 0
    haystacks = [
        (symbol["name"].lower(), 100, 80),
        (symbol["qualified_name"].lower(), 95, 70),
        (rel_path.lower(), 0, 60),
        ((symbol.get("summary") or "").lower(), 0, 50),
        ((symbol.get("signature") or "").lower(), 0, 40),
        (" ".join(symbol.get("keywords", [])).lower(), 0, 30),
    ]
    for value, exact_score, contains_score in haystacks:
        if exact_score and value == exact:
            return exact_score
        if exact in value:
            return contains_score
    return 0


def _symbol_record_to_item(symbol: SymbolRecord, rel_path: str) -> dict[str, Any]:
    return {
        "symbol_id": symbol["symbol_id"],
        "qualified_name": symbol["qualified_name"],
        "name": symbol["name"],
        "kind": symbol["kind"],
        "signature": symbol["signature"],
        "summary": symbol.get("summary"),
        "language": symbol["language"],
        "start_line": symbol["start_line"],
        "end_line": symbol["end_line"],
        "file_path": rel_path,
    }


def _search_checkout_symbols(
    root: Path,
    query: str,
    *,
    limit: int,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """Search current-checkout symbols by extracting supported files locally."""
    normalized_prefix, target_root = _resolve_checkout_path_prefix(root, path_prefix)
    if normalized_prefix and target_root is None:
        return _empty_symbol_result(query, root, normalized_prefix)

    query_terms = _expand_symbol_queries(query)
    candidate_paths = _candidate_symbol_paths(root, query_terms, limit, normalized_prefix, target_root)
    items = _scored_symbol_items(root, candidate_paths, query_terms, normalized_prefix, limit)
    return {
        "query": query,
        "count": len(items),
        "items": items,
        "scope": "checkout",
        "root_path": str(root),
        "path_prefix": normalized_prefix,
    }


def _empty_symbol_result(query: str, root: Path, normalized_prefix: str | None) -> dict[str, Any]:
    return {
        "query": query,
        "count": 0,
        "items": [],
        "scope": "checkout",
        "root_path": str(root),
        "path_prefix": normalized_prefix,
    }


def _candidate_symbol_paths(
    root: Path,
    query_terms: list[str],
    limit: int,
    normalized_prefix: str | None,
    target_root: Path | None,
) -> list[Path]:
    candidate_paths: list[Path] = []
    seen_candidate_paths: set[Path] = set()
    for query_term in query_terms:
        candidates = _ripgrep_candidate_paths(
            root,
            query_term,
            limit=max(limit * 3, CHECKOUT_CANDIDATE_LIMIT),
            suffixes=SUPPORTED_SYMBOL_EXTENSIONS,
            path_prefix=normalized_prefix,
        )
        for candidate in candidates:
            if candidate not in seen_candidate_paths:
                seen_candidate_paths.add(candidate)
                candidate_paths.append(candidate)
    return candidate_paths or _iter_checkout_files(
        root,
        allowed_suffixes=SUPPORTED_SYMBOL_EXTENSIONS,
        start_root=target_root,
    )


def _scored_symbol_items(
    root: Path,
    candidate_paths: list[Path],
    query_terms: list[str],
    normalized_prefix: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int]] = set()
    scored_items: list[tuple[int, dict[str, Any]]] = []
    for path in candidate_paths:
        rel_path = _normalize_rel_path(root, path)
        if rel_path is None or not _path_matches_prefix(rel_path, normalized_prefix):
            continue
        _append_scored_symbols(path, rel_path, query_terms, seen, scored_items)
    scored_items.sort(key=_symbol_sort_key)
    return [item for _, item in scored_items[:limit]]


def _append_scored_symbols(
    path: Path,
    rel_path: str,
    query_terms: list[str],
    seen: set[tuple[str, str, int]],
    scored_items: list[tuple[int, dict[str, Any]]],
) -> None:
    for symbol in extract_symbols(path, rel_path):
        score = _symbol_score(symbol, rel_path, query_terms)
        key = (rel_path, symbol["symbol_id"], symbol["start_line"])
        if score > 0 and key not in seen:
            seen.add(key)
            scored_items.append((score, _symbol_record_to_item(symbol, rel_path)))


def _symbol_sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, str, int, str]:
    score, symbol = item
    return (
        -score,
        str(symbol.get("file_path", "")),
        int(symbol.get("start_line", 0) or 0),
        str(symbol.get("qualified_name", "")),
    )


def _search_checkout_file_symbols(root: Path, file_path: str, *, limit: int) -> dict[str, Any]:
    """List symbols for a specific file from the current checkout."""
    absolute_path = (root / file_path).resolve()
    rel_path = _normalize_rel_path(root, absolute_path)
    if rel_path is None or not absolute_path.is_file():
        return {"file_path": file_path, "count": 0, "items": [], "scope": "checkout", "root_path": str(root)}

    items = [_symbol_record_to_item(symbol, rel_path) for symbol in extract_symbols(absolute_path, rel_path)[:limit]]
    return {
        "file_path": rel_path,
        "count": len(items),
        "items": items,
        "scope": "checkout",
        "root_path": str(root),
    }
