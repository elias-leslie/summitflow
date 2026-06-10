"""Query normalization, term extraction, and signal classification for precision search."""

from __future__ import annotations

import re

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# English function words only. Domain vocabulary (workflow, validation, dispatch,
# queue, ...) must NOT appear here: those words name real code in indexed projects
# and filtering them suppresses legitimate searches.
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
    "how",
    "does",
    "did",
    "what",
    "where",
    "when",
    "why",
    "which",
    "find",
    "show",
    "list",
    "get",
    "all",
    "can",
    "not",
    "have",
    "has",
    "had",
    "been",
    "are",
    "was",
    "were",
    "will",
    "would",
    "could",
    "should",
    "about",
    "there",
    "their",
    "they",
    "them",
    "then",
    "than",
    "also",
    "just",
    "only",
    "while",
    "these",
    "those",
    "after",
    "before",
    "between",
    "through",
    "during",
    "each",
    "every",
    "some",
    "other",
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
    "checkout",
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


def expand_case_variants(term: str) -> list[str]:
    """Generate CamelCase and snake_case variants of a term.

    'SymbolExtractor' -> ['SymbolExtractor', 'symbol_extractor']
    'symbol_extractor' -> ['symbol_extractor', 'SymbolExtractor']
    'Router' (single word) -> ['Router']
    """
    variants = [term]

    # CamelCase -> snake_case
    parts = _CAMEL_SPLIT_RE.split(term)
    if len(parts) > 1:
        snake = "_".join(p.lower() for p in parts)
        if snake != term and snake not in variants:
            variants.append(snake)
        return variants

    # snake_case -> CamelCase
    if "_" in term:
        segments = term.split("_")
        if len(segments) > 1:
            camel = "".join(seg.capitalize() for seg in segments)
            if camel != term and camel not in variants:
                variants.append(camel)

    return variants


def is_import_query(queries: list[str]) -> bool:
    """Detect 'import X' or 'from X import Y' patterns that should route to text search."""
    combined = " ".join(queries).strip()
    # Match "import foo" but not "import_plan_file" (underscore-joined identifiers)
    return bool(
        re.match(r"^(?:from\s+\S+\s+)?import\s+\S", combined)
    )


def is_natural_language_query(queries: list[str]) -> bool:
    """Detect queries that are plain English with no code identifiers.

    Queries like 'scoring logic', 'search ranking algorithm', 'CREATE TABLE foo'
    should route to text search since they won't match symbol names.
    """
    combined = " ".join(queries).strip()
    # SQL DDL patterns should go to text search
    if re.match(r"(?i)^(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|SELECT)\s", combined):
        return True
    # If query contains code markers (underscores, dots, camelCase, backticks), it's code
    if re.search(r"[_`]|[a-z][A-Z]|\.\w", combined):
        return False
    # All-lowercase multi-word queries with no code signals → natural language
    words = combined.split()
    return len(words) >= 2 and combined == combined.lower() and not has_explicit_code_signal(queries)


def _try_add(candidate: str, terms: list[str], seen: set[str]) -> bool:
    """Add *candidate* to *terms* if unseen. Return True when the cap is reached."""
    lowered = candidate.lower()
    if lowered in seen:
        return False
    terms.append(candidate)
    seen.add(lowered)
    return len(terms) >= _MAX_TERMS


def _add_with_variants(
    base: str, terms: list[str], seen: set[str]
) -> bool:
    """Add *base* and its case variants. Return True when the cap is reached."""
    if _try_add(base, terms, seen):
        return True
    for variant in expand_case_variants(base):
        if variant != base and variant.lower() not in seen and _try_add(variant, terms, seen):
            return True
    return False


def extract_query_terms(queries: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    for query in queries:
        if len(query) <= 80 and _add_with_variants(query, terms, seen):
            return terms

        for token in query.replace("`", " ").replace(",", " ").split():
            candidate = token.strip("()[]{}:.;'\"")
            lowered = candidate.lower()
            if len(candidate) < 3 or lowered in seen or lowered in _STOP_WORDS:
                continue
            if _add_with_variants(candidate, terms, seen):
                return terms

    return terms


def nl_to_symbol_terms(queries: list[str]) -> list[str]:
    """Generate potential symbol names from natural language query words.

    E.g. "project selector" -> ["ProjectSelector", "project_selector"]
    """
    combined = " ".join(queries).strip()
    words = [w for w in combined.lower().split() if len(w) >= 2 and w not in _STOP_WORDS]
    if not words:
        return []

    terms: list[str] = []
    # Full phrase as CamelCase and snake_case
    if len(words) >= 2:
        camel = "".join(w.capitalize() for w in words)
        snake = "_".join(words)
        terms.append(camel)
        if snake != camel:
            terms.append(snake)

    # Individual words and their case variants
    for word in words:
        for variant in expand_case_variants(word):
            if variant not in terms:
                terms.append(variant)

    return terms[:_MAX_TERMS]


def has_explicit_code_signal(queries: list[str]) -> bool:
    combined = " ".join(queries).lower()
    if any(marker in combined for marker in _EXPLICIT_CODE_MARKERS):
        return True
    return any(term in combined for term in _CODE_SIGNAL_TERMS)


def meaningful_terms(text: str) -> list[str]:
    """Tokens of *text* with English stop words and short fragments removed."""
    return [term for term in text.split() if len(term) >= 3 and term not in _STOP_WORDS]


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
