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
resolve_current_transcript = _load_symbol("codex_sync_transcripts", "resolve_current_transcript")

DEFAULT_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
_SOURCE_PATH = str(Path(__file__))


def log(message: str) -> None:
    """Use the caller's streams so systemd applies the host journal policy."""
    timestamp = datetime.now(UTC).isoformat()
    stream = sys.stderr if message.startswith(("[WARN]", "[ERROR]")) else sys.stdout
    print(f"[{timestamp}] {message}", file=stream, flush=True)


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
        help="Show per-session success entries in addition to the sync summary",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    binding_mode = args.bind_session is not None
    synced = 0
    warnings = 0

    def emit(message: str) -> None:
        nonlocal synced, warnings
        if message.startswith("[INFO] Synced session="):
            synced += 1
            if not args.verbose:
                return
        if message.startswith("[WARN]"):
            warnings += 1
        log(message)

    binding_values = (args.bind_session, args.bind_project, args.project_root)
    if any(value is not None for value in binding_values) and not all(
        value is not None for value in binding_values
    ):
        emit(
            "[WARN] Binding requires --bind-session, --bind-project, and --project-root"
        )
        return 2
    if binding_mode:
        try:
            current = resolve_current_transcript()
        except ValueError as exc:
            emit(f"[WARN] {exc}")
            return 2
        if args.bind_session != current.session_id:
            emit("[WARN] --bind-session must match the validated current native Codex thread ID")
            return 2
    if not args.scan and args.transcript is None:
        args.scan = True

    client_id = load_env_credentials()
    if not client_id:
        emit("[WARN] Missing SUMMITFLOW_CLIENT_ID; skipping Codex sync")
        return 2 if binding_mode else 0

    # The runner's verbose flag only emits successful sync events. Collect those
    # events for a compact summary without changing direct CLI verbosity.
    sync_args = argparse.Namespace(**vars(args))
    sync_args.verbose = True
    exit_code = run_sync(
        sync_args,
        api_url=DEFAULT_API,
        client_id=client_id,
        source_path=_SOURCE_PATH,
        log_fn=emit,
    )
    level = "INFO" if exit_code == 0 else "ERROR"
    log(f"[{level}] Codex sync completed status={exit_code} synced={synced} warnings={warnings}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
