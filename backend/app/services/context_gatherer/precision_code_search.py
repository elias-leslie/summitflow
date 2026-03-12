"""Shared Precision Code Search retrieval for prompts and explorer context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage.explorer import (
    get_symbol,
    get_symbol_stats,
    list_related_entries_for_file,
    search_symbols,
)
from .. import explorer as explorer_service
from ..explorer.text_search import search_text
from ._precision_query import (
    extract_query_terms,
    looks_like_workflow_meta_query,
    normalize_queries,
)
from .token_utils import MAX_EXPLORER_TOKENS, estimate_tokens, truncate_to_tokens

logger = get_logger(__name__)

_SEARCH_LIMIT = 5
_CANDIDATE_LIMIT = 50
_SOURCE_SYMBOL_LIMIT = 2
_RELATED_ENTRY_LIMIT = 2
_ENTRY_LIMIT = 12
_PRECISION_INDEX_MAX_AGE = timedelta(minutes=30)
_CAMEL_CASE_RE = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

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
    candidates: dict[str, dict[str, object]] = {}
    query_terms = extract_query_terms(queries)

    for query in query_terms:
        rows = search_symbols(project_id, query, limit=_CANDIDATE_LIMIT)
        for row in rows:
            candidates.setdefault(str(row["symbol_id"]), row)

    if not candidates:
        return []

    normalized_queries = [_normalize_match_text(query) for query in queries]
    normalized_terms = [_normalize_match_text(term) for term in query_terms]
    ranked = sorted(
        candidates.values(),
        key=lambda row: _symbol_match_rank(row, normalized_queries, normalized_terms),
        reverse=True,
    )
    return ranked[:_SEARCH_LIMIT]


def _normalize_match_text(value: object) -> str:
    text = str(value or "")
    text = _CAMEL_CASE_RE.sub(r"\1 \2", text)
    return _NON_ALNUM_RE.sub(" ", text.lower()).strip()


def _match_term_count(text: str, terms: list[str]) -> int:
    text_tokens = set(text.split())
    return sum(1 for term in terms if term and (term in text or term in text_tokens))


def _symbol_match_rank(
    row: dict[str, object],
    normalized_queries: list[str],
    normalized_terms: list[str],
) -> tuple[int, int, int, int, int, str]:
    name = _normalize_match_text(row.get("name"))
    qualified_name = _normalize_match_text(row.get("qualified_name"))
    signature = _normalize_match_text(row.get("signature"))
    summary = _normalize_match_text(row.get("summary"))
    file_path = _normalize_match_text(row.get("file_path"))
    raw_keywords = row.get("keywords", [])
    keyword_values = raw_keywords if isinstance(raw_keywords, list | tuple | set) else []
    keywords = " ".join(_normalize_match_text(keyword) for keyword in keyword_values)
    blob = " ".join(part for part in (name, qualified_name, signature, summary, file_path, keywords) if part)

    query_phrase_hits = sum(1 for query in normalized_queries if query and query in blob)
    distinct_term_hits = _match_term_count(blob, normalized_terms)
    name_term_hits = _match_term_count(name, normalized_terms)
    qualified_term_hits = _match_term_count(qualified_name, normalized_terms)
    path_term_hits = _match_term_count(file_path, normalized_terms)
    exact_name_hits = sum(1 for query in normalized_queries if query and query == name)

    return (
        distinct_term_hits,
        query_phrase_hits,
        exact_name_hits,
        name_term_hits + qualified_term_hits,
        path_term_hits + _match_term_count(summary, normalized_terms),
        str(row.get("qualified_name", "")),
    )


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


def _build_text_section(text_results: dict[str, object]) -> str:
    items = text_results.get("items", [])
    if not isinstance(items, list) or not items:
        return ""

    lines = ["## Relevant Text Matches", ""]
    for item in items:
        if not isinstance(item, dict):
            continue
        match = item
        path = str(match.get("path") or "unknown")
        line = match.get("line")
        content = str(match.get("content") or "").strip()
        lines.append(f"- {path}:{line} - {content}")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Metadata & logging
# ---------------------------------------------------------------------------


def _build_result_metadata(
    normalized_queries: list[str],
    symbols: list[dict[str, object]],
    text_results: dict[str, object],
    index_status: dict[str, object],
    refreshed_index: bool,
    used_symbol_first: bool,
    used_fallback: bool,
    symbol_section: str,
    text_section: str,
    truncated_body: str,
    project_id: str,
) -> dict[str, object]:
    naive_file_tokens = _estimate_naive_file_tokens_for_symbols(project_id, symbols) if used_symbol_first else 0
    final_tokens = estimate_tokens(truncated_body)
    text_tokens = estimate_tokens(text_section)
    text_items = text_results.get("items", [])
    text_match_count = len(text_items) if isinstance(text_items, list) else 0
    fallback_mode = "text" if used_fallback else None
    estimated_tokens_saved = (
        max(naive_file_tokens - final_tokens, 0)
        if used_symbol_first
        else max(text_tokens - final_tokens, 0)
    )

    return {
        "query_count": len(normalized_queries),
        "symbol_count": len(symbols),
        "text_match_count": text_match_count,
        "text_files_searched": text_results.get("files_searched", 0),
        "refreshed_index": refreshed_index,
        "used_symbol_first": used_symbol_first,
        "used_fallback": used_fallback,
        "fallback_mode": fallback_mode,
        "naive_file_tokens": naive_file_tokens,
        "symbol_tokens": estimate_tokens(symbol_section),
        "fallback_tokens": text_tokens,
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
) -> tuple[
    list[dict[str, object]],
    str,
    dict[str, Any],
    str,
    str,
    bool,
    bool,
    dict[str, object],
    bool,
]:
    """Retrieve symbols/text matches, assemble sections, return retrieval state."""
    index_status = _get_precision_index_status(project_id)
    refreshed_index = _refresh_precision_index(project_id) if index_status["should_refresh"] else False

    symbols = _search_symbol_matches(project_id, normalized_queries)
    symbol_section = _build_symbol_section(project_id, symbols) if symbols else ""
    text_results = (
        {"count": 0, "files_searched": 0, "items": [], "truncated": False}
        if symbol_section
        else search_text(project_id, " ".join(normalized_queries), limit=_ENTRY_LIMIT)
    )
    text_section = "" if symbol_section else _build_text_section(text_results)

    used_symbol_first = bool(symbol_section)
    used_fallback = not used_symbol_first and bool(text_section)
    body = symbol_section if used_symbol_first else text_section
    truncated_body = truncate_to_tokens(body, budget_tokens) if body else ""

    return (
        symbols,
        symbol_section,
        text_results,
        text_section,
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

    symbols, symbol_section, text_results, text_section, truncated_body, used_symbol_first, used_fallback, index_status, refreshed_index = (
        _retrieve_and_assemble(project_id, normalized_queries, budget_tokens)
    )

    metadata = _build_result_metadata(
        normalized_queries=normalized_queries,
        symbols=symbols,
        text_results=text_results,
        index_status=index_status,
        refreshed_index=refreshed_index,
        used_symbol_first=used_symbol_first,
        used_fallback=used_fallback,
        symbol_section=symbol_section,
        text_section=text_section,
        truncated_body=truncated_body,
        project_id=project_id,
    )

    mode = "symbol-first" if used_symbol_first else ("text-fallback" if truncated_body else "empty")
    _log_result(project_id, metadata, mode)

    if not truncated_body:
        return PrecisionCodeSearchResult(prompt_context="", metadata=metadata)

    return PrecisionCodeSearchResult(
        prompt_context=_make_prompt_context(mode, metadata, truncated_body),
        metadata=metadata,
    )
