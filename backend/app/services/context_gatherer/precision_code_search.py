"""Shared Precision Code Search retrieval for prompts and explorer context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ...logging_config import get_logger
from ...storage.explorer import get_symbol_stats
from ...utils.datetime_helpers import parse_iso_datetime
from .. import explorer as explorer_service
from ..explorer.text_search import search_text
from ._precision_query import (
    has_explicit_code_signal,
    identifier_shaped_tokens,
    is_import_query,
    is_natural_language_query,
    meaningful_terms,
    nl_to_symbol_terms,
    normalize_queries,
    split_path_and_symbol_terms,
)
from ._precision_ranking import normalize_match_text, search_and_rank_symbols
from ._precision_sections import (
    build_symbol_section,
    build_text_section,
    estimate_naive_file_tokens,
)
from .token_utils import MAX_EXPLORER_TOKENS, estimate_tokens, truncate_to_tokens

logger = get_logger(__name__)

_SEARCH_LIMIT = 5
_ENTRY_LIMIT = 12
_TEXT_SECTION_BUDGET_SHARE = 0.3
# Stale only when the bi-hourly refresh sweep (summitflow-refresh-precision-indexes,
# cron "10 */2 * * *") has demonstrably missed a cycle: cadence plus slack for scan time.
_PRECISION_INDEX_MAX_AGE = timedelta(minutes=150)
_INLINE_REFRESH_REASONS = {
    "missing_file_index",
    "missing_symbol_index",
    "missing_file_scan_timestamp",
    "missing_symbol_timestamp",
}

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
    coverage: dict[str, object]


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


_DEFINITION_PATTERN = (
    r"\b(?:def|class|function|fn|interface|struct|enum|trait|type|const|let|var|val)\s+{term}\b"
)


def _definition_matched_terms(
    normalized_queries: list[str],
    text_items: Any,
) -> list[str]:
    """Query terms whose definition line appears in the text matches.

    A `def <term>`/`class <term>` line surfacing only via text fallback means
    the symbol index should have had this term and missed it — a stale-index
    signal the hint layer surfaces instead of asking for a reshaped query.
    """
    if not isinstance(text_items, list) or not text_items:
        return []
    terms = list(dict.fromkeys(
        term for query in normalized_queries for term in query.split() if len(term) >= 3
    ))
    contents = [str(item.get("content", "")) for item in text_items if isinstance(item, dict)]
    matched = []
    for term in terms:
        pattern = re.compile(_DEFINITION_PATTERN.format(term=re.escape(term)))
        if any(pattern.search(content) for content in contents):
            matched.append(term)
    return matched


def _build_result_metadata(
    project_id: str,
    normalized_queries: list[str],
    state: _RetrievalState,
    *,
    path_prefix: str | None = None,
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
        "path_prefix": path_prefix,
        "symbol_count": len(state.symbols),
        "text_match_count": len(text_items) if isinstance(text_items, list) else 0,
        "text_files_searched": state.text_results.get("files_searched", 0),
        "text_per_term_union": bool(state.text_results.get("per_term_union", False)),
        "definition_matched_terms": (
            []
            if state.used_symbol_first
            else _definition_matched_terms(normalized_queries, text_items)
        ),
        "missed_identifier_terms": state.coverage.get("missed_identifier_tokens") or [],
        "suppressed_generic_symbols": state.coverage.get("suppressed_generic_symbols") or 0,
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
    """Check precision index freshness and refresh only when indexes are unusable."""
    index_status = _get_precision_index_status(project_id)
    raw_reasons = index_status.get("refresh_reasons", [])
    refresh_reasons = {str(reason) for reason in raw_reasons} if isinstance(raw_reasons, list) else set()
    should_refresh_inline = bool(refresh_reasons & _INLINE_REFRESH_REASONS)
    refreshed = _refresh_precision_index(project_id) if should_refresh_inline else False
    return index_status, refreshed


def _search_symbols_for_queries(
    project_id: str,
    normalized_queries: list[str],
    *,
    symbol_limit: int = _SEARCH_LIMIT,
    path_prefix: str | None = None,
) -> tuple[list[dict[str, object]], str, dict[str, object]]:
    """Run symbol search and build the symbol section.

    Import queries skip symbol search entirely. Natural language queries
    generate CamelCase/snake_case variants and try symbol search before
    falling back (e.g. "project selector" → tries "ProjectSelector").

    Returns (symbols, section, coverage). Coverage reports user-typed
    identifier tokens that missed the index; it stays empty for import and
    natural-language queries, whose synthesized variants are expected to miss.
    """
    if is_import_query(normalized_queries):
        return [], "", {}

    if is_natural_language_query(normalized_queries):
        # Try symbol search with case-expanded variants from NL words
        nl_terms = nl_to_symbol_terms(normalized_queries)
        if nl_terms:
            if path_prefix is None:
                symbols = search_and_rank_symbols(project_id, nl_terms, symbol_limit=symbol_limit)
            else:
                symbols = search_and_rank_symbols(
                    project_id,
                    nl_terms,
                    symbol_limit=symbol_limit,
                    path_prefix=path_prefix,
                )
            if symbols:
                section = build_symbol_section(project_id, symbols)
                return symbols, section, {}
        return [], "", {}

    _path_terms, symbol_terms = split_path_and_symbol_terms(normalized_queries)
    symbol_queries = symbol_terms if symbol_terms else normalized_queries
    identifier_tokens = identifier_shaped_tokens(symbol_queries)
    coverage: dict[str, object] = {}
    if path_prefix is None:
        symbols = search_and_rank_symbols(
            project_id,
            symbol_queries,
            symbol_limit=symbol_limit,
            identifier_tokens=identifier_tokens,
            coverage=coverage,
        )
    else:
        symbols = search_and_rank_symbols(
            project_id,
            symbol_queries,
            symbol_limit=symbol_limit,
            path_prefix=path_prefix,
            identifier_tokens=identifier_tokens,
            coverage=coverage,
        )
    section = build_symbol_section(project_id, symbols) if symbols else ""
    return symbols, section, coverage


def _symbol_hits_cover_plain_phrase(
    normalized_queries: list[str],
    symbols: list[dict[str, object]],
) -> bool:
    """Return True when at least one symbol covers all plain query words."""
    combined = " ".join(normalized_queries).strip()
    terms = meaningful_terms(normalize_match_text(combined))
    if len(terms) < 2 or has_explicit_code_signal(normalized_queries):
        return True

    for symbol in symbols:
        blob = normalize_match_text(
            " ".join(
                str(symbol.get(key) or "")
                for key in ("name", "qualified_name", "file_path", "signature", "summary")
            )
        )
        if all(term in blob for term in terms):
            return True

    return False


def _text_fallback(
    project_id: str,
    normalized_queries: list[str],
    symbol_section: str,
    *,
    path_prefix: str | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], str]:
    """Run text search as a fallback when symbol search yields nothing.

    Searches the full phrase first. When the phrase misses and the query has
    multiple meaningful terms, retries per term and unions the matches —
    dropping terms whose match count hits the cap, since those are the
    common words whose single-word matches are junk that costs tokens and
    misleads the caller.
    """
    _empty: dict[str, Any] = {"count": 0, "files_searched": 0, "items": [], "truncated": False}
    if symbol_section and not force:
        return _empty, ""

    path_terms, _symbol_terms = split_path_and_symbol_terms(normalized_queries)
    text_query = " ".join(path_terms) if path_terms else " ".join(normalized_queries)
    if path_prefix is None:
        text_results = search_text(project_id, text_query, limit=_ENTRY_LIMIT)
    else:
        text_results = search_text(project_id, text_query, limit=_ENTRY_LIMIT, path_prefix=path_prefix)

    if not text_results.get("items"):
        union = _per_term_text_union(project_id, text_query, path_prefix=path_prefix)
        if union is not None:
            text_results = union

    return text_results, build_text_section(text_results)


def _per_term_text_union(
    project_id: str,
    phrase: str,
    *,
    path_prefix: str | None = None,
) -> dict[str, Any] | None:
    """Union per-term matches when the full phrase has none.

    Terms whose match count reaches the cap are dropped: those are common
    words whose matches would be junk. Rare identifier-shaped terms — the
    ones worth surfacing — survive.
    """
    terms = list(dict.fromkeys(meaningful_terms(phrase)))
    if len(terms) < 2:
        return None

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    files_searched = 0
    for term in terms:
        result = search_text(project_id, term, limit=_ENTRY_LIMIT, path_prefix=path_prefix)
        files_searched = max(files_searched, int(result.get("files_searched", 0) or 0))
        term_items = result.get("items") or []
        if not term_items or result.get("truncated") or len(term_items) >= _ENTRY_LIMIT:
            continue
        for item in term_items:
            key = (str(item.get("path", "")), item.get("line"))
            if key not in seen:
                seen.add(key)
                items.append(item)

    if not items:
        return None
    items = items[:_ENTRY_LIMIT]
    return {
        "count": len(items),
        "files_searched": files_searched,
        "items": items,
        "truncated": False,
        "per_term_union": True,
    }


def _retrieve_and_assemble(
    project_id: str,
    normalized_queries: list[str],
    budget_tokens: int,
    *,
    symbol_limit: int = _SEARCH_LIMIT,
    path_prefix: str | None = None,
) -> _RetrievalState:
    """Retrieve symbols/text matches, assemble sections, return retrieval state."""
    index_status, refreshed_index = _ensure_index(project_id)
    symbols, symbol_section, coverage = _search_symbols_for_queries(
        project_id,
        normalized_queries,
        symbol_limit=symbol_limit,
        path_prefix=path_prefix,
    )
    text_results, text_section = _text_fallback(
        project_id,
        normalized_queries,
        symbol_section,
        path_prefix=path_prefix,
        force=bool(symbol_section)
        and not _symbol_hits_cover_plain_phrase(normalized_queries, symbols),
    )

    used_symbol_first = bool(symbol_section)
    used_fallback = bool(text_section)

    return _RetrievalState(
        symbols=symbols,
        symbol_section=symbol_section,
        text_results=text_results,
        text_section=text_section,
        truncated_body=_truncate_sections(symbol_section, text_section, budget_tokens),
        used_symbol_first=used_symbol_first,
        used_fallback=used_fallback,
        index_status=index_status,
        refreshed_index=refreshed_index,
        coverage=coverage,
    )


def _truncate_sections(symbol_section: str, text_section: str, budget_tokens: int) -> str:
    """Fit both sections within the budget without losing the text matches.

    Combined mode means symbol coverage was judged weak, so the text matches
    are the corrective signal; plain tail truncation would cut exactly those
    lines first. When both sections together exceed the budget, cap the text
    section at a share of the budget and give symbols the remainder.
    """
    if not symbol_section or not text_section:
        body = symbol_section or text_section
        return truncate_to_tokens(body, budget_tokens) if body else ""
    combined = f"{symbol_section}\n\n{text_section}"
    if estimate_tokens(combined) <= budget_tokens:
        return combined
    text_budget = min(estimate_tokens(text_section), int(budget_tokens * _TEXT_SECTION_BUDGET_SHARE))
    text_part = truncate_to_tokens(text_section, text_budget)
    symbol_part = truncate_to_tokens(symbol_section, budget_tokens - estimate_tokens(text_part))
    return f"{symbol_part}\n\n{text_part}"


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
    path_prefix: str | None = None,
) -> PrecisionCodeSearchResult:
    """Build symbol-first retrieval context with explicit fallback and telemetry."""
    normalized_queries = normalize_queries(queries)
    if not normalized_queries:
        return PrecisionCodeSearchResult(prompt_context="", metadata={"query_count": 0})

    state = _retrieve_and_assemble(
        project_id,
        normalized_queries,
        budget_tokens,
        symbol_limit=symbol_limit,
        path_prefix=path_prefix,
    )
    metadata = _build_result_metadata(
        project_id,
        normalized_queries,
        state,
        path_prefix=path_prefix,
    )

    if state.used_symbol_first and state.used_fallback:
        mode = "combined"
    elif state.used_symbol_first:
        mode = "symbol-first"
    elif state.truncated_body:
        mode = "text-fallback"
    else:
        mode = "empty"
    _log_result(project_id, metadata, mode)

    if not state.truncated_body:
        return PrecisionCodeSearchResult(prompt_context="", metadata=metadata)

    return PrecisionCodeSearchResult(
        prompt_context=_make_prompt_context(mode, metadata, state.truncated_body),
        metadata=metadata,
    )
