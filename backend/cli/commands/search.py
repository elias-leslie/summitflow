"""Precision Code Search CLI command."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

import typer

from .._output_state import is_compact
from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(help="Precision Code Search")


@app.command()
def search(
    query: Annotated[
        list[str],
        typer.Argument(help="Search query (symbol name, function, class, endpoint)"),
    ],
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
    q = " ".join(query).strip()
    if not q:
        typer.echo("Error: empty query", err=True)
        raise typer.Exit(1)
    if text and symbols:
        typer.echo("Error: choose at most one primitive mode", err=True)
        raise typer.Exit(1)

    client = STClient()
    try:
        if text:
            params = urlencode({"q": q, "limit": limit})
            result = client.get(client._url(f"/explorer/text/search?{params}"))
        elif symbols:
            params = urlencode({"q": q, "limit": limit})
            result = client.get(client._url(f"/explorer/symbols/search?{params}"))
        else:
            params = urlencode({"q": q, "budget": budget})
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
            _print_precision_compact(q, result.get("prompt_context", ""), result.get("metadata", {}))
    else:
        output_json(result)


def _print_precision_compact(query: str, prompt_context: str, metadata: dict) -> None:
    """Print TOON-style compact output for agent consumption."""
    symbol_count = metadata.get("symbol_count", 0)
    mode = "symbol-first" if metadata.get("used_symbol_first") else "text-fallback"
    tokens_saved = metadata.get("estimated_tokens_saved", 0)
    final_tokens = metadata.get("final_tokens", 0)

    if not prompt_context:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0")
        return

    print(
        f"SEARCH:{query}|mode={mode}|symbols={symbol_count}"
        f"|tokens={final_tokens}|saved={tokens_saved}"
    )
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
