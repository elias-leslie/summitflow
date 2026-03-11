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
