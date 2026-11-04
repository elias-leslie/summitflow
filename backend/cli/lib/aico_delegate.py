"""The seam to Aico's coordination verbs: `st lease`, `st sessions send|ack|confirm|inbox` and `st pulse` call `aico`.

Aico owns leases, handshakes, the inbox and the pulse (Tether's coordination documents); SummitFlow keeps
the verbs agents already type and passes them on.

Rollback. ``ST_AICO_COORD=0`` (or no ``aico`` on PATH) covers only these verbs: it runs the SummitFlow code,
which reads and writes the same Tether documents through ``coord_store``. The hooks are separate config; a full
rollback also reverts them:

- the inbox hook entries: claude-config 7b30ca9 (settings.json) and codex-config 7334282 (hooks.json), back to
  ``~/.claude/hooks/coord-inbox.sh turn|stop|watch``;
- the Pi extension and the startup brief: aico 40a2367e (native/hook/pi/aico-hook.ts back to coord-inbox.sh,
  native/hook/data/hook.json ``startup_brief`` back to SummitFlow's pulse), then reinstall aico-hook.

The edit lease hook (aico-hook) stays either way: it has no SummitFlow counterpart since M7a. The data is not
moved back: the old ``~/.summitflow/leases`` files are M12's archive, and only ``ST_LEASES_DIR`` reads them.
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
