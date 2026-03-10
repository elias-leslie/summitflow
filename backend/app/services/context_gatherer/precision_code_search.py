"""Shared Precision Code Search retrieval for prompts and explorer context."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...storage.explorer import get_symbol, list_related_entries_for_file, search_symbols
from ...storage.explorer_entries import get_entries
from .. import explorer as explorer_service
from .token_utils import MAX_EXPLORER_TOKENS, estimate_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)

_SEARCH_LIMIT = 5
_SOURCE_SYMBOL_LIMIT = 2
_RELATED_ENTRY_LIMIT = 2
_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "using",
    "make",
    "task",
    "code",
    "shared",
    "path",
    "workflow",
    "validation",
    "dispatch",
    "readiness",
    "reconciliation",
    "friction",
    "signal",
    "temporary",
    "queue",
    "summary",
    "closure",
    "ergonomics",
    "context",
    "task-system",
}
_WORKFLOW_META_TERMS = {
    "workflow",
    "validation",
    "dispatch",
    "readiness",
    "reconciliation",
    "friction",
    "signal",
    "temporary",
    "queue",
    "residue",
    "closure",
    "citation",
    "syncable",
    "lane",
    "ergonomics",
}
_CODE_SIGNAL_TERMS = {
    "api",
    "endpoint",
    "table",
    "schema",
    "migration",
    "query",
    "sql",
    "symbol",
    "function",
    "class",
    "module",
    "component",
    "frontend",
    "backend",
    "react",
    "typescript",
    "python",
    "cli",
    "prompt",
    "review",
    "planner",
    "autocode",
    "file",
    "worktree",
}


@dataclass(slots=True)
class PrecisionCodeSearchResult:
    prompt_context: str
    metadata: dict[str, Any]


def _normalize_queries(queries: list[str] | tuple[str, ...] | str) -> list[str]:
    if isinstance(queries, str):
        queries = [queries]

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in queries:
        for piece in str(raw).splitlines():
            query = piece.strip()
            lowered = query.lower()
            if len(query) < 2 or lowered in seen:
                continue
            normalized.append(query)
            seen.add(lowered)
    return normalized


def _extract_query_terms(queries: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    for query in queries:
        if len(query) <= 80:
            lowered = query.lower()
            if lowered not in seen:
                terms.append(query)
                seen.add(lowered)

        for token in query.replace("`", " ").replace(",", " ").split():
            candidate = token.strip("()[]{}:.;'\"")
            lowered = candidate.lower()
            if (
                len(candidate) < 3
                or lowered in seen
                or lowered in _STOP_WORDS
            ):
                continue
            terms.append(candidate)
            seen.add(lowered)
            if len(terms) >= 12:
                return terms

    return terms


def _has_explicit_code_signal(queries: list[str]) -> bool:
    combined = " ".join(queries).lower()
    if any(marker in combined for marker in ("backend/", "frontend/", ".py", ".ts", ".tsx", "`", "::", "()")):
        return True
    return any(term in combined for term in _CODE_SIGNAL_TERMS)


def _looks_like_workflow_meta_query(queries: list[str]) -> bool:
    combined = " ".join(queries).lower()
    workflow_hits = sum(1 for term in _WORKFLOW_META_TERMS if term in combined)
    return workflow_hits >= 2 and not _has_explicit_code_signal(queries)


def _fallback_match_terms(query_terms: list[str]) -> list[str]:
    specific_terms = [
        term.lower()
        for term in query_terms
        if term.lower() not in _CODE_SIGNAL_TERMS and term.lower() not in _STOP_WORDS
    ]
    return specific_terms or [term.lower() for term in query_terms]


def _search_symbol_matches(project_id: str, queries: list[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for query in _extract_query_terms(queries):
        rows = search_symbols(project_id, query, limit=_SEARCH_LIMIT)
        for row in rows:
            symbol_id = str(row["symbol_id"])
            if symbol_id in seen_ids:
                continue
            matches.append(row)
            seen_ids.add(symbol_id)
            if len(matches) >= _SEARCH_LIMIT:
                return matches

    return matches


def _format_symbol_related(entry: dict[str, object]) -> str | None:
    entry_type = entry.get("entry_type")
    path = str(entry.get("path", "unknown"))
    metadata = entry.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if entry_type == "endpoint":
        tables = metadata.get("depends_on_tables") or []
        suffix = f" | tables: {', '.join(str(table) for table in tables)}" if tables else ""
        return f"endpoint {path}{suffix}"

    if entry_type == "page":
        return f"page {path}"

    return None


def _read_symbol_source(
    project_id: str,
    symbol: dict[str, Any],
    *,
    context_lines: int = 2,
) -> str | None:
    root_path = explorer_service.get_project_root(project_id)
    if not root_path:
        return None

    root = Path(root_path).resolve()
    file_path = (root / symbol["file_path"]).resolve()
    if not file_path.is_relative_to(root) or not file_path.exists():
        return None

    try:
        if context_lines == 0:
            with file_path.open("rb") as handle:
                handle.seek(int(symbol["byte_offset"]))
                source_bytes = handle.read(int(symbol["byte_length"]))
            return source_bytes.decode("utf-8", errors="replace")

        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, int(symbol["start_line"]) - 1 - context_lines)
        end = min(len(lines), int(symbol["end_line"]) + context_lines)
        return "\n".join(lines[start:end])
    except OSError:
        logger.debug("precision_code_search_source_read_failed", exc_info=True)
        return None


def _build_symbol_section(project_id: str, symbols: list[dict[str, Any]]) -> str:
    unique_paths = {str(symbol["file_path"]) for symbol in symbols}
    related_map = {
        file_path: list_related_entries_for_file(project_id, file_path)
        for file_path in unique_paths
    }

    lines = ["## Relevant Symbols", ""]
    for symbol in symbols:
        summary = symbol.get("summary") or symbol.get("signature") or ""
        file_path = str(symbol["file_path"])
        lines.append(
            f"- `{symbol['qualified_name']}` ({symbol['kind']}) in {file_path}:{symbol['start_line']}"
            f" - {summary}"
        )
        for entry in related_map.get(file_path, [])[:_RELATED_ENTRY_LIMIT]:
            formatted = _format_symbol_related(entry)
            if formatted:
                lines.append(f"  related: {formatted}")

    detailed_symbols = symbols[:_SOURCE_SYMBOL_LIMIT]
    if detailed_symbols:
        lines.extend(["", "## Exact Source Slices", ""])
        for summary_row in detailed_symbols:
            symbol = get_symbol(project_id, str(summary_row["symbol_id"])) or summary_row
            source = _read_symbol_source(project_id, symbol, context_lines=2)
            if not source:
                continue
            lines.append(
                f"### `{symbol['qualified_name']}`"
                f" ({symbol['file_path']}:{symbol['start_line']}-{symbol['end_line']})"
            )
            lines.append("```")
            lines.append(source)
            lines.append("```")
            lines.append("")

    return "\n".join(lines).strip()


def _collect_files(project_id: str, query_terms: list[str]) -> str | None:
    files = get_entries(project_id, filters={"type": "file"})
    lowered_terms = _fallback_match_terms(query_terms)
    relevant = [
        file_entry
        for file_entry in files
        if any(
            term in str(file_entry.get(field, "")).lower()
            for term in lowered_terms
            for field in ("name", "path")
        )
    ][:12]
    if not relevant:
        return None
    return "\n".join(["## Relevant Files", "", *[f"- {f.get('path', 'unknown')}" for f in relevant]])


def _collect_endpoints(project_id: str, query_terms: list[str]) -> str | None:
    endpoints = get_entries(project_id, filters={"type": "endpoint"})[:12]
    lowered_terms = _fallback_match_terms(query_terms)
    relevant = [
        endpoint
        for endpoint in endpoints
        if any(
            term in str(endpoint.get("path", "")).lower()
            or term in str(endpoint.get("name", "")).lower()
            for term in lowered_terms
        )
    ]
    if not relevant:
        return None
    lines = ["## API Endpoints", ""]
    for endpoint in relevant[:12]:
        method = endpoint.get("metadata", {}).get("method", "GET")
        lines.append(f"- {method} {endpoint.get('path', 'unknown')}")
    return "\n".join(lines)


def _collect_tables(project_id: str, query_terms: list[str]) -> str | None:
    tables = get_entries(project_id, filters={"type": "table"})[:12]
    lowered_terms = _fallback_match_terms(query_terms)
    relevant = [
        table
        for table in tables
        if any(term in str(table.get("name", "")).lower() for term in lowered_terms)
    ]
    if not relevant:
        return None
    return "\n".join(["## Database Tables", "", *[f"- {t.get('name', 'unknown')}" for t in relevant[:12]]])


def _build_fallback_section(project_id: str, query_terms: list[str]) -> str:
    sections = [
        _collect_files(project_id, query_terms),
        _collect_endpoints(project_id, query_terms),
        _collect_tables(project_id, query_terms),
    ]
    return "\n\n".join(section for section in sections if section)


def collect_precision_code_search_context(
    project_id: str,
    queries: list[str] | tuple[str, ...] | str,
    *,
    budget_tokens: int = MAX_EXPLORER_TOKENS,
) -> PrecisionCodeSearchResult:
    """Build symbol-first retrieval context with explicit fallback and telemetry."""
    normalized_queries = _normalize_queries(queries)
    if not normalized_queries:
        return PrecisionCodeSearchResult(prompt_context="", metadata={"query_count": 0})
    if _looks_like_workflow_meta_query(normalized_queries):
        return PrecisionCodeSearchResult(
            prompt_context="",
            metadata={"query_count": len(normalized_queries), "skipped_reason": "workflow_meta_low_signal"},
        )

    query_terms = _extract_query_terms(normalized_queries)
    symbols = _search_symbol_matches(project_id, normalized_queries)
    symbol_section = _build_symbol_section(project_id, symbols) if symbols else ""
    fallback_section = _build_fallback_section(project_id, query_terms)

    used_symbol_first = bool(symbol_section)
    used_fallback = not used_symbol_first and bool(fallback_section)
    body = symbol_section if used_symbol_first else fallback_section
    truncated_body = truncate_to_tokens(body, budget_tokens) if body else ""

    metadata = {
        "query_count": len(normalized_queries),
        "symbol_count": len(symbols),
        "used_symbol_first": used_symbol_first,
        "used_fallback": used_fallback,
        "symbol_tokens": estimate_tokens(symbol_section),
        "fallback_tokens": estimate_tokens(fallback_section),
    }
    metadata["final_tokens"] = estimate_tokens(truncated_body)
    metadata["estimated_tokens_saved"] = max(
        metadata["fallback_tokens"] - metadata["final_tokens"],
        0,
    ) if used_symbol_first else 0

    if not truncated_body:
        return PrecisionCodeSearchResult(prompt_context="", metadata=metadata)

    mode = "symbol-first" if used_symbol_first else "fallback-only"
    telemetry = (
        "Precision Code Search: "
        f"{mode}; symbols={metadata['symbol_count']}; "
        f"estimated_token_savings={metadata['estimated_tokens_saved']}"
    )

    logger.info(
        "precision_code_search",
        extra={
            "project_id": project_id,
            "symbol_count": metadata["symbol_count"],
            "used_symbol_first": used_symbol_first,
            "used_fallback": used_fallback,
            "estimated_tokens_saved": metadata["estimated_tokens_saved"],
        },
    )

    return PrecisionCodeSearchResult(
        prompt_context=f"{telemetry}\n\n{truncated_body}",
        metadata=metadata,
    )
