#!/usr/bin/env python3
"""Run host-side agent observability sync jobs in one place."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_CODEX_RECENT_HOURS = 24


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _python_bin() -> str:
    override = os.environ.get("AGENT_OBSERVABILITY_SYNC_PYTHON")
    return override or sys.executable


def _commands(*, include_tmux: bool, include_codex: bool, verbose: bool) -> list[list[str]]:
    repo_root = _repo_root()
    python_bin = _python_bin()
    commands: list[list[str]] = []

    if include_tmux:
        commands.append([python_bin, str(repo_root / "scripts" / "tmux-agent-session-sync.py")])

    if include_codex:
        recent_hours = os.environ.get("AGENT_OBSERVABILITY_CODEX_RECENT_HOURS", str(DEFAULT_CODEX_RECENT_HOURS))
        cmd = [
            python_bin,
            str(repo_root / "scripts" / "codex-session-sync.py"),
            "--scan",
            "--recent-hours",
            recent_hours,
        ]
        if verbose:
            cmd.append("--verbose")
        commands.append(cmd)

    return commands


def _run_command(args: list[str], *, timeout: float, best_effort: bool) -> int:
    try:
        result = subprocess.run(args, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if best_effort:
            return 0
        print(f"agent-observability-sync failed: {' '.join(args)}: {exc}", file=sys.stderr)
        return 1

    if result.returncode != 0 and not best_effort:
        return result.returncode
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--best-effort", action="store_true", help="Never fail the caller on sync errors")
    parser.add_argument("--skip-tmux", action="store_true", help="Skip external tmux presence sync")
    parser.add_argument("--skip-codex", action="store_true", help="Skip Codex transcript sync")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Per-command timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="Pass verbose mode through to subcommands when supported")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    commands = _commands(
        include_tmux=not args.skip_tmux,
        include_codex=not args.skip_codex,
        verbose=args.verbose,
    )
    for command in commands:
        exit_code = _run_command(command, timeout=max(args.timeout, 1.0), best_effort=args.best_effort)
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
