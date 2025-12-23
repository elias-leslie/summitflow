"""QA validation loop for TDD builds.

Implements a 5-iteration QA loop with recurring issue detection
and escalation for unfixable problems.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from ...storage import agent_sessions as sessions_storage
from ..recovery import (
    FailureType,
    RecoveryManager,
    RecoveryStrategy,
    classify_failure,
    is_circular_fix,
)

logger = logging.getLogger(__name__)

# QA Loop Configuration
QA_MAX_ITERATIONS = 5
QA_RECURRING_THRESHOLD = 3  # Same issue 3+ times = escalate


class QAResult(Enum):
    """Result of a QA validation loop."""

    PASSED = "passed"  # All tests pass
    FAILED = "failed"  # Max iterations exceeded
    ESCALATE = "escalate"  # Circular/recurring issues detected


def _create_error_signature(
    failure_type: FailureType,
    error_text: str,
) -> str:
    """Create a signature hash for an error.

    Used to track recurring issues.

    Args:
        failure_type: Type of failure
        error_text: Error message/output

    Returns:
        MD5 hash signature.
    """
    # Extract key lines from error (first 3 non-empty lines)
    lines = [l.strip() for l in error_text.split("\n") if l.strip()][:3]
    key_content = failure_type.value + "|" + "|".join(lines)
    return hashlib.md5(key_content.encode()).hexdigest()[:12]


async def qa_loop(
    project_id: str,
    capability_id: str,
    session_id: str,
    recovery_manager: RecoveryManager,
    run_tests: Any,  # Callable that returns test results
    call_agent: Any,  # Callable for agent fix
) -> QAResult:
    """Run QA validation loop for a capability.

    Attempts up to QA_MAX_ITERATIONS to get tests passing.
    Escalates on circular fixes or recurring issues.

    Args:
        project_id: Project ID
        capability_id: Capability to validate
        session_id: Build session ID
        recovery_manager: RecoveryManager instance
        run_tests: Async callable that runs tests and returns results dict
        call_agent: Async callable that calls agent for fixes

    Returns:
        QAResult enum value.
    """
    # Track issue signatures for recurring detection
    issue_counts: dict[str, int] = {}
    previous_errors: list[str] = []

    for iteration in range(1, QA_MAX_ITERATIONS + 1):
        logger.info(
            f"QA iteration {iteration}/{QA_MAX_ITERATIONS} for {capability_id}"
        )

        # Run tests
        test_results = await run_tests()

        if test_results.get("all_passed"):
            logger.info(f"QA passed for {capability_id} on iteration {iteration}")
            return QAResult.PASSED

        # Tests failed - extract failure info
        failed_tests = test_results.get("results", [])
        error_text = "\n".join(
            t.get("error", "") + t.get("output", "")
            for t in failed_tests
            if not t.get("passed")
        )

        # Classify failure
        failure_type = classify_failure(error_text=error_text)

        # Create error signature
        signature = _create_error_signature(failure_type, error_text)
        issue_counts[signature] = issue_counts.get(signature, 0) + 1

        logger.info(
            f"QA iteration {iteration}: {failure_type.value}, "
            f"signature={signature}, count={issue_counts[signature]}"
        )

        # Check for circular fix
        if previous_errors and is_circular_fix(error_text, previous_errors):
            logger.warning(
                f"Circular fix detected for {capability_id} - escalating"
            )
            return QAResult.ESCALATE

        # Check for recurring issue
        if issue_counts[signature] >= QA_RECURRING_THRESHOLD:
            logger.warning(
                f"Recurring issue ({issue_counts[signature]}x) for {capability_id} - escalating"
            )
            return QAResult.ESCALATE

        # Record this error for circular detection
        previous_errors.append(error_text)

        # Get recovery strategy
        strategy = recovery_manager.get_recovery_strategy(failure_type, error_text)

        if strategy == RecoveryStrategy.ESCALATE:
            logger.warning(f"Recovery strategy is ESCALATE for {capability_id}")
            return QAResult.ESCALATE

        # Call agent for fix
        agent_result = await call_agent(
            failure_type=failure_type,
            error_text=error_text,
        )

        if not agent_result.get("success"):
            logger.error(
                f"Agent fix failed on QA iteration {iteration}: "
                f"{agent_result.get('error', 'unknown')}"
            )
            continue

        logger.info(
            f"Agent fix applied on QA iteration {iteration}, re-running tests..."
        )

    # Max iterations exceeded
    logger.warning(
        f"QA max iterations ({QA_MAX_ITERATIONS}) exceeded for {capability_id}"
    )
    return QAResult.FAILED


def escalate_build(
    project_id: str,
    session_id: str,
    capability_id: str,
    reason: str,
    error_summary: str,
) -> dict[str, Any]:
    """Create an escalation for a build failure.

    Args:
        project_id: Project ID
        session_id: Build session ID
        capability_id: Capability that failed
        reason: Reason for escalation
        error_summary: Summary of the error

    Returns:
        Escalation record dict.
    """
    escalation = {
        "project_id": project_id,
        "session_id": session_id,
        "capability_id": capability_id,
        "reason": reason,
        "error_summary": error_summary[:500],  # Truncate
        "escalated_at": datetime.now(UTC).isoformat(),
    }

    # Store in build_state
    sessions_storage.merge_build_state(
        project_id,
        session_id,
        {
            "escalated": True,
            "escalation_reason": reason,
            "escalation_time": escalation["escalated_at"],
            "escalation_capability": capability_id,
        },
    )

    logger.warning(
        f"Build escalated for {capability_id}: {reason}"
    )

    return escalation


def get_escalations(project_id: str, session_id: str) -> list[dict[str, Any]]:
    """Get escalations for a build session.

    Args:
        project_id: Project ID
        session_id: Build session ID

    Returns:
        List of escalation dicts.
    """
    build_state = sessions_storage.get_build_state(project_id, session_id)

    if not build_state.get("escalated"):
        return []

    return [
        {
            "capability_id": build_state.get("escalation_capability"),
            "reason": build_state.get("escalation_reason"),
            "escalated_at": build_state.get("escalation_time"),
        }
    ]
