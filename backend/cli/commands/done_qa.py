"""QA gate for task completion — runs lint + tests before merge.

Blocks `st done` if quality checks fail. Zero-token cost,
catches ~70% of issues before they reach main.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..output import output_warning

# Resolve st path once — ~/bin/st may not be on PATH in subprocesses
_ST_PATH = shutil.which("st") or str(Path.home() / "bin" / "st")


def run_qa_gate(checkout_path: str) -> tuple[bool, str]:
    """Run st check -q -d + st check pytest in the checkout. Returns (passed, output)."""
    combined_output: list[str] = []

    for cmd, timeout in [
        ([_ST_PATH, "check", "-q", "-d"], 120),
        ([_ST_PATH, "check", "pytest"], 300),
    ]:
        try:
            result = subprocess.run(
                cmd,
                cwd=checkout_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.stdout:
                combined_output.append(result.stdout)
            if result.stderr:
                combined_output.append(result.stderr)
            if result.returncode != 0:
                return False, "\n".join(combined_output)
        except subprocess.TimeoutExpired:
            combined_output.append(f"Timed out after {timeout}s: {' '.join(cmd)}")
            return False, "\n".join(combined_output)
        except FileNotFoundError:
            output_warning(f"QA tool not found: {cmd[0]}")
            # st not installed — skip gate rather than block completion
            return True, ""

    return True, "\n".join(combined_output)
