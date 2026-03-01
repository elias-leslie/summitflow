"""Quality gate execution and auto-fix logic."""

from __future__ import annotations

import subprocess

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


def collect_coderabbit_advisory(
    proc: subprocess.Popen | None,
    task_id: str,
    project_id: str,
    timeout: int = 600,
) -> str | None:
    """Collect CodeRabbit results. Returns findings string or None.

    Lets CodeRabbit run to natural completion or error — the timeout is only
    an extreme safety net (default 10 min) to prevent infinite hangs.
    """
    if proc is None:
        return None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        output = (stdout + stderr).strip()

        if "rate limit" in output.lower() or "429" in output:
            emit_log(
                task_id,
                "info",
                "CodeRabbit advisory skipped: rate limited",
                source="coderabbit",
                project_id=project_id,
            )
            return None

        if proc.returncode != 0 and "not found" in output.lower():
            emit_log(
                task_id,
                "info",
                "CodeRabbit advisory skipped: not installed",
                source="coderabbit",
                project_id=project_id,
            )
            return None

        if proc.returncode != 0:
            emit_log(
                task_id,
                "info",
                f"CodeRabbit advisory errored (exit {proc.returncode}):\n{output[:2000]}",
                source="coderabbit",
                project_id=project_id,
            )
            return None

        findings = output[:4000] if output else None
        if findings:
            emit_log(
                task_id,
                "info",
                f"CodeRabbit advisory review:\n{findings}",
                source="coderabbit",
                project_id=project_id,
            )
        return findings
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        emit_log(
            task_id,
            "info",
            "CodeRabbit advisory skipped: safety timeout reached",
            source="coderabbit",
            project_id=project_id,
        )
        return None
    except Exception as e:
        logger.debug("CodeRabbit collect failed: %s", e)
        return None
