"""The seam to Aico's coordination verbs: `st lease`, `st sessions send|ack|confirm|inbox` and `st pulse` call `aico`;
and to its gate: `st check` and `st commit` call `aico check` and `aico commit` (``checks_enabled``, ``run_checks``).

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

The gate rollback is separate: remove the verb from ``AICO_GATE_VERBS`` (or set ``ST_AICO_CHECKS=0``) and
SummitFlow's own `st check` / `st commit` runs. Aico answers
exit 3 (``NOT_HANDLED``) for a repo or option it does not run, and SummitFlow's code then runs as before.

The ops verbs (Aico's packages/ops) roll back the same way: drop the verb from ``AICO_OPS_VERBS`` (or set
``ST_AICO_OPS=0`` for all). ``logs`` passes `st logs -s UNIT` for one unit or project; ``snapshots`` passes
`st snap|snaps|rollback` for a Btrfs project root; ``vm`` passes `st vm list|status|start|stop|snapshot`;
``rebuild`` passes `st service rebuild|result|wait` for Aico. Anything else answers NOT_HANDLED.

`st web` calls `aico web` (Aico's packages/webtools: search, research, fetch, batch, refocus, the call counter)
through the ``web-details`` extension (``web_command``); anything Aico does not run (Lightpanda, doctor, benchmark,
--selector, --wait-script) answers NOT_HANDLED and Agent Hub's own executable runs as before. Rollback:
``ST_AICO_WEB=0`` (or no ``aico`` on PATH) sends every call to Agent Hub again.
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


NOT_HANDLED = 3


# The gate verbs that call Aico. Rollback: drop a verb here, or ST_AICO_CHECKS=0 for all (=1 turns all on).
AICO_GATE_VERBS: frozenset[str] = frozenset({"check"})


def checks_enabled(verb: str) -> bool:
    switch = os.environ.get("ST_AICO_CHECKS", "")
    if switch == "0" or (switch != "1" and verb not in AICO_GATE_VERBS):
        return False
    return shutil.which("aico") is not None


def run_checks(*argv: str) -> int:
    """``aico check|commit ...``; NOT_HANDLED (silently) when Aico does not run this repo's gate."""
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(["aico", *argv], check=False, env={**os.environ, "AICO_CHECKS_CALLER": "st"}).returncode


def run(*argv: str) -> int:
    """Run ``aico`` with the caller's stdio and environment; its exit code."""
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(["aico", *argv], check=False).returncode


# The ops verbs that call Aico. Rollback: drop a verb here, or ST_AICO_OPS=0 for all (=1 turns all on).
AICO_OPS_VERBS: frozenset[str] = frozenset({"logs", "vm"})


def ops_enabled(verb: str) -> bool:
    switch = os.environ.get("ST_AICO_OPS", "")
    if switch == "0" or (switch != "1" and verb not in AICO_OPS_VERBS):
        return False
    return shutil.which("aico") is not None


def run_ops(*argv: str) -> int:
    """``aico deploy|logs|snapshots|vm ...``; NOT_HANDLED (silently) for what Aico does not run."""
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(["aico", *argv], check=False, env={**os.environ, "AICO_OPS_CALLER": "st"}).returncode


def try_ops(verb: str, *argv: str) -> int | None:
    """``aico ARGV``'s exit code when ``verb`` is cut over and Aico runs it; None means run SummitFlow's code."""
    if not ops_enabled(verb):
        return None
    code = run_ops(*argv)
    return None if code == NOT_HANDLED else code


def web_command() -> str | None:
    """The ``aico`` executable `st web` calls, or None when it is rolled back (``ST_AICO_WEB=0``) or not installed."""
    if os.environ.get("ST_AICO_WEB", "1") == "0":
        return None
    return shutil.which("aico")
