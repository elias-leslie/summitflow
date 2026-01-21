"""Verification command runner for test-type acceptance criteria.

Runs verify_command for criteria with verify_by='test' and returns
failure information if any commands fail.
"""

from __future__ import annotations

import subprocess
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)


def run_verification_commands(
    criteria: list[dict[str, Any]],
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Run verification commands for test-type criteria.

    Args:
        criteria: List of criterion dicts with verify_command field
        timeout: Command timeout in seconds (default 30)

    Returns:
        List of failed verification results. Empty list means all passed.
        Each failure dict contains:
        - criterion_id: Criterion identifier
        - criterion: Criterion text
        - verify_command: The command that was run
        - exit_code: Command exit code
        - output: Combined stdout/stderr (truncated to 2000 chars)
        - expected_output: What was expected (if any)
    """
    failures: list[dict[str, Any]] = []

    for crit in criteria:
        criterion_id = crit.get("criterion_id", "unknown")
        verify_command = crit.get("verify_command")
        expected_output = crit.get("expected_output")

        if not verify_command:
            # Skip criteria without verification commands
            continue

        logger.info(f"Running verification for {criterion_id}: {verify_command[:100]}...")

        try:
            result = subprocess.run(
                verify_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Check exit code
            if result.returncode != 0:
                output = _truncate_output(result.stdout + result.stderr)
                failures.append({
                    "criterion_id": criterion_id,
                    "criterion": crit.get("criterion", ""),
                    "verify_command": verify_command,
                    "exit_code": result.returncode,
                    "output": output,
                    "expected_output": expected_output,
                })
                logger.warning(
                    f"Verification failed for {criterion_id}: exit_code={result.returncode}"
                )
                continue

            # Check expected output if specified
            if expected_output:
                combined_output = result.stdout + result.stderr
                if expected_output not in combined_output:
                    failures.append({
                        "criterion_id": criterion_id,
                        "criterion": crit.get("criterion", ""),
                        "verify_command": verify_command,
                        "exit_code": 0,
                        "output": _truncate_output(combined_output),
                        "expected_output": expected_output,
                        "mismatch": True,
                    })
                    logger.warning(
                        f"Verification failed for {criterion_id}: "
                        f"expected '{expected_output}' not found in output"
                    )
                    continue

            logger.info(f"Verification passed for {criterion_id}")

        except subprocess.TimeoutExpired:
            failures.append({
                "criterion_id": criterion_id,
                "criterion": crit.get("criterion", ""),
                "verify_command": verify_command,
                "exit_code": -1,
                "output": f"Command timed out after {timeout}s",
                "expected_output": expected_output,
                "timeout": True,
            })
            logger.warning(f"Verification timed out for {criterion_id}")

        except Exception as e:
            failures.append({
                "criterion_id": criterion_id,
                "criterion": crit.get("criterion", ""),
                "verify_command": verify_command,
                "exit_code": -1,
                "output": f"Error running command: {e}",
                "expected_output": expected_output,
                "error": True,
            })
            logger.exception(f"Error running verification for {criterion_id}")

    return failures


def _truncate_output(output: str, max_length: int = 2000) -> str:
    """Truncate output to max_length, preserving end."""
    if len(output) <= max_length:
        return output
    return "...(truncated)...\n" + output[-max_length:]
