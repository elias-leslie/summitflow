"""Precision Code Search CLI command."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

import typer

from .._output_state import is_compact
from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(help="Precision Code Search")


# ---------------------------------------------------------------------------
# Hint generation
# ---------------------------------------------------------------------------

_HINT_PREFIX = "hint: "


def _generate_hint(query: str, mode: str, metadata: dict) -> str | None:
    """Return an actionable refinement hint based on result quality, or None."""
    from app.services.context_gatherer._precision_query import (
        has_path_segments,
        is_short_or_generic,
    )

    queries = [query]

    if mode == "empty":
        if has_path_segments(queries):
            return "path terms reduce symbol precision. Try `st search --text <query>` or just the symbol name."
        if is_short_or_generic(queries):
            return "query is too short/generic for symbol matching. Try a specific function, class, or variable name."
        return "no symbols or text matched. Try `st search --text <query>` for content search, or refine to a specific identifier."

    if mode == "text-fallback":
        if has_path_segments(queries):
            return "fell back to text search (no symbol match). Path-qualified terms are noisy — try just the symbol name."
        return "fell back to text search (no symbol match). Narrower symbol/function names give better results."

    # Symbol-first with low match quality — check if results look incidental
    symbol_count = metadata.get("symbol_count", 0)
    if mode == "symbol-first" and symbol_count > 0:
        if has_path_segments(queries):
            return "path terms in symbol search may favor incidental mentions. Try `st search --text <query>` for file-content matches."
        if is_short_or_generic(queries):
            return "short/generic query may produce incidental symbol matches. Verify relevance or try a more specific identifier."

    return None


@app.command()
def search(
    query: Annotated[
        list[str] | None,
        typer.Argument(help="Search query (symbol name, function, class, endpoint)"),
    ] = None,
    budget: Annotated[
        int,
        typer.Option("--budget", "-b", help="Token budget for prompt context"),
    ] = 1200,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum primitive results"),
    ] = 20,
    text: Annotated[
        bool,
        typer.Option("--text", help="Use the text/content search primitive"),
    ] = False,
    symbols: Annotated[
        bool,
        typer.Option("--symbols", help="Use the symbol search primitive"),
    ] = False,
    raw_json: Annotated[
        bool,
        typer.Option("--json", "-j", help="Emit full JSON payload"),
    ] = False,
    file: Annotated[
        str | None,
        typer.Option("--file", "-f", help="List all symbols in a specific file"),
    ] = None,
    hint: Annotated[
        bool,
        typer.Option("--hint/--no-hint", help="Show refinement hints when results are poor"),
    ] = True,
) -> None:
    """Search codebase symbols, endpoints, and tables with Precision Code Search.

    Returns prompt-ready context with symbol source slices, related endpoints,
    and database tables. Uses indexed symbols first, falls back to file/endpoint
    matching when no symbols match.

    Examples:
        st search collect_precision_code_search_context
        st search "TaskOperationsMixin"
        st search router endpoint --budget 2000
        st search scan_history --json
    """
    q = " ".join(query).strip() if query else ""
    if not q and not file:
        typer.echo("Error: empty query", err=True)
        raise typer.Exit(1)
    if text and symbols:
        typer.echo("Error: choose at most one primitive mode", err=True)
        raise typer.Exit(1)

    client = STClient()

    if file:
        params = urlencode({"file_path": file, "limit": limit})
        try:
            result = client.get(client._url(f"/explorer/symbols/by-file?{params}"))
        except APIError as e:
            handle_api_error(e)
            return
        if raw_json:
            output_json(result)
            return
        if is_compact():
            _print_file_symbols_compact(file, result)
        else:
            output_json(result)
        return

    try:
        if text:
            params = urlencode({"q": q, "limit": limit})
            result = client.get(client._url(f"/explorer/text/search?{params}"))
        elif symbols:
            params = urlencode({"q": q, "limit": limit})
            result = client.get(client._url(f"/explorer/symbols/search?{params}"))
        else:
            params = urlencode({"q": q, "budget": budget, "limit": limit})
            result = client.get(client._url(f"/explorer/precision-search?{params}"))
    except APIError as e:
        handle_api_error(e)
        return

    if raw_json:
        output_json(result)
        return

    if is_compact():
        if text:
            _print_text_compact(q, result)
        elif symbols:
            _print_symbols_compact(q, result)
        else:
            _print_precision_compact(q, result.get("prompt_context", ""), result.get("metadata", {}), show_hint=hint)
    else:
        output_json(result)


def _print_precision_compact(
    query: str, prompt_context: str, metadata: dict, *, show_hint: bool = True
) -> None:
    """Print TOON-style compact output for agent consumption."""
    symbol_count = metadata.get("symbol_count", 0)
    mode = "symbol-first" if metadata.get("used_symbol_first") else "text-fallback"
    tokens_saved = metadata.get("estimated_tokens_saved", 0)
    final_tokens = metadata.get("final_tokens", 0)

    if not prompt_context:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0")
        if show_hint:
            hint_text = _generate_hint(query, "empty", metadata)
            if hint_text:
                print(f"{_HINT_PREFIX}{hint_text}")
        return

    print(
        f"SEARCH:{query}|mode={mode}|symbols={symbol_count}"
        f"|tokens={final_tokens}|saved={tokens_saved}"
    )
    if show_hint:
        hint_text = _generate_hint(query, mode, metadata)
        if hint_text:
            print(f"{_HINT_PREFIX}{hint_text}")
    print()
    print(prompt_context)


def _print_text_compact(query: str, result: dict) -> None:
    """Print TOON-style compact text search output."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)
    files_searched = result.get("files_searched", 0)

    if not items:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0")
        return

    print(f"SEARCH:{query}|mode=text|matches={count}|files={files_searched}")
    print()
    for item in items:
        if not isinstance(item, dict):
            continue
        print(f"- {item.get('path', 'unknown')}:{item.get('line', '?')} | {item.get('content', '')}")


def _print_symbols_compact(query: str, result: dict) -> None:
    """Print TOON-style compact symbol search output."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)

    if not items:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0")
        return

    print(f"SEARCH:{query}|mode=symbols|symbols={count}")
    print()
    for item in items:
        if not isinstance(item, dict):
            continue
        print(
            f"- `{item.get('qualified_name', item.get('name', 'unknown'))}` "
            f"({item.get('kind', 'unknown')}) {item.get('file_path', 'unknown')}:{item.get('start_line', '?')}"
        )


def _print_file_symbols_compact(file_path: str, result: dict) -> None:
    """Print TOON-style compact output for file symbol listing."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)

    if not items:
        print(f"SEARCH:--file {file_path}|mode=empty|symbols=0|tokens=0")
        return

    print(f"SEARCH:--file {file_path}|mode=file-symbols|symbols={count}")
    print()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind", "unknown")
        name = item.get("qualified_name", item.get("name", "unknown"))
        line = item.get("start_line", "?")
        sig = item.get("signature", "")
        summary = item.get("summary", "")
        detail = sig or summary
        suffix = f" - {detail}" if detail else ""
        print(f"- `{name}` ({kind}) :{line}{suffix}")
