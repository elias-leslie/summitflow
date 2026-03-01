"""Quality gate execution and auto-fix logic."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ....logging_config import get_logger
from .events import emit_log
from .git_ops import auto_commit, has_uncommitted_changes
from .quality import auto_fix_quality, run_final_quality_gate
from .quality_utils import find_dev_tools

logger = get_logger(__name__)


def run_quality_gate_with_autofix(
    task_id: str,
    project_path: str,
    project_id: str,
) -> bool:
    """Run quality gate with auto-fix retry if it fails.

    Args:
        task_id: The task ID
        project_path: Path to project directory
        project_id: The project ID

    Returns:
        True if quality gate passed (either initially or after auto-fix), False otherwise
    """
    final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)

    if not final_gate_passed:
        emit_log(
            task_id,
            "warn",
            "Final quality gate failed, attempting auto-fix",
            source="quality",
            project_id=project_id,
        )
        auto_fix_quality(project_path, project_id)

        if has_uncommitted_changes(project_path):
            auto_commit(project_path, f"[auto-fix] Quality gate fixes for {task_id}")

        final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)

    return final_gate_passed


def start_coderabbit_advisory(project_path: str) -> subprocess.Popen | None:
    """Start CodeRabbit as a background subprocess. Returns Popen handle or None."""
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return None
    try:
        return subprocess.Popen(
            [dt_cmd, "coderabbit"],
            cwd=project_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        logger.debug("CodeRabbit start failed: %s", e)
        return None


def _read_coderabbit_details(toon_line: str) -> str | None:
    """Extract details file path from TOON output and read it.

    dt coderabbit outputs: CODERABBIT:FAIL:N|details:<path>|hint:...
    The actual findings are in the details file, not stdout.
    """
    match = re.search(r"details:([^|]+)", toon_line)
    if not match:
        return None
    details_path = Path(match.group(1).strip())
    if details_path.is_file():
        return details_path.read_text(encoding="utf-8", errors="replace")[:8000]
    return None


def _check_coderabbit_skip_conditions(
    output: str,
    returncode: int,
    task_id: str,
    project_id: str,
) -> bool:
    """Emit a skip log and return True if CodeRabbit output should be skipped."""
    if "rate limit" in output.lower() or "429" in output:
        emit_log(task_id, "info", "CodeRabbit advisory skipped: rate limited",
                 source="coderabbit", project_id=project_id)
        return True
    if returncode != 0 and "not found" in output.lower():
        emit_log(task_id, "info", "CodeRabbit advisory skipped: not installed",
                 source="coderabbit", project_id=project_id)
        return True
    # Exit code > 1 = actual error (not just "findings present")
    if returncode > 1:
        emit_log(task_id, "info",
                 f"CodeRabbit advisory errored (exit {returncode}):\n{output[:2000]}",
                 source="coderabbit", project_id=project_id)
        return True
    return False


def _emit_coderabbit_findings(
    output: str,
    returncode: int,
    task_id: str,
    project_id: str,
) -> str | None:
    """Extract findings from CodeRabbit output, emit log, and return them."""
    # Exit code 0 = clean, exit code 1 = findings present
    # dt writes detailed findings to .dev-tools/coderabbit-details.txt
    details = _read_coderabbit_details(output) if returncode == 1 else None
    findings = details or (output[:4000] if output else None)
    if findings:
        emit_log(task_id, "info",
                 f"CodeRabbit advisory ({returncode}, {len(findings)} chars):\n{findings[:2000]}",
                 source="coderabbit", project_id=project_id)
    else:
        emit_log(task_id, "info", "CodeRabbit advisory: clean (no findings)",
                 source="coderabbit", project_id=project_id)
    return findings


def collect_coderabbit_advisory(
    proc: subprocess.Popen | None,
    task_id: str,
    project_id: str,
    timeout: int = 600,
) -> str | None:
    """Collect CodeRabbit results. Returns findings string or None.

    dt coderabbit writes detailed findings to .dev-tools/coderabbit-details.txt
    and outputs a TOON summary line to stdout. We read the details file for the
    full findings to pass to the QA reviewer.

    The timeout is only an extreme safety net (default 10 min).
    """
    if proc is None:
        return None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        output = (stdout + stderr).strip()
        if _check_coderabbit_skip_conditions(output, proc.returncode, task_id, project_id):
            return None
        return _emit_coderabbit_findings(output, proc.returncode, task_id, project_id)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        emit_log(task_id, "info", "CodeRabbit advisory skipped: safety timeout reached",
                 source="coderabbit", project_id=project_id)
        return None
    except Exception as e:
        logger.debug("CodeRabbit collect failed: %s", e)
        return None
