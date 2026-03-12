#!/usr/bin/env python3
"""Search or profile Precision Code Search for local agent workflows."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lib.ensure_backend_venv  # noqa: E402, F401  (venv re-exec + sys.path side-effect)

REPO_ROOT = Path(__file__).resolve().parents[1]
QUIET_LOGS = True

from app.services.context_gatherer import collect_precision_code_search_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="Keep application logs enabled")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Render prompt-ready Precision Code Search context")
    search_parser.add_argument("query", nargs="+", help="Search query")
    search_parser.add_argument("--project", default=REPO_ROOT.name, help="Project id to search")
    search_parser.add_argument("--budget", type=int, default=1200, help="Token budget for prompt context")
    search_parser.add_argument("--json", action="store_true", help="Emit JSON payload instead of plain text")

    profile_parser = subparsers.add_parser("profile", help="Compare Precision Code Search to rg")
    profile_parser.add_argument("query", nargs="+", help="One or more benchmark queries")
    profile_parser.add_argument("--project", default=REPO_ROOT.name, help="Project id to search")
    profile_parser.add_argument("--budget", type=int, default=1200, help="Token budget for prompt context")
    profile_parser.add_argument(
        "--rg-root",
        default=str(REPO_ROOT),
        help="Repo root for rg baseline",
    )
    profile_parser.add_argument(
        "--rg-limit",
        type=int,
        default=20,
        help="Max rg lines to include in the baseline sample",
    )

    return parser.parse_args()


def configure_logging(verbose: bool) -> None:
    """Suppress application logs unless explicitly requested."""
    global QUIET_LOGS
    QUIET_LOGS = not verbose
    if verbose:
        return
    for name in ("root", "app", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)


def run_precision_search(project_id: str, query: str, budget: int) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    if QUIET_LOGS:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = collect_precision_code_search_context(project_id, [query], budget_tokens=budget)
    else:
        result = collect_precision_code_search_context(project_id, [query], budget_tokens=budget)
    duration_ms = (time.perf_counter() - started) * 1000
    payload = {
        "query": query,
        "prompt_context": result.prompt_context,
        "chars": len(result.prompt_context),
        "metadata": result.metadata,
    }
    return duration_ms, payload


def run_rg_search(query: str, rg_root: str, limit: int) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    completed = subprocess.run(
        ["rg", "-n", "--hidden", "--glob", "!.git", query, rg_root],
        capture_output=True,
        text=True,
        check=False,
    )
    duration_ms = (time.perf_counter() - started) * 1000
    lines = completed.stdout.splitlines()
    sample = "\n".join(lines[:limit])
    payload = {
        "query": query,
        "chars": len(sample),
        "matches": len(lines),
        "sample": sample,
        "returncode": completed.returncode,
    }
    return duration_ms, payload


def choose_preference(precision: dict[str, object], rg: dict[str, object]) -> str:
    metadata = precision.get("metadata", {})
    if not isinstance(metadata, dict):
        return "rg"

    if metadata.get("used_symbol_first") and int(metadata.get("estimated_tokens_saved", 0)) > 0:
        return "precision"

    precision_chars = int(precision.get("chars", 0))
    rg_chars = int(rg.get("chars", 0))
    if metadata.get("used_symbol_first") and precision_chars and rg_chars and precision_chars <= rg_chars:
        return "precision"

    return "rg"


def handle_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    duration_ms, payload = run_precision_search(args.project, query, args.budget)
    payload["duration_ms"] = round(duration_ms, 1)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    prompt_context = str(payload["prompt_context"])
    print(prompt_context or "(no precision context)")
    print()
    print(
        "meta:",
        json.dumps(
            {
                "duration_ms": payload["duration_ms"],
                "chars": payload["chars"],
                "metadata": payload["metadata"],
            },
            sort_keys=True,
        ),
    )
    return 0


def handle_profile(args: argparse.Namespace) -> int:
    print("query\tprefer\tpcs_ms\tpcs_chars\trg_ms\trg_chars\trg_matches\tsymbols\test_saved")
    for query in args.query:
        pcs_ms, precision = run_precision_search(args.project, query, args.budget)
        rg_ms, rg_payload = run_rg_search(query, args.rg_root, args.rg_limit)
        metadata = precision.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        prefer = choose_preference(precision, rg_payload)
        print(
            f"{query}\t{prefer}\t{pcs_ms:.1f}\t{precision['chars']}\t"
            f"{rg_ms:.1f}\t{rg_payload['chars']}\t{rg_payload['matches']}\t"
            f"{metadata.get('symbol_count', 0)}\t{metadata.get('estimated_tokens_saved', 0)}"
        )
    return 0


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    if args.command == "search":
        return handle_search(args)
    if args.command == "profile":
        return handle_profile(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
