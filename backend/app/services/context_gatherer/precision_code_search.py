"""SummitFlow index metadata adapter for Code Intelligence precision retrieval.

Storage and scheduled scanning stay in SummitFlow. Query-time source selection,
validation, ranking, rendering and accounting belong to Code Intelligence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ...logging_config import get_logger
from ...storage.explorer import get_symbol_stats, list_related_entries_for_file
from ...utils.datetime_helpers import parse_iso_datetime
from .. import explorer as explorer_service
from ..code_intelligence_host import configure_code_intelligence
from ..explorer.text_search import search_text
from .token_utils import MAX_EXPLORER_TOKENS

if TYPE_CHECKING:
    from code_intelligence.precision.current_search import (
        CurrentSearchResult as PrecisionCodeSearchResult,
    )

logger = get_logger(__name__)
_SEARCH_LIMIT = 5
# Scheduling health is diagnostic; age or a clean Git tree does not verify source.
_PRECISION_INDEX_MAX_AGE = timedelta(minutes=150)

PRECISION_CODE_SEARCH_GUIDANCE = (
    "Use the Precision Code Search block as the first code-navigation pass. "
    "Only broaden to file-wide or text search if these indexed symbols are insufficient, stale, or clearly unrelated."
)


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

def collect_precision_code_search_context(
    project_id: str,
    queries: list[str] | tuple[str, ...] | str,
    *,
    budget_tokens: int = MAX_EXPLORER_TOKENS,
    symbol_limit: int = _SEARCH_LIMIT,
    path_prefix: str | None = None,
    include_candidates: bool = False,
) -> PrecisionCodeSearchResult:
    """Supply host indexes/root to the shared source-verifying owner implementation."""
    from code_intelligence.precision.current_search import collect_current_search_context

    configure_code_intelligence()
    index_status: dict[str, object]
    try:
        index_status = _get_precision_index_status(project_id)
    except Exception as exc:
        # A failed index must not prevent bounded local recovery. The exception
        # type is useful diagnostics without leaking connection parameters.
        index_status = {
            "should_refresh": True,
            "refresh_reasons": ["index_status_unavailable"],
            "index_status_error": type(exc).__name__,
        }
    try:
        root = explorer_service.get_project_root(project_id)
    except Exception as exc:
        root = None
        index_status["root_lookup_error"] = type(exc).__name__
    index_status["refreshed_index"] = False
    result = collect_current_search_context(
        project_id,
        queries,
        project_root=Path(root) if root else None,
        search_text=search_text,
        budget_tokens=budget_tokens,
        symbol_limit=symbol_limit,
        path_prefix=path_prefix,
        index_status=index_status,
        include_candidates=include_candidates,
        list_related_entries_for_file=list_related_entries_for_file,
    )
    logger.info(
        "precision_code_search",
        extra={
            "project_id": project_id,
            **{key: result.metadata.get(key) for key in (
                "symbol_count", "text_match_count", "final_tokens",
                "estimated_tokens_saved", "measurement_available",
                "source_verified", "retrieval_duration_ms",
            )},
        },
    )
    return result
