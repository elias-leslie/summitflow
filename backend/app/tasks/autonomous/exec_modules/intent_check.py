"""Intent verification against task spirit (done_when / objective / spirit_anti)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

from ....logging_config import get_logger
from ....storage.task_spirit import get_task_spirit

logger = get_logger(__name__)


@dataclass
class DoneWhenResult:
    text: str
    status: str  # "pass", "fail", "unclear"
    reason: str


@dataclass
class IntentCheckResult:
    passed: bool
    objective_met: bool
    spirit_violated: bool
    done_when_results: list[DoneWhenResult] = field(default_factory=list)
    summary: str = ""


def check_intent(
    task_id: str,
    project_path: str,
    project_id: str,
) -> IntentCheckResult:
    """Check whether task implementation matches its declared intent.

    Fetches task_spirit, gets git diff summary, and evaluates done_when items
    against the actual changes.

    Returns IntentCheckResult with passed=True if:
    - No spirit data exists (bare tasks skip trivially)
    - No done_when items (intent-only tasks skip)
    - All done_when items pass or are unclear (no fails)
    """
    spirit = get_task_spirit(task_id)
    if not spirit:
        return IntentCheckResult(
            passed=True, objective_met=True, spirit_violated=False,
            summary="No spirit data — skipping intent check",
        )

    done_when = spirit.get("done_when") or []
    objective = spirit.get("objective") or ""
    spirit_anti = spirit.get("spirit_anti") or ""

    if not done_when:
        return IntentCheckResult(
            passed=True, objective_met=True, spirit_violated=False,
            summary="No done_when criteria — skipping intent check",
        )

    diff_summary = _get_diff_summary(project_path)
    return _evaluate_intent(
        task_id, project_id, objective, spirit_anti, done_when, diff_summary,
    )


def _get_diff_summary(project_path: str) -> str:
    """Get a summary of changes on the current branch."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD~5..HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        stat = result.stdout.strip() if result.returncode == 0 else ""

        result2 = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        log = result2.stdout.strip() if result2.returncode == 0 else ""

        return f"Recent commits:\n{log}\n\nDiff stats:\n{stat}"
    except Exception as e:
        logger.warning("Failed to get diff summary", error=str(e))
        return "(diff unavailable)"


def _evaluate_intent(
    task_id: str,
    project_id: str,
    objective: str,
    spirit_anti: str,
    done_when: list[str],
    diff_summary: str,
) -> IntentCheckResult:
    """Evaluate intent using Agent Hub reviewer."""
    prompt = _build_intent_prompt(objective, spirit_anti, done_when, diff_summary)

    try:
        from ....services.agent_hub_client import get_sync_client

        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="reviewer",
            project_id=project_id,
        )
        return _parse_intent_response(response.content, done_when, objective, spirit_anti)
    except Exception as e:
        logger.warning("Intent check failed, defaulting to pass", task_id=task_id, error=str(e))
        return IntentCheckResult(
            passed=True, objective_met=True, spirit_violated=False,
            summary=f"Intent check unavailable: {e}",
        )


def _build_intent_prompt(
    objective: str,
    spirit_anti: str,
    done_when: list[str],
    diff_summary: str,
) -> str:
    """Build the prompt for intent verification."""
    done_items = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(done_when))
    spirit_section = f"\nSPIRIT_ANTI (must NOT happen): {spirit_anti}" if spirit_anti else ""

    return f"""You are verifying whether a task implementation matches its declared intent.

OBJECTIVE: {objective}
{spirit_section}

DONE_WHEN criteria:
{done_items}

CHANGES MADE:
{diff_summary}

For each DONE_WHEN item, respond with PASS, FAIL, or UNCLEAR and a brief reason.
Then give an overall verdict.

Format your response exactly as:
DONE_WHEN_1: PASS|FAIL|UNCLEAR - reason
DONE_WHEN_2: PASS|FAIL|UNCLEAR - reason
...
OBJECTIVE_MET: YES|NO
SPIRIT_VIOLATED: YES|NO
SUMMARY: one-line summary
"""


def _parse_intent_response(
    content: str,
    done_when: list[str],
    objective: str,
    spirit_anti: str,
) -> IntentCheckResult:
    """Parse structured response from reviewer."""
    lines = content.strip().split("\n")
    done_when_results: list[DoneWhenResult] = []
    objective_met = True
    spirit_violated = False
    summary = ""
    has_fail = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("DONE_WHEN_"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                status_reason = parts[1].strip()
                idx = int(parts[0].replace("DONE_WHEN_", "")) - 1
                if 0 <= idx < len(done_when):
                    if status_reason.startswith("PASS"):
                        status = "pass"
                        reason = status_reason[4:].strip().lstrip("- ")
                    elif status_reason.startswith("FAIL"):
                        status = "fail"
                        reason = status_reason[4:].strip().lstrip("- ")
                        has_fail = True
                    else:
                        status = "unclear"
                        reason = status_reason.replace("UNCLEAR", "").strip().lstrip("- ")
                    done_when_results.append(DoneWhenResult(
                        text=done_when[idx], status=status, reason=reason,
                    ))
        elif line.startswith("OBJECTIVE_MET:"):
            objective_met = "NO" not in line.upper().split(":", 1)[1]
        elif line.startswith("SPIRIT_VIOLATED:"):
            spirit_violated = "YES" in line.upper().split(":", 1)[1]
        elif line.startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()

    passed = not has_fail and not spirit_violated
    return IntentCheckResult(
        passed=passed,
        objective_met=objective_met,
        spirit_violated=spirit_violated,
        done_when_results=done_when_results,
        summary=summary,
    )
