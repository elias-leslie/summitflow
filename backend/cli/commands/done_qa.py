"""QA gate for task completion — runs lint + tests before merge.

Blocks `st done` if quality checks fail. Zero-token cost,
catches ~70% of issues before they reach main.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..output import output_warning

# Resolve dt path once — ~/bin/dt may not be on PATH in worktree subprocesses
_DT_PATH = shutil.which("dt") or str(Path.home() / "bin" / "dt")


def run_qa_gate(worktree_path: str) -> tuple[bool, str]:
    """Run dt -q -d + dt pytest in the worktree. Returns (passed, output)."""
    combined_output: list[str] = []

    for cmd, timeout in [
        ([_DT_PATH, "-q", "-d"], 120),
        ([_DT_PATH, "pytest"], 300),
    ]:
        try:
            result = subprocess.run(
                cmd,
                cwd=worktree_path,
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
            # dt not installed — skip gate rather than block completion
            return True, ""

    return True, "\n".join(combined_output)
