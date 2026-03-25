"""Shared Precision Code Search retrieval for prompts and explorer context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ...logging_config import get_logger
from ...storage.explorer import get_symbol_stats
from ...utils.datetime_helpers import parse_iso_datetime
from .. import explorer as explorer_service
from ..explorer.text_search import search_text
from ._precision_query import (
    is_import_query,
    is_natural_language_query,
    looks_like_workflow_meta_query,
    nl_to_symbol_terms,
    normalize_queries,
    split_path_and_symbol_terms,
)
from ._precision_ranking import search_and_rank_symbols
from ._precision_sections import (
    build_symbol_section,
    build_text_section,
    estimate_naive_file_tokens,
)
from .token_utils import MAX_EXPLORER_TOKENS, estimate_tokens, truncate_to_tokens

logger = get_logger(__name__)

_SEARCH_LIMIT = 5
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


@dataclass(slots=True)
class _RetrievalState:
    """Intermediate state from symbol/text retrieval and assembly."""

    symbols: list[dict[str, object]]
    symbol_section: str
    text_results: dict[str, Any]
    text_section: str
    truncated_body: str
    used_symbol_first: bool
    used_fallback: bool
    index_status: dict[str, object]
    refreshed_index: bool


# ---------------------------------------------------------------------------
# Index status & refresh
# ---------------------------------------------------------------------------



def _age_minutes(timestamp: datetime | None) -> int | None:
    if timestamp is None:
        return None
    return max(int((datetime.now(UTC) - timestamp).total_seconds() // 60), 0)


def _get_precision_index_status(project_id: str) -> dict[str, object]:
    file_stats = explorer_service.get_stats(project_id, entry_type="file")
    symbol_stats = get_symbol_stats(project_id)

    file_total = int(file_stats.get("total") or 0)
    symbol_count = int(symbol_stats.get("count") or 0)
    file_last_scanned = parse_iso_datetime(file_stats.get("last_scanned"))
    symbol_last_updated = parse_iso_datetime(symbol_stats.get("last_updated"))
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


# ---------------------------------------------------------------------------
# Metadata & logging
# ---------------------------------------------------------------------------


def _build_result_metadata(
    project_id: str,
    normalized_queries: list[str],
    state: _RetrievalState,
) -> dict[str, object]:
    naive_file_tokens = (
        estimate_naive_file_tokens(project_id, state.symbols)
        if state.used_symbol_first else 0
    )
    final_tokens = estimate_tokens(state.truncated_body)
    text_tokens = estimate_tokens(state.text_section)
    text_items = state.text_results.get("items", [])
    estimated_tokens_saved = (
        max(naive_file_tokens - final_tokens, 0)
        if state.used_symbol_first
        else max(text_tokens - final_tokens, 0)
    )

    return {
        "query_count": len(normalized_queries),
        "symbol_count": len(state.symbols),
        "text_match_count": len(text_items) if isinstance(text_items, list) else 0,
        "text_files_searched": state.text_results.get("files_searched", 0),
        "refreshed_index": state.refreshed_index,
        "used_symbol_first": state.used_symbol_first,
        "used_fallback": state.used_fallback,
        "fallback_mode": "text" if state.used_fallback else None,
        "naive_file_tokens": naive_file_tokens,
        "symbol_tokens": estimate_tokens(state.symbol_section),
        "fallback_tokens": text_tokens,
        "stale_hit": state.index_status["should_refresh"],
        "refresh_reasons": state.index_status["refresh_reasons"],
        "file_total": state.index_status["file_total"],
        "file_last_scanned": state.index_status["file_last_scanned"],
        "symbol_last_updated": state.index_status["symbol_last_updated"],
        "file_index_age_minutes": state.index_status["file_index_age_minutes"],
        "symbol_index_age_minutes": state.index_status["symbol_index_age_minutes"],
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


def _ensure_index(project_id: str) -> tuple[dict[str, object], bool]:
    """Check precision index freshness and refresh if stale."""
    index_status = _get_precision_index_status(project_id)
    refreshed = _refresh_precision_index(project_id) if index_status["should_refresh"] else False
    return index_status, refreshed


def _search_symbols_for_queries(
    project_id: str,
    normalized_queries: list[str],
    *,
    symbol_limit: int = _SEARCH_LIMIT,
) -> tuple[list[dict[str, object]], str]:
    """Run symbol search and build the symbol section.

    Import queries skip symbol search entirely. Natural language queries
    generate CamelCase/snake_case variants and try symbol search before
    falling back (e.g. "project selector" → tries "ProjectSelector").
    """
    if is_import_query(normalized_queries):
        return [], ""

    if is_natural_language_query(normalized_queries):
        # Try symbol search with case-expanded variants from NL words
        nl_terms = nl_to_symbol_terms(normalized_queries)
        if nl_terms:
            symbols = search_and_rank_symbols(project_id, nl_terms, symbol_limit=symbol_limit)
            if symbols:
                section = build_symbol_section(project_id, symbols)
                return symbols, section
        return [], ""

    _path_terms, symbol_terms = split_path_and_symbol_terms(normalized_queries)
    symbol_queries = symbol_terms if symbol_terms else normalized_queries
    symbols = search_and_rank_symbols(project_id, symbol_queries, symbol_limit=symbol_limit)
    section = build_symbol_section(project_id, symbols) if symbols else ""
    return symbols, section


def _text_fallback(
    project_id: str,
    normalized_queries: list[str],
    symbol_section: str,
) -> tuple[dict[str, Any], str]:
    """Run text search as a fallback when symbol search yields nothing.

    Tries the full phrase first.  When that produces no matches and the
    query has multiple words, retries with the longest individual term
    to surface at least *some* relevant content.
    """
    _empty: dict[str, Any] = {"count": 0, "files_searched": 0, "items": [], "truncated": False}
    if symbol_section:
        return _empty, ""

    path_terms, _symbol_terms = split_path_and_symbol_terms(normalized_queries)
    text_query = " ".join(path_terms) if path_terms else " ".join(normalized_queries)
    text_results = search_text(project_id, text_query, limit=_ENTRY_LIMIT)

    # If phrase search found nothing, try individual terms (longest first)
    if not text_results.get("items") and " " in text_query:
        terms: list[str] = sorted(text_query.split(), key=lambda term: len(term), reverse=True)
        for term in terms:
            if len(term) < 3:
                continue
            term_results = search_text(project_id, term, limit=_ENTRY_LIMIT)
            if term_results.get("items"):
                text_results = term_results
                break

    return text_results, build_text_section(text_results)


def _retrieve_and_assemble(
    project_id: str,
    normalized_queries: list[str],
    budget_tokens: int,
    *,
    symbol_limit: int = _SEARCH_LIMIT,
) -> _RetrievalState:
    """Retrieve symbols/text matches, assemble sections, return retrieval state."""
    index_status, refreshed_index = _ensure_index(project_id)
    symbols, symbol_section = _search_symbols_for_queries(
        project_id, normalized_queries, symbol_limit=symbol_limit,
    )
    text_results, text_section = _text_fallback(project_id, normalized_queries, symbol_section)

    used_symbol_first = bool(symbol_section)
    used_fallback = not used_symbol_first and bool(text_section)
    body = symbol_section if used_symbol_first else text_section

    return _RetrievalState(
        symbols=symbols,
        symbol_section=symbol_section,
        text_results=text_results,
        text_section=text_section,
        truncated_body=truncate_to_tokens(body, budget_tokens) if body else "",
        used_symbol_first=used_symbol_first,
        used_fallback=used_fallback,
        index_status=index_status,
        refreshed_index=refreshed_index,
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
    symbol_limit: int = _SEARCH_LIMIT,
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

    state = _retrieve_and_assemble(project_id, normalized_queries, budget_tokens, symbol_limit=symbol_limit)
    metadata = _build_result_metadata(project_id, normalized_queries, state)

    mode = "symbol-first" if state.used_symbol_first else ("text-fallback" if state.truncated_body else "empty")
    _log_result(project_id, metadata, mode)

    if not state.truncated_body:
        return PrecisionCodeSearchResult(prompt_context="", metadata=metadata)

    return PrecisionCodeSearchResult(
        prompt_context=_make_prompt_context(mode, metadata, state.truncated_body),
        metadata=metadata,
    )
