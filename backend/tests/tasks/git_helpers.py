"""Small git helper shared by the publication tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()
