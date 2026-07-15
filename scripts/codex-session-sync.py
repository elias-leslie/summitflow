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
        "--bind-session",
        help="Bind one live Codex thread id to an explicit registered project",
    )
    parser.add_argument(
        "--bind-project",
        help="Registered project id for --bind-session",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="Canonical registered project root for --bind-session",
    )
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
    binding_mode = args.bind_session is not None

    def emit(message: str) -> None:
        log(message)
        if binding_mode and message.startswith("[WARN]"):
            print(message, file=sys.stderr)

    binding_values = (args.bind_session, args.bind_project, args.project_root)
    if any(value is not None for value in binding_values) and not all(
        value is not None for value in binding_values
    ):
        emit(
            "[WARN] Binding requires --bind-session, --bind-project, and --project-root"
        )
        return 2
    current_thread_id = (os.environ.get("CODEX_THREAD_ID") or "").strip()
    if binding_mode and args.bind_session != current_thread_id:
        emit("[WARN] --bind-session must match the current CODEX_THREAD_ID")
        return 2
    if not args.scan and args.transcript is None:
        args.scan = True

    client_id = load_env_credentials()
    if not client_id:
        emit("[WARN] Missing SUMMITFLOW_CLIENT_ID; skipping Codex sync")
        return 2 if binding_mode else 0

    return run_sync(
        args,
        api_url=DEFAULT_API,
        client_id=client_id,
        source_path=_SOURCE_PATH,
        log_fn=emit,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
