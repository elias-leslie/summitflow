"""The seam to Aico's coordination verbs: `st lease`, `st sessions send|ack|confirm|inbox` and `st pulse` call `aico`.

Aico owns leases, handshakes, the inbox and the pulse (Tether's coordination documents); SummitFlow keeps
the verbs agents already type and passes them on. Rollback: ``ST_AICO_COORD=0`` (or no ``aico`` on PATH)
runs the SummitFlow code, which reads the same documents through ``coord_store``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def enabled() -> bool:
    if os.environ.get("ST_AICO_COORD", "1") == "0" or "ST_LEASES_DIR" in os.environ:
        return False  # rolled back, or tests/old files selected
    return shutil.which("aico") is not None


def run(*argv: str) -> int:
    """Run ``aico`` with the caller's stdio and environment; its exit code."""
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(["aico", *argv], check=False).returncode
