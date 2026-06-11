"""Refinement hints for compact `st search` output."""

from __future__ import annotations

from typing import Any

HINT_PREFIX = "hint: "


def generate_hint(query: str, mode: str, metadata: dict[str, Any]) -> str | None:
    """Return an actionable refinement hint based on result quality, or None."""
    from app.services.context_gatherer._precision_query import (
        has_path_segments,
        is_short_or_generic,
    )

    queries = [query]
    missed_terms = (
        []
        if metadata.get("checkout_overlay_applied")
        else list(metadata.get("missed_identifier_terms") or [])
    )

    if mode == "empty":
        if missed_terms:
            suppressed = int(metadata.get("suppressed_generic_symbols") or 0)
            junk_note = (
                f" ({suppressed} symbols matching only the other words were withheld as junk)"
                if suppressed
                else ""
            )
            if metadata.get("checkout_escalation_empty"):
                return (
                    f"`{missed_terms[0]}` matched no symbols or text{junk_note}, and a live parse of the "
                    "checkout found no definition either — the identifier does not exist as written; "
                    "verify the name or search for a different term."
                )
            return (
                f"`{missed_terms[0]}` matched no symbols or text{junk_note} — verify the identifier name; "
                "if it is brand-new code, rerun with `--scope checkout` or rescan the project."
            )
        used_fallback = metadata.get("used_fallback", False)
        files_searched = metadata.get("text_files_searched", 0)
        if has_path_segments(queries):
            return "path terms reduce symbol precision. Try just the symbol name, `st search --path <subtree> --text <query>` for subtree text matches, or `st search --file <path>` to list symbols in a file."
        if is_short_or_generic(queries):
            return "query is too short/generic for symbol matching. Try a specific function, class, or variable name."
        if used_fallback or files_searched > 0:
            return f"searched {files_searched} files — no symbol or text matches. Try a shorter/different identifier, or `st search --file <path>` to browse symbols in a known file."
        return "no symbol matches. Try `st search --text <query>` for content search, or refine to a specific identifier."

    if mode == "text-fallback":
        definition_terms = metadata.get("definition_matched_terms") or []
        if definition_terms:
            age = metadata.get("symbol_index_age_minutes")
            age_note = f" (index age {age}m)" if isinstance(age, int) and age > 0 else ""
            if metadata.get("checkout_escalation_empty"):
                return (
                    f"text matches include a definition of `{definition_terms[0]}` that the symbol index missed{age_note}, "
                    "and a live checkout parse also found no symbol — rescan the project instead of reshaping the query."
                )
            return (
                f"text matches include a definition of `{definition_terms[0]}` that the symbol index missed{age_note} — "
                "index likely stale; rerun with `--scope checkout` or rescan the project instead of reshaping the query."
            )
        if missed_terms and metadata.get("text_per_term_union"):
            return (
                f"`{missed_terms[0]}` matched no symbols or text — the matches shown cover only the other "
                "query words; verify the identifier or rescan if it is brand-new code."
            )
        if has_path_segments(queries):
            return "fell back to text search (no symbol match). Path-qualified terms are noisy — try just the symbol name or use `--path` with `--text` for subtree content search."
        return "fell back to text search (no symbol match). Try a specific identifier like `FunctionName` or `function_name`."

    symbol_count = metadata.get("symbol_count", 0)
    if mode in ("symbol-first", "combined") and symbol_count > 0:
        if missed_terms:
            return (
                f"`{missed_terms[0]}` matched nothing — these results cover only the other query terms; "
                "verify that identifier or search for it alone."
            )
        if has_path_segments(queries):
            return "path terms in symbol search may favor incidental mentions. Try `st search --path <subtree> --text <query>` for subtree file-content matches."
        if is_short_or_generic(queries):
            return "short/generic query may produce incidental symbol matches. Verify relevance or try a more specific identifier."

    return None
