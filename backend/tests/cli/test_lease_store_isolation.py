"""Tests never write the host lease store (~/.summitflow/leases), in process or from st/hook children."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cli.lib import leases

BACKEND = Path(__file__).parents[2]
HOST_STORE = Path.home() / ".summitflow" / "leases"


def test_lease_store_is_redirected_for_this_process_and_children() -> None:
    child = subprocess.run(
        [sys.executable, "-c", "from cli.lib import leases; print(leases.LEASES_DIR)"],
        cwd=BACKEND, text=True, capture_output=True, check=True,
    )

    assert leases.LEASES_DIR != HOST_STORE
    assert Path(child.stdout.strip()) == leases.LEASES_DIR
