"""Query normalization, term extraction, and signal classification for precision search."""

from __future__ import annotations

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
    "cleanup",
    "status",
    "coordination",
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

_EXPLICIT_CODE_MARKERS = ("backend/", "frontend/", ".py", ".ts", ".tsx", "`", "::", "()")
_MAX_TERMS = 12
_PATH_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".yaml", ".yml", ".toml", ".md"}


def normalize_queries(queries: list[str] | tuple[str, ...] | str) -> list[str]:
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


def _is_path_token(token: str) -> bool:
    """Return True if the token looks like a file path or path fragment."""
    if "/" in token or "\\" in token:
        return True
    return any(token.endswith(ext) for ext in _PATH_EXTENSIONS)


def split_path_and_symbol_terms(queries: list[str]) -> tuple[list[str], list[str]]:
    """Split query terms into (path_terms, symbol_terms).

    Path segments like 'frontend/src' or 'explorer.py' are separated from
    conceptual symbol terms like 'ShowPreview' so each can be routed to
    the appropriate search mode.
    """
    path_terms: list[str] = []
    symbol_terms: list[str] = []
    for query in queries:
        for token in query.split():
            cleaned = token.strip("()[]{}:.;'\"")
            if not cleaned:
                continue
            if _is_path_token(cleaned):
                path_terms.append(cleaned)
            else:
                symbol_terms.append(cleaned)
    return path_terms, symbol_terms


def extract_query_terms(queries: list[str]) -> list[str]:
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
            if len(candidate) < 3 or lowered in seen or lowered in _STOP_WORDS:
                continue
            terms.append(candidate)
            seen.add(lowered)
            if len(terms) >= _MAX_TERMS:
                return terms

    return terms


def has_explicit_code_signal(queries: list[str]) -> bool:
    combined = " ".join(queries).lower()
    if any(marker in combined for marker in _EXPLICIT_CODE_MARKERS):
        return True
    return any(term in combined for term in _CODE_SIGNAL_TERMS)


def looks_like_workflow_meta_query(queries: list[str]) -> bool:
    combined = " ".join(queries).lower()
    workflow_hits = sum(1 for term in _WORKFLOW_META_TERMS if term in combined)
    return workflow_hits >= 2 and not has_explicit_code_signal(queries)


def fallback_match_terms(query_terms: list[str]) -> list[str]:
    specific_terms = [
        term.lower()
        for term in query_terms
        if term.lower() not in _CODE_SIGNAL_TERMS and term.lower() not in _STOP_WORDS
    ]
    return specific_terms or [term.lower() for term in query_terms]


# ---------------------------------------------------------------------------
# Query quality classification for hint generation
# ---------------------------------------------------------------------------

_PATH_MARKERS = ("/", "\\", ".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".json")


def has_path_segments(queries: list[str]) -> bool:
    """Detect path-qualified queries like 'Show Preview frontend/src'."""
    combined = " ".join(queries)
    return any(marker in combined for marker in _PATH_MARKERS)


def is_short_or_generic(queries: list[str]) -> bool:
    """Detect very short or generic queries unlikely to match symbols well."""
    combined = " ".join(queries).strip()
    terms = [t for t in combined.split() if t.lower() not in _STOP_WORDS]
    if not terms:
        return True
    # All terms are 3 chars or fewer (e.g. "dnd", "ui")
    if all(len(t) <= 3 for t in terms):
        return True
    # Single generic word that isn't a code identifier (no underscores, camelCase, etc.)
    return len(terms) == 1 and terms[0].isalpha() and terms[0].islower() and len(terms[0]) <= 6
