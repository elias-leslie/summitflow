"""Symbol match ranking and filtering for precision code search."""

from __future__ import annotations

import re

from ...storage.explorer import search_symbols
from ._precision_query import extract_query_terms

_CANDIDATE_LIMIT = 50
_CAMEL_CASE_RE = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_match_text(value: object) -> str:
    """Normalize a value to lowercase space-separated tokens for matching."""
    text = str(value or "")
    text = _CAMEL_CASE_RE.sub(r"\1 \2", text)
    return _NON_ALNUM_RE.sub(" ", text.lower()).strip()


def match_term_count(text: str, terms: list[str]) -> int:
    """Count how many terms appear in the text (as substring or token)."""
    text_tokens = set(text.split())
    return sum(1 for term in terms if term and (term in text or term in text_tokens))


def has_primary_match(row: dict[str, object], normalized_terms: list[str]) -> bool:
    """Return True if symbol matches on name, qualified_name, or file_path (not just summary/keywords)."""
    name = normalize_match_text(row.get("name"))
    qualified_name = normalize_match_text(row.get("qualified_name"))
    file_path = normalize_match_text(row.get("file_path"))
    return (
        match_term_count(name, normalized_terms)
        + match_term_count(qualified_name, normalized_terms)
        + match_term_count(file_path, normalized_terms)
    ) > 0


def symbol_match_rank(
    row: dict[str, object],
    normalized_queries: list[str],
    normalized_terms: list[str],
) -> tuple[int, int, int, int, int, int, str]:
    """Compute a multi-key ranking tuple for a candidate symbol."""
    name = normalize_match_text(row.get("name"))
    qualified_name = normalize_match_text(row.get("qualified_name"))
    signature = normalize_match_text(row.get("signature"))
    summary = normalize_match_text(row.get("summary"))
    file_path = normalize_match_text(row.get("file_path"))
    raw_keywords = row.get("keywords", [])
    keyword_values = raw_keywords if isinstance(raw_keywords, list | tuple | set) else []
    keywords = " ".join(normalize_match_text(kw) for kw in keyword_values)

    name_term_hits = match_term_count(name, normalized_terms)
    qualified_term_hits = match_term_count(qualified_name, normalized_terms)
    exact_name_hits = sum(1 for q in normalized_queries if q and q == name)
    path_term_hits = match_term_count(file_path, normalized_terms)
    summary_term_hits = match_term_count(summary, normalized_terms)
    sig_term_hits = match_term_count(signature, normalized_terms)
    kw_term_hits = match_term_count(keywords, normalized_terms)

    has_primary = int(name_term_hits + qualified_term_hits + path_term_hits > 0)
    blob = " ".join(part for part in (name, qualified_name, signature, summary, file_path, keywords) if part)
    query_phrase_hits = sum(1 for q in normalized_queries if q and q in blob)

    return (
        has_primary,
        exact_name_hits,
        name_term_hits + qualified_term_hits,
        query_phrase_hits,
        path_term_hits,
        summary_term_hits + sig_term_hits + kw_term_hits,
        str(row.get("qualified_name", "")),
    )


def search_and_rank_symbols(
    project_id: str,
    queries: list[str],
    *,
    symbol_limit: int = 5,
) -> list[dict[str, object]]:
    """Search for symbol candidates, filter, rank, and return the top matches."""
    candidates: dict[str, dict[str, object]] = {}
    query_terms = extract_query_terms(queries)

    for query in query_terms:
        for row in search_symbols(project_id, query, limit=_CANDIDATE_LIMIT):
            candidates.setdefault(str(row["symbol_id"]), row)

    if not candidates:
        return []

    normalized_queries = [normalize_match_text(q) for q in queries]
    normalized_terms = [normalize_match_text(t) for t in query_terms]

    primary = [r for r in candidates.values() if has_primary_match(r, normalized_terms)]
    pool = primary or list(candidates.values())

    ranked = sorted(
        pool,
        key=lambda row: symbol_match_rank(row, normalized_queries, normalized_terms),
        reverse=True,
    )
    return ranked[:symbol_limit]
