"""Canonical public web research command surface."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import typer

from ..output import output_error

app = typer.Typer(
    help="Public web search, research, and fetch through the shared Agent Hub stack.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    add_help_option=False,
)

_AGENT_HUB_BACKEND = Path("/srv/workspaces/projects/agent-hub/backend")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="st web", description=app.info.help)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search the public web.")
    search.add_argument("query_arg", nargs="?")
    search.add_argument("--query")
    search.add_argument("--max-results", "--limit", dest="max_results", type=int, default=5)
    search.add_argument("--search-type", choices=("text", "news"), default="text")
    search.add_argument("--timelimit", choices=("d", "w", "m", "y"))

    research = subparsers.add_parser("research", help="Search first, then fetch one result.")
    research.add_argument("query_arg", nargs="?")
    research.add_argument("--query")
    research.add_argument("--max-results", "--limit", dest="max_results", type=int, default=5)
    research.add_argument("--result-index", type=int, default=1)
    research.add_argument("--search-type", choices=("text", "news"), default="text")
    research.add_argument("--timelimit", choices=("d", "w", "m", "y"))
    research.add_argument("--max-chars", type=int, default=12000)
    research.add_argument("--focus-query")

    fetch = subparsers.add_parser("fetch", help="Fetch and extract a webpage.")
    fetch.add_argument("url_arg", nargs="?")
    fetch.add_argument("--url")
    fetch.add_argument("--max-chars", type=int, default=12000)
    fetch.add_argument("--focus-query")
    return parser


def _required(primary: str | None, fallback: str | None, name: str) -> str:
    value = (primary or fallback or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _payload(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "search":
        return {
            "command": "search",
            "query": _required(args.query, args.query_arg, "--query"),
            "max_results": args.max_results,
            "search_type": args.search_type,
            "timelimit": args.timelimit,
        }
    if args.command == "research":
        return {
            "command": "research",
            "query": _required(args.query, args.query_arg, "--query"),
            "max_results": args.max_results,
            "result_index": args.result_index,
            "search_type": args.search_type,
            "timelimit": args.timelimit,
            "max_chars": args.max_chars,
            "focus_query": args.focus_query,
        }
    if args.command == "fetch":
        return {
            "command": "fetch",
            "url": _required(args.url, args.url_arg, "--url"),
            "max_chars": args.max_chars,
            "focus_query": args.focus_query,
        }
    raise ValueError(f"Unknown command: {args.command}")


def _agent_hub_python() -> str:
    candidate = _AGENT_HUB_BACKEND / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return "python3"


def _run_agent_hub_web(payload: dict[str, object]) -> int:
    if not _AGENT_HUB_BACKEND.exists():
        output_error(f"Agent Hub backend not found: {_AGENT_HUB_BACKEND}")
        return 1
    code = r"""
import asyncio
import json
import sys

from app.services.tools._executor_web import fetch_web_page, research_web, search_web


async def main() -> str:
    payload = json.loads(sys.argv[1])
    command = payload["command"]
    if command == "search":
        return await search_web(
            query=payload["query"],
            max_results=payload["max_results"],
            search_type=payload["search_type"],
            timelimit=payload.get("timelimit"),
        )
    if command == "research":
        return await research_web(
            query=payload["query"],
            max_results=payload["max_results"],
            result_index=payload["result_index"],
            search_type=payload["search_type"],
            timelimit=payload.get("timelimit"),
            max_chars=payload["max_chars"],
            focus_query=payload.get("focus_query"),
        )
    if command == "fetch":
        return await fetch_web_page(
            url=payload["url"],
            max_chars=payload["max_chars"],
            focus_query=payload.get("focus_query"),
        )
    return json.dumps({"error": f"unknown command: {command}"})


result = asyncio.run(main())
try:
    parsed = json.loads(result)
except json.JSONDecodeError:
    print(result)
    raise SystemExit(1)
print(json.dumps(parsed, indent=2, sort_keys=True))
raise SystemExit(0 if "error" not in parsed else 1)
"""
    result = subprocess.run(
        [_agent_hub_python(), "-c", code, json.dumps(payload)],
        cwd=_AGENT_HUB_BACKEND,
        check=False,
    )
    return result.returncode


@app.callback(invoke_without_command=True)
def web(ctx: typer.Context) -> None:
    """Run shared web research commands.

    Examples:
      st web search --query "SummitFlow" --limit 1
      st web fetch --url https://example.com --focus-query title
    """
    if ctx.invoked_subcommand is not None:
        return
    parser = _parser()
    try:
        parsed = parser.parse_args(list(ctx.args))
        payload = _payload(parsed)
    except SystemExit as exc:
        raise typer.Exit(exc.code if isinstance(exc.code, int) else 2) from None
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    raise typer.Exit(_run_agent_hub_web(payload))
