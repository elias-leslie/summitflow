#!/usr/bin/env python3
"""Sync Codex transcript analysis into Agent Hub without waiting for process exit."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure scripts/lib is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent / "lib"))


def _load_symbol(module_name: str, symbol: str) -> Any:
    return getattr(importlib.import_module(module_name), symbol)


load_env_credentials = _load_symbol("codex_sync_credentials", "load_env_credentials")
run_sync = _load_symbol("codex_sync_runner", "run_sync")

DEFAULT_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
LOG_PATH = Path.home() / ".codex" / "session-integrations" / "codex-session-sync.log"
_SOURCE_PATH = str(Path(__file__))


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="Scan recent Codex transcripts")
    parser.add_argument("--transcript", type=Path, help="Sync a specific transcript path")
    parser.add_argument("--recent-hours", type=int, default=24, help="Recent hours to scan")
    parser.add_argument("--cwd", type=Path, help="Only scan transcripts from this working directory")
    parser.add_argument(
        "--close",
        action="store_true",
        help="Close the Agent Hub session after analysis",
    )
    parser.add_argument(
        "--close-inactive",
        action="store_true",
        help="Close synced Codex sessions whose transcript is no longer open by a live Codex process",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sync even if transcript state is unchanged",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Write success entries to the sync log",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.scan and args.transcript is None:
        args.scan = True

    client_id = load_env_credentials()
    if not client_id:
        log("[WARN] Missing SUMMITFLOW_CLIENT_ID; skipping Codex sync")
        return 0

    return run_sync(
        args,
        api_url=DEFAULT_API,
        client_id=client_id,
        source_path=_SOURCE_PATH,
        log_fn=log,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
