"""Shared Precision Code Search retrieval for prompts and explorer context."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ...storage.explorer import (
    get_symbol,
    get_symbol_stats,
    list_related_entries_for_file,
    search_symbols,
)
from ...storage.explorer_entries import get_entries
from .. import explorer as explorer_service
from ._precision_query import (
    extract_query_terms,
    fallback_match_terms,
    looks_like_workflow_meta_query,
    normalize_queries,
)
from .token_utils import MAX_EXPLORER_TOKENS, estimate_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)

_SEARCH_LIMIT = 5
_SOURCE_SYMBOL_LIMIT = 2
_RELATED_ENTRY_LIMIT = 2
_ENTRY_LIMIT = 12
_PRECISION_INDEX_MAX_AGE = timedelta(minutes=30)

PRECISION_CODE_SEARCH_GUIDANCE = (
    "Use the Precision Code Search block as the first code-navigation pass. "
    "Only broaden to file-wide or text search if these indexed symbols are insufficient, stale, or clearly unrelated."
)


@dataclass(slots=True)
class PrecisionCodeSearchResult:
    prompt_context: str
    metadata: dict[str, object]


# ---------------------------------------------------------------------------
# Index status & refresh
# ---------------------------------------------------------------------------


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _age_minutes(timestamp: datetime | None) -> int | None:
    if timestamp is None:
        return None
    return max(int((datetime.now(UTC) - timestamp).total_seconds() // 60), 0)


def _get_precision_index_status(project_id: str) -> dict[str, object]:
    file_stats = explorer_service.get_stats(project_id, entry_type="file")
    symbol_stats = get_symbol_stats(project_id)

    file_total = int(file_stats.get("total") or 0)
    symbol_count = int(symbol_stats.get("count") or 0)
    file_last_scanned = _parse_iso_datetime(file_stats.get("last_scanned"))
    symbol_last_updated = _parse_iso_datetime(symbol_stats.get("last_updated"))
    stale_before = datetime.now(UTC) - _PRECISION_INDEX_MAX_AGE

    reasons: list[str] = []
    if file_total == 0:
        reasons.append("missing_file_index")
    if symbol_count == 0:
        reasons.append("missing_symbol_index")
    if file_last_scanned is None:
        reasons.append("missing_file_scan_timestamp")
    elif file_last_scanned < stale_before:
        reasons.append("stale_file_index")
    if symbol_last_updated is None:
        reasons.append("missing_symbol_timestamp")
    elif symbol_last_updated < stale_before:
        reasons.append("stale_symbol_index")

    return {
        "file_total": file_total,
        "symbol_count": symbol_count,
        "file_last_scanned": file_stats.get("last_scanned"),
        "symbol_last_updated": symbol_stats.get("last_updated"),
        "file_index_age_minutes": _age_minutes(file_last_scanned),
        "symbol_index_age_minutes": _age_minutes(symbol_last_updated),
        "refresh_reasons": reasons,
        "should_refresh": bool(reasons),
    }


def _refresh_precision_index(project_id: str) -> bool:
    logger.info("precision_code_search_refresh_start", extra={"project_id": project_id})
    result = explorer_service.scan(project_id, "file")
    if not result.success:
        logger.warning(
            "precision_code_search_refresh_failed",
            extra={"project_id": project_id, "error": result.error},
        )
        return False
    logger.info(
        "precision_code_search_refresh_complete",
        extra={
            "project_id": project_id,
            "entries_found": result.entries_found,
            "entries_saved": result.entries_saved,
            "duration_ms": result.duration_ms,
        },
    )
    return True


# ---------------------------------------------------------------------------
# Symbol retrieval & section building
# ---------------------------------------------------------------------------


def _read_symbol_source(
    project_id: str,
    symbol: dict[str, object],
    *,
    context_lines: int = 2,
) -> str | None:
    root_path = explorer_service.get_project_root(project_id)
    if not root_path:
        return None

    root = Path(root_path).resolve()
    file_path = (root / str(symbol["file_path"])).resolve()
    if not file_path.is_relative_to(root) or not file_path.exists():
        return None

    try:
        if context_lines == 0:
            with file_path.open("rb") as handle:
                handle.seek(int(str(symbol["byte_offset"])))
                source_bytes = handle.read(int(str(symbol["byte_length"])))
            return source_bytes.decode("utf-8", errors="replace")

        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, int(str(symbol["start_line"])) - 1 - context_lines)
        end = min(len(lines), int(str(symbol["end_line"])) + context_lines)
        return "\n".join(lines[start:end])
    except OSError:
        logger.debug("precision_code_search_source_read_failed", exc_info=True)
        return None


def _estimate_naive_file_tokens_for_symbols(
    project_id: str,
    symbols: list[dict[str, object]],
) -> int:
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


def _format_symbol_related(entry: dict[str, object]) -> str | None:
    entry_type = entry.get("entry_type")
    path = str(entry.get("path", "unknown"))
    metadata = entry.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if entry_type == "endpoint":
        tables = metadata.get("depends_on_tables") or []
        suffix = f" | tables: {', '.join(str(t) for t in tables)}" if tables else ""
        return f"endpoint {path}{suffix}"

    if entry_type == "page":
        return f"page {path}"

    return None


def _search_symbol_matches(project_id: str, queries: list[str]) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for query in extract_query_terms(queries):
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


def _build_symbol_section(project_id: str, symbols: list[dict[str, object]]) -> str:
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
            formatted = _format_symbol_related(entry)
            if formatted:
                lines.append(f"  related: {formatted}")

    source_lines: list[str] = []
    for summary_row in symbols[:_SOURCE_SYMBOL_LIMIT]:
        symbol = get_symbol(project_id, str(summary_row["symbol_id"])) or summary_row
        source = _read_symbol_source(project_id, symbol, context_lines=2)
        if not source:
            continue
        source_lines.append(
            f"### `{symbol['qualified_name']}`"
            f" ({symbol['file_path']}:{symbol['start_line']}-{symbol['end_line']})"
        )
        source_lines.extend(["```", source, "```", ""])

    if source_lines:
        lines.extend(["", "## Exact Source Slices", ""])
        lines.extend(source_lines)

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Fallback retrieval (files, endpoints, tables)
# ---------------------------------------------------------------------------


def _collect_files(project_id: str, query_terms: list[str]) -> str | None:
    files = get_entries(project_id, filters={"type": "file"})
    lowered_terms = fallback_match_terms(query_terms)
    relevant = [
        f
        for f in files
        if any(
            term in str(f.get(field, "")).lower()
            for term in lowered_terms
            for field in ("name", "path")
        )
    ][:_ENTRY_LIMIT]
    if not relevant:
        return None
    return "\n".join(["## Relevant Files", "", *[f"- {f.get('path', 'unknown')}" for f in relevant]])


def _collect_endpoints(project_id: str, query_terms: list[str]) -> str | None:
    endpoints = get_entries(project_id, filters={"type": "endpoint"})[:_ENTRY_LIMIT]
    lowered_terms = fallback_match_terms(query_terms)
    relevant = [
        ep
        for ep in endpoints
        if any(
            term in str(ep.get("path", "")).lower() or term in str(ep.get("name", "")).lower()
            for term in lowered_terms
        )
    ]
    if not relevant:
        return None
    lines = ["## API Endpoints", ""]
    for ep in relevant[:_ENTRY_LIMIT]:
        method = (ep.get("metadata") or {}).get("method", "GET")
        lines.append(f"- {method} {ep.get('path', 'unknown')}")
    return "\n".join(lines)


def _collect_tables(project_id: str, query_terms: list[str]) -> str | None:
    tables = get_entries(project_id, filters={"type": "table"})[:_ENTRY_LIMIT]
    lowered_terms = fallback_match_terms(query_terms)
    relevant = [t for t in tables if any(term in str(t.get("name", "")).lower() for term in lowered_terms)]
    if not relevant:
        return None
    return "\n".join(["## Database Tables", "", *[f"- {t.get('name', 'unknown')}" for t in relevant[:_ENTRY_LIMIT]]])


def _build_fallback_section(project_id: str, query_terms: list[str]) -> str:
    sections = [
        _collect_files(project_id, query_terms),
        _collect_endpoints(project_id, query_terms),
        _collect_tables(project_id, query_terms),
    ]
    return "\n\n".join(s for s in sections if s)


# ---------------------------------------------------------------------------
# Metadata & logging
# ---------------------------------------------------------------------------


def _build_result_metadata(
    normalized_queries: list[str],
    symbols: list[dict[str, object]],
    index_status: dict[str, object],
    refreshed_index: bool,
    used_symbol_first: bool,
    used_fallback: bool,
    symbol_section: str,
    fallback_section: str,
    truncated_body: str,
    project_id: str,
) -> dict[str, object]:
    naive_file_tokens = _estimate_naive_file_tokens_for_symbols(project_id, symbols) if used_symbol_first else 0
    final_tokens = estimate_tokens(truncated_body)
    fallback_tokens = estimate_tokens(fallback_section)
    estimated_tokens_saved = (
        max(naive_file_tokens - final_tokens, 0)
        if used_symbol_first
        else max(fallback_tokens - final_tokens, 0)
    )

    return {
        "query_count": len(normalized_queries),
        "symbol_count": len(symbols),
        "refreshed_index": refreshed_index,
        "used_symbol_first": used_symbol_first,
        "used_fallback": used_fallback,
        "naive_file_tokens": naive_file_tokens,
        "symbol_tokens": estimate_tokens(symbol_section),
        "fallback_tokens": fallback_tokens,
        "stale_hit": index_status["should_refresh"],
        "refresh_reasons": index_status["refresh_reasons"],
        "file_total": index_status["file_total"],
        "file_last_scanned": index_status["file_last_scanned"],
        "symbol_last_updated": index_status["symbol_last_updated"],
        "file_index_age_minutes": index_status["file_index_age_minutes"],
        "symbol_index_age_minutes": index_status["symbol_index_age_minutes"],
        "final_tokens": final_tokens,
        "estimated_tokens_saved": estimated_tokens_saved,
    }


def _log_result(project_id: str, metadata: dict[str, object], mode: str) -> None:
    logger.info(
        "precision_code_search",
        extra={
            "project_id": project_id,
            "symbol_count": metadata["symbol_count"],
            "used_symbol_first": metadata["used_symbol_first"],
            "used_fallback": metadata["used_fallback"],
            "estimated_tokens_saved": metadata["estimated_tokens_saved"],
            "stale_hit": metadata["stale_hit"],
            "refreshed_index": metadata["refreshed_index"],
            "refresh_reasons": metadata["refresh_reasons"],
            "file_index_age_minutes": metadata["file_index_age_minutes"],
            "symbol_index_age_minutes": metadata["symbol_index_age_minutes"],
            "mode": mode,
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _retrieve_and_assemble(
    project_id: str,
    normalized_queries: list[str],
    budget_tokens: int,
) -> tuple[list[dict[str, object]], str, str, str, bool, bool, dict[str, object], bool]:
    """Retrieve symbols/fallback, assemble sections, return retrieval state."""
    index_status = _get_precision_index_status(project_id)
    refreshed_index = _refresh_precision_index(project_id) if index_status["should_refresh"] else False

    query_terms = extract_query_terms(normalized_queries)
    symbols = _search_symbol_matches(project_id, normalized_queries)
    symbol_section = _build_symbol_section(project_id, symbols) if symbols else ""
    fallback_section = "" if symbol_section else _build_fallback_section(project_id, query_terms)

    used_symbol_first = bool(symbol_section)
    used_fallback = not used_symbol_first and bool(fallback_section)
    body = symbol_section if used_symbol_first else fallback_section
    truncated_body = truncate_to_tokens(body, budget_tokens) if body else ""

    return (
        symbols,
        symbol_section,
        fallback_section,
        truncated_body,
        used_symbol_first,
        used_fallback,
        index_status,
        refreshed_index,
    )


def _make_prompt_context(mode: str, metadata: dict[str, object], truncated_body: str) -> str:
    telemetry = (
        "Precision Code Search: "
        f"{mode}; symbols={metadata['symbol_count']}; "
        f"estimated_token_savings={metadata['estimated_tokens_saved']}"
    )
    return f"{telemetry}\n\n{truncated_body}"


def collect_precision_code_search_context(
    project_id: str,
    queries: list[str] | tuple[str, ...] | str,
    *,
    budget_tokens: int = MAX_EXPLORER_TOKENS,
) -> PrecisionCodeSearchResult:
    """Build symbol-first retrieval context with explicit fallback and telemetry."""
    normalized_queries = normalize_queries(queries)
    if not normalized_queries:
        return PrecisionCodeSearchResult(prompt_context="", metadata={"query_count": 0})
    if looks_like_workflow_meta_query(normalized_queries):
        return PrecisionCodeSearchResult(
            prompt_context="",
            metadata={"query_count": len(normalized_queries), "skipped_reason": "workflow_meta_low_signal"},
        )

    symbols, symbol_section, fallback_section, truncated_body, used_symbol_first, used_fallback, index_status, refreshed_index = (
        _retrieve_and_assemble(project_id, normalized_queries, budget_tokens)
    )

    metadata = _build_result_metadata(
        normalized_queries=normalized_queries,
        symbols=symbols,
        index_status=index_status,
        refreshed_index=refreshed_index,
        used_symbol_first=used_symbol_first,
        used_fallback=used_fallback,
        symbol_section=symbol_section,
        fallback_section=fallback_section,
        truncated_body=truncated_body,
        project_id=project_id,
    )

    mode = "symbol-first" if used_symbol_first else ("fallback-only" if truncated_body else "empty")
    _log_result(project_id, metadata, mode)

    if not truncated_body:
        return PrecisionCodeSearchResult(prompt_context="", metadata=metadata)

    return PrecisionCodeSearchResult(
        prompt_context=_make_prompt_context(mode, metadata, truncated_body),
        metadata=metadata,
    )
