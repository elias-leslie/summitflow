"""Canonical public web research command surface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import typer

from ..details import current_root, display_path, summary_hint, write_details
from ..output import output_error

app = typer.Typer(
    help="Public web search, research, and fetch through the shared Agent Hub stack.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    add_help_option=False,
)

_AGENT_HUB_BACKEND = Path(os.environ.get("AGENT_HUB_BACKEND_PATH", "../agent-hub/backend"))
if "AGENT_HUB_BACKEND_PATH" not in os.environ:
    _AGENT_HUB_BACKEND = Path(__file__).resolve().parents[4] / "agent-hub" / "backend"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="st web", description=app.info.help)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search the public web.")
    search.add_argument("query_arg", nargs="?")
    search.add_argument("--query")
    search.add_argument("--max-results", "--limit", dest="max_results", type=int, default=5)
    search.add_argument("--search-type", choices=("text", "news"), default="text")
    search.add_argument("--timelimit", choices=("d", "w", "m", "y"))
    search.add_argument("--raw", action="store_true")

    research = subparsers.add_parser("research", help="Search first, then fetch one result.")
    research.add_argument("query_arg", nargs="?")
    research.add_argument("--query")
    research.add_argument("--max-results", "--limit", dest="max_results", type=int, default=5)
    research.add_argument("--result-index", type=int, default=1)
    research.add_argument("--search-type", choices=("text", "news"), default="text")
    research.add_argument("--timelimit", choices=("d", "w", "m", "y"))
    research.add_argument("--max-chars", type=int, default=12000)
    research.add_argument("--focus-query")
    research.add_argument("--backend", choices=("auto", "direct", "jina"), default="auto")
    research.add_argument("--raw", action="store_true")

    fetch = subparsers.add_parser("fetch", help="Fetch and extract a webpage.")
    fetch.add_argument("url_arg", nargs="?")
    fetch.add_argument("--url")
    fetch.add_argument("--max-chars", type=int, default=12000)
    fetch.add_argument("--focus-query")
    fetch.add_argument("--backend", choices=("auto", "direct", "jina"), default="auto")
    fetch.add_argument("--raw", action="store_true")

    benchmark = subparsers.add_parser("benchmark", help="Run deterministic local st web fetch benchmarks.")
    benchmark.add_argument("--iterations", type=int, default=3)
    benchmark.add_argument("--max-chars", type=int, default=800)
    benchmark.add_argument("--raw", action="store_true")
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
            "raw": args.raw,
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
            "backend": args.backend,
            "raw": args.raw,
        }
    if args.command == "fetch":
        return {
            "command": "fetch",
            "url": _required(args.url, args.url_arg, "--url"),
            "max_chars": args.max_chars,
            "focus_query": args.focus_query,
            "backend": args.backend,
            "raw": args.raw,
        }
    if args.command == "benchmark":
        return {
            "command": "benchmark",
            "iterations": max(1, min(args.iterations, 10)),
            "max_chars": max(100, min(args.max_chars, 5000)),
            "raw": args.raw,
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
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.services.tools._executor_web import fetch_web_page, research_web, search_web


class _BenchmarkHandler(BaseHTTPRequestHandler):
    PRODUCT_HTML = '''<!doctype html><html><head><title>Benchmark Olive Oil</title></head><body>
<article>
<h1>Pompeian Robust Extra Virgin Olive Oil</h1>
<p>Price: $38.79.</p>
<p>Package size: 68 fl oz.</p>
<p>Unit price: $0.57/fl oz.</p>
<p>Pickup store: deterministic local benchmark.</p>
</article>
</body></html>'''
    FOCUS_MARKDOWN = '''# Benchmark Focus

Unrelated filler alpha about pantry planning, delivery windows, and membership notes.

Olive oil benchmark target: Pompeian robust extra virgin olive oil is $38.79 for 68 fl oz, equal to $0.57/fl oz, verified deterministic comparison benchmark data for unit-price extraction.

Unrelated filler omega about snacks, paper goods, rice, coffee, and storage bins.'''

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_GET(self) -> None:
        if self.path == "/product":
            body = self.PRODUCT_HTML
            content_type = "text/html; charset=utf-8"
        elif self.path == "/focus":
            body = self.FOCUS_MARKDOWN
            content_type = "text/markdown; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _case_result(
    name: str,
    *,
    elapsed_ms: float,
    payload: dict[str, object],
    checks: dict[str, bool],
) -> dict[str, object]:
    output_chars = len(json.dumps(payload, sort_keys=True))
    content = str(payload.get("content") or "")
    passed = "error" not in payload and all(checks.values())
    return {
        "name": name,
        "passed": passed,
        "elapsed_ms": round(elapsed_ms, 2),
        "output_chars": output_chars,
        "content_chars": len(content),
        "fetch_backend": payload.get("fetch_backend"),
        "checks": checks,
    }


async def benchmark_web(iterations: int, max_chars: int) -> str:
    iterations = max(1, min(int(iterations), 10))
    max_chars = max(100, min(int(max_chars), 5000))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BenchmarkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    cases: list[dict[str, object]] = []
    try:
        for iteration in range(1, iterations + 1):
            started = time.perf_counter()
            product = json.loads(await fetch_web_page(
                f"{base_url}/product",
                max_chars=max_chars,
                focus_query="olive oil price 68 fl oz unit price",
                backend="direct",
            ))
            product_content = str(product.get("content") or "")
            cases.append(_case_result(
                f"product_unit_price_{iteration}",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                payload=product,
                checks={
                    "backend_direct": product.get("fetch_backend") == "direct",
                    "has_price": "$38.79" in product_content,
                    "has_quantity": "68 fl oz" in product_content,
                    "has_unit_price": "$0.57/fl oz" in product_content,
                    "content_within_budget": len(product_content) <= max_chars,
                    "output_token_efficient": len(json.dumps(product, sort_keys=True)) <= max_chars + 1600,
                },
            ))

            started = time.perf_counter()
            focused = json.loads(await fetch_web_page(
                f"{base_url}/focus",
                max_chars=220,
                focus_query="olive oil 68 fl oz unit price",
                backend="direct",
            ))
            focused_content = str(focused.get("content") or "")
            cases.append(_case_result(
                f"focus_budget_{iteration}",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                payload=focused,
                checks={
                    "focused": focused.get("focused") is True,
                    "has_target": "$0.57/fl oz" in focused_content,
                    "drops_unrelated_tail": "Unrelated filler omega" not in focused_content,
                    "content_within_budget": len(focused_content) <= 220,
                    "output_token_efficient": len(json.dumps(focused, sort_keys=True)) <= 1800,
                },
            ))

        started = time.perf_counter()
        invalid = json.loads(await fetch_web_page("file:///tmp/not-web", backend="direct"))
        invalid_checks = {
            "reports_error": "error" in invalid,
            "mentions_http": "http://" in str(invalid.get("error") or ""),
            "output_token_efficient": len(json.dumps(invalid, sort_keys=True)) <= 400,
        }
        cases.append({
            "name": "invalid_scheme_error",
            "passed": all(invalid_checks.values()),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "output_chars": len(json.dumps(invalid, sort_keys=True)),
            "content_chars": 0,
            "fetch_backend": None,
            "checks": invalid_checks,
        })
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    passed = all(bool(case["passed"]) for case in cases)
    return json.dumps({
        "benchmark": "st web deterministic fetch",
        "deterministic_goal": "all semantic extraction checks pass and benchmark payloads stay within fixed char budgets",
        "iterations": iterations,
        "max_chars": max_chars,
        "case_count": len(cases),
        "passed": passed,
        "max_output_chars": max(int(case["output_chars"]) for case in cases),
        "max_elapsed_ms": max(float(case["elapsed_ms"]) for case in cases),
        "cases": cases,
    }, indent=2, sort_keys=True)


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
            backend=payload.get("backend", "auto"),
        )
    if command == "fetch":
        return await fetch_web_page(
            url=payload["url"],
            max_chars=payload["max_chars"],
            focus_query=payload.get("focus_query"),
            backend=payload.get("backend", "auto"),
        )
    if command == "benchmark":
        return await benchmark_web(
            iterations=payload.get("iterations", 3),
            max_chars=payload.get("max_chars", 800),
        )
    return json.dumps({"error": f"unknown command: {command}"})


result = asyncio.run(main())
try:
    parsed = json.loads(result)
except json.JSONDecodeError:
    print(result)
    raise SystemExit(1)
print(json.dumps(parsed, sort_keys=True))
if json.loads(sys.argv[1]).get("command") == "benchmark" and parsed.get("passed") is False:
    raise SystemExit(1)
raise SystemExit(0 if "error" not in parsed else 1)
"""
    result = subprocess.run(
        [_agent_hub_python(), "-c", code, json.dumps(payload)],
        cwd=_AGENT_HUB_BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if payload.get("raw"):
        print(output)
        return result.returncode
    root = current_root()
    details = write_details(root, f"web-{payload['command']}", output)
    print(
        f"WEB:{payload['command']}:{'OK' if result.returncode == 0 else 'FAIL'}:{result.returncode}|"
        f"details:{display_path(root, details)}|hint:{summary_hint(output)}"
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
