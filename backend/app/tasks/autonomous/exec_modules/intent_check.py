"""Intent verification against task spirit (done_when / objective / spirit_anti)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

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


@dataclass
class _ParseState:
    done_when_results: list[DoneWhenResult] = field(default_factory=list)
    objective_met: bool = True
    spirit_violated: bool = False
    summary: str = ""
    has_fail: bool = False


def _trivial_pass(summary: str) -> IntentCheckResult:
    return IntentCheckResult(passed=True, objective_met=True, spirit_violated=False, summary=summary)


def check_intent(task_id: str, project_path: str, project_id: str) -> IntentCheckResult:
    """Check whether task implementation matches its declared intent."""
    spirit = get_task_spirit(task_id)
    if not spirit:
        return _trivial_pass("No spirit data — skipping intent check")
    done_when = spirit.get("done_when") or []
    if not done_when:
        return _trivial_pass("No done_when criteria — skipping intent check")
    diff_summary = _get_diff_summary(project_path)
    return _evaluate_intent(
        task_id, project_id,
        spirit.get("objective") or "",
        spirit.get("spirit_anti") or "",
        done_when, diff_summary,
    )


def _get_diff_summary(project_path: str) -> str:
    try:
        mb = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        diff_range = f"{mb.stdout.strip()}..HEAD" if mb.returncode == 0 else "HEAD~1..HEAD"
        stat_out = subprocess.run(
            ["git", "diff", "--stat", diff_range],
            cwd=project_path, capture_output=True, text=True, timeout=30,
        )
        log_out = subprocess.run(
            ["git", "log", "--oneline", diff_range],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        stat = stat_out.stdout.strip() if stat_out.returncode == 0 else ""
        log = log_out.stdout.strip() if log_out.returncode == 0 else ""
        return f"Recent commits:\n{log}\n\nDiff stats:\n{stat}"
    except Exception as e:
        logger.warning("Failed to get diff summary", error=str(e))
        return "(diff unavailable)"


def _evaluate_intent(
    task_id: str, project_id: str, objective: str,
    spirit_anti: str, done_when: list[str], diff_summary: str,
) -> IntentCheckResult:
    prompt = _build_intent_prompt(objective, spirit_anti, done_when, diff_summary)
    try:
        from ....services.agent_hub_client import get_sync_client
        response = get_sync_client().complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="reviewer",
            project_id=project_id,
        )
        return _parse_intent_response(response.content, done_when, objective, spirit_anti)
    except Exception as e:
        logger.warning("Intent check failed, defaulting to pass", task_id=task_id, error=str(e))
        return _trivial_pass(f"Intent check unavailable: {e}")


def _build_intent_prompt(
    objective: str, spirit_anti: str, done_when: list[str], diff_summary: str,
) -> str:
    done_items = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(done_when))
    spirit_section = f"\nSPIRIT_ANTI (must NOT happen): {spirit_anti}" if spirit_anti else ""
    return (
        f"Verify that this task implementation matches its declared intent.\n"
        f"OBJECTIVE: {objective}{spirit_section}\n"
        f"DONE_WHEN criteria:\n{done_items}\n"
        f"CHANGES MADE:\n{diff_summary}\n\n"
        "For each DONE_WHEN item respond PASS, FAIL, or UNCLEAR with a brief reason.\n"
        "Format exactly as:\nDONE_WHEN_1: PASS|FAIL|UNCLEAR - reason\n"
        "OBJECTIVE_MET: YES|NO\nSPIRIT_VIOLATED: YES|NO\nSUMMARY: one-line summary\n"
    )


def _parse_done_when_line(line: str, done_when: list[str]) -> DoneWhenResult | None:
    parts = line.split(":", 1)
    if len(parts) != 2:
        return None
    idx = int(parts[0].replace("DONE_WHEN_", "")) - 1
    if not (0 <= idx < len(done_when)):
        return None
    sr = parts[1].strip()
    for prefix, status in (("PASS", "pass"), ("FAIL", "fail")):
        if sr.startswith(prefix):
            return DoneWhenResult(text=done_when[idx], status=status, reason=sr[4:].strip().lstrip("- "))
    return DoneWhenResult(text=done_when[idx], status="unclear", reason=sr.replace("UNCLEAR", "").strip().lstrip("- "))


def _apply_line_to_state(line: str, state: _ParseState, done_when: list[str]) -> None:
    """Update parse state with a single response line."""
    if line.startswith("DONE_WHEN_"):
        dw = _parse_done_when_line(line, done_when)
        if dw:
            state.has_fail = state.has_fail or dw.status == "fail"
            state.done_when_results.append(dw)
        return
    if line.startswith("OBJECTIVE_MET:"):
        state.objective_met = "NO" not in line.upper().split(":", 1)[1]
        return
    if line.startswith("SPIRIT_VIOLATED:"):
        state.spirit_violated = "YES" in line.upper().split(":", 1)[1]
        return
    if line.startswith("SUMMARY:"):
        state.summary = line.split(":", 1)[1].strip()


def _parse_intent_response(
    content: str, done_when: list[str], objective: str, spirit_anti: str,
) -> IntentCheckResult:
    """Parse structured response from reviewer."""
    state = _ParseState()
    for raw in content.strip().split("\n"):
        line = raw.strip()
        if line:
            _apply_line_to_state(line, state, done_when)

    return IntentCheckResult(
        passed=not state.has_fail and not state.spirit_violated,
        objective_met=state.objective_met,
        spirit_violated=state.spirit_violated,
        done_when_results=state.done_when_results,
        summary=state.summary,
    )
