#!/usr/bin/env python3
"""Retry SummitFlow's managed Codex outboxes through Agent Hub.

Runs on summitflow-codex-managed-drain.timer. Each configured project spool is
recovered independently and keeps draining while new managed capture is off.
Codex transcript sync itself is Agent Hub's (its codex-session-sync timer).
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

DEFAULT_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")


def log(message: str) -> None:
    stream = sys.stderr if message.startswith(("[WARN]", "[ERROR]")) else sys.stdout
    print(f"[{datetime.now(UTC).isoformat()}] {message}", file=stream, flush=True)


def main() -> int:
    try:
        from codex_managed_delivery import recover_configured_outboxes

        statuses = recover_configured_outboxes(DEFAULT_API)
    except Exception:  # noqa: BLE001 - one bad spool must not fail the timer loudly every run
        log("[WARN] Managed Codex delivery unavailable")
        return 0
    for status in statuses:
        log(
            f"[INFO] Managed Codex delivery health={status['health']} "
            f"pending={status['pending']} gaps={status['capture_gaps']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
