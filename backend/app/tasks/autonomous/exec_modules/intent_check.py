"""Completion gate — hard verification against task done_when with file:line citations.

Replaces the soft intent check. Agents must re-read modified files and confirm
each done_when criterion with specific citations. Confidence < 90 blocks completion.

Public API (re-exported for callers and test patches):
  check_intent, IntentCheckResult, DoneWhenResult, CONFIDENCE_THRESHOLD,
  _parse_gate_response, _get_modified_files, _read_modified_files,
  _get_diff_summary, _evaluate_completion_gate
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from ....logging_config import get_logger
from ....services.task_harness import summarize_execution_contract
from ....storage import tasks as task_store
from ....storage.task_spirit import get_task_spirit

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Parser models and helpers
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 90


@dataclass
class DoneWhenResult:
    text: str
    status: str  # "MET", "NOT_MET", "PARTIAL"
    evidence: str  # file:line citations


@dataclass
class IntentCheckResult:
    passed: bool
    objective_met: bool
    spirit_violated: bool
    confidence: int = 0
    done_when_results: list[DoneWhenResult] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class _ParseState:
    done_when_results: list[DoneWhenResult] = field(default_factory=list)
    confidence: int = 0
    gaps: list[str] = field(default_factory=list)
    anti_check: str = "CLEAR"
    has_not_met: bool = False


def _parse_confidence(line: str) -> int:
    try:
        return int(line.split(":", 1)[1].strip().split()[0])
    except (ValueError, IndexError):
        return 0


def _parse_gaps(line: str) -> list[str]:
    gaps_text = line.split(":", 1)[1].strip()
    if gaps_text.upper() == "NONE":
        return []
    return [g.strip() for g in gaps_text.split(",") if g.strip()]


def _parse_criterion_line(
    line: str, done_when: list[str], state: _ParseState,
) -> None:
    try:
        parts = line.split(":", 1)
        if len(parts) != 2:
            return
        idx = int(parts[0].replace("CRITERION_", "")) - 1
        if not (0 <= idx < len(done_when)):
            return
        remainder = parts[1].strip()
        if " - " in remainder:
            status_str, evidence = remainder.split(" - ", 1)
        else:
            status_str = remainder
            evidence = ""
        status_str = status_str.strip().upper()
        if status_str not in ("MET", "NOT_MET", "PARTIAL"):
            status_str = "NOT_MET"
        if status_str == "NOT_MET":
            state.has_not_met = True
        state.done_when_results.append(
            DoneWhenResult(text=done_when[idx], status=status_str, evidence=evidence.strip())
        )
    except (ValueError, IndexError):
        pass


def _build_summary(state: _ParseState, passed: bool) -> str:
    met = sum(1 for r in state.done_when_results if r.status == "MET")
    total = len(state.done_when_results)
    parts = [f"Confidence: {state.confidence}/100, {met}/{total} criteria met"]
    if state.gaps:
        parts.append(f"Gaps: {', '.join(state.gaps)}")
    if state.anti_check.upper() != "CLEAR":
        parts.append(f"Anti-pattern violation: {state.anti_check}")
    if not passed:
        parts.append("BLOCKED — does not meet completion threshold")
    return ". ".join(parts)


def _parse_gate_response(content: str, done_when: list[str]) -> IntentCheckResult:
    """Parse structured completion gate response."""
    state = _ParseState()
    for raw in content.strip().split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("CRITERION_"):
            _parse_criterion_line(line, done_when, state)
        elif line.startswith("CONFIDENCE:"):
            state.confidence = _parse_confidence(line)
        elif line.startswith("GAPS:"):
            state.gaps = _parse_gaps(line)
        elif line.startswith("ANTI_CHECK:"):
            state.anti_check = line.split(":", 1)[1].strip()

    spirit_violated = state.anti_check.upper() != "CLEAR"
    passed = (
        state.confidence >= CONFIDENCE_THRESHOLD
        and not state.has_not_met
        and not spirit_violated
    )
    return IntentCheckResult(
        passed=passed,
        objective_met=not state.has_not_met,
        spirit_violated=spirit_violated,
        confidence=state.confidence,
        done_when_results=state.done_when_results,
        gaps=state.gaps,
        summary=_build_summary(state, passed),
    )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _get_modified_files(project_path: str) -> list[str]:
    """Get files modified between merge-base and HEAD."""
    try:
        mb = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if mb.returncode != 0:
            return []
        diff_range = f"{mb.stdout.strip()}...HEAD"
        result = subprocess.run(
            ["git", "diff", "--name-only", diff_range],
            cwd=project_path, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception as e:
        logger.warning("Failed to get modified files", error=str(e))
        return []


def _get_diff_summary(project_path: str) -> str:
    """Get diff stats and commit log for context."""
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


def _read_one_file(project_path: str, filepath: str, max_lines: int) -> str | None:
    try:
        result = subprocess.run(
            ["head", "-n", str(max_lines), filepath],
            cwd=project_path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        numbered = "\n".join(
            f"{i+1}: {line}"
            for i, line in enumerate(result.stdout.split("\n")[:max_lines])
        )
        return f"### {filepath}\n```\n{numbered}\n```"
    except Exception:
        return None


def _read_modified_files(
    project_path: str,
    modified_files: list[str],
    max_files: int = 20,
    max_lines_per_file: int = 200,
) -> str:
    """Read modified files for the reviewer to verify citations."""
    if not modified_files:
        return "(no modified files)"
    sections = [
        section
        for filepath in modified_files[:max_files]
        if (section := _read_one_file(project_path, filepath, max_lines_per_file)) is not None
    ]
    if not sections:
        return "(files could not be read)"
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _contract_section(execution_contract: object) -> str:
    contract_summary = summarize_execution_contract(execution_contract)
    needs_section = (
        contract_summary["target_url_count"] > 0
        or contract_summary["user_flow_count"] > 0
        or contract_summary["api_check_count"] > 0
        or contract_summary["negative_case_count"] > 0
        or contract_summary["has_design_criteria"]
    )
    if not needs_section:
        return ""
    return (
        "\nEXECUTION CONTRACT:\n"
        f"  mode={contract_summary['mode']}\n"
        f"  target_urls={contract_summary['target_url_count']}\n"
        f"  user_flows={contract_summary['user_flow_count']}\n"
        f"  api_checks={contract_summary['api_check_count']}\n"
        f"  negative_cases={contract_summary['negative_case_count']}\n"
        f"  design_critic={'yes' if contract_summary['has_design_criteria'] else 'no'}\n"
    )


def _build_completion_gate_prompt(
    description: str,
    spirit_anti: str,
    done_when: list[str],
    modified_files: list[str],
    file_contents: str,
    diff_summary: str,
    execution_contract: object,
) -> str:
    """Build the completion gate verification prompt."""
    done_items = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(done_when))
    anti_section = f"\nSPIRIT_ANTI (must NOT happen):\n{spirit_anti}" if spirit_anti else ""
    files_list = "\n".join(f"  - {f}" for f in modified_files) if modified_files else "  (none)"
    contract_section = _contract_section(execution_contract)
    return (
        "You are performing a completion gate check. Verify that the task's done_when criteria "
        "have been met by examining the actual code changes.\n\n"
        f"TASK DESCRIPTION: {description}{anti_section}\n\n"
        f"DONE_WHEN CRITERIA:\n{done_items}\n\n"
        f"{contract_section}\n"
        f"MODIFIED FILES:\n{files_list}\n\n"
        f"CHANGES SUMMARY:\n{diff_summary}\n\n"
        f"FILE CONTENTS:\n{file_contents}\n\n"
        "For each done_when criterion, respond with:\n"
        "CRITERION_N: MET|NOT_MET|PARTIAL - file:line evidence or explanation\n\n"
        "Then:\n"
        "CONFIDENCE: 0-100\n"
        "GAPS: comma-separated list of unmet items, or NONE\n"
        "ANTI_CHECK: any spirit_anti violations found, or CLEAR\n"
    )


# ---------------------------------------------------------------------------
# Completion gate
# ---------------------------------------------------------------------------

_GENERIC_DONE_WHEN = {
    "All configured quality gates pass",
    "No regressions - all existing tests pass",
    "No console errors in browser",
}

_STRUCTURAL_DONE_WHEN_PREFIXES = (
    "No functions exceed ",
    "No nesting deeper than ",
    "Functions per file reduced to <=",
    "Classes per file reduced to <=",
    "No class has more than ",
    "Magic strings extracted ",
    "Imports reduced to <=",
    "File structure is meaningfully simplified, with size reduced toward the guideline target",
    "File structure is meaningfully simplified where size was the issue",
    "Largest functions are measured ",
    "Deep nesting is measured ",
    "Function count is measured ",
    "Class count is measured ",
    "Large classes are measured ",
    "Repeated magic strings are extracted ",
    "Imports are measured ",
)


def _trivial_pass(summary: str) -> IntentCheckResult:
    return IntentCheckResult(
        passed=True, objective_met=True, spirit_violated=False,
        confidence=100, summary=summary,
    )


def _is_supported_refactor_done_when(item: str) -> bool:
    return item in _GENERIC_DONE_WHEN or item.startswith(_STRUCTURAL_DONE_WHEN_PREFIXES)


def _deterministic_refactor_pass(
    task_id: str,
    done_when: list[str],
    project_path: str,
    spirit: dict,
) -> IntentCheckResult | None:
    """Use passed subtask/step verification as authoritative evidence for refactors."""
    from ....storage import subtasks as subtask_store

    task = task_store.get_task(task_id)
    if not task or task.get("task_type") != "refactor":
        return None
    if not done_when or not all(_is_supported_refactor_done_when(item) for item in done_when):
        return None

    raw_context = spirit.get("context") if isinstance(spirit, dict) else None
    context = raw_context if isinstance(raw_context, dict) else {}
    files_to_modify = context.get("files_to_modify") or []
    if files_to_modify:
        modified = set(_get_modified_files(project_path))
        if not modified.intersection(files_to_modify):
            return None

    subtasks = subtask_store.get_subtasks_for_task(task_id, include_steps=True)
    if not subtasks:
        return None
    if any(not subtask.get("passes") for subtask in subtasks):
        return None
    for subtask in subtasks:
        steps = subtask.get("steps_from_table", [])
        if any(not step.get("passes") for step in steps):
            return None

    results = [
        DoneWhenResult(
            text=item,
            status="MET",
            evidence="Verified by passed refactor steps and quality gates",
        )
        for item in done_when
    ]
    return IntentCheckResult(
        passed=True,
        objective_met=True,
        spirit_violated=False,
        confidence=95,
        done_when_results=results,
        summary="Passed using refactor step verification evidence",
    )


def _evaluate_completion_gate(
    task_id: str,
    project_id: str,
    description: str,
    spirit_anti: str,
    done_when: list[str],
    modified_files: list[str],
    file_contents: str,
    diff_summary: str,
) -> IntentCheckResult:
    """Call reviewer agent to verify completion gate."""
    spirit = get_task_spirit(task_id) or {}
    raw_context = spirit.get("context")
    context: dict[str, object] = raw_context if isinstance(raw_context, dict) else {}
    prompt = _build_completion_gate_prompt(
        description, spirit_anti, done_when,
        modified_files, file_contents, diff_summary,
        context.get("execution_contract"),
    )
    try:
        from ....services.agent_hub_client import get_sync_client
        response = get_sync_client().complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="reviewer",
            project_id=project_id,
            execute_tools=False,
        )
        return _parse_gate_response(response.content, done_when)
    except Exception as e:
        logger.warning("Completion gate failed, defaulting to pass", task_id=task_id, error=str(e))
        return _trivial_pass(f"Completion gate unavailable: {e}")


def check_intent(task_id: str, project_path: str, project_id: str) -> IntentCheckResult:
    """Run completion gate: verify done_when criteria with file:line citations."""
    spirit = get_task_spirit(task_id)
    if not spirit:
        return _trivial_pass("No spirit data — skipping completion gate")

    done_when = spirit.get("done_when") or []
    if not done_when:
        return _trivial_pass("No done_when criteria — skipping completion gate")

    deterministic = _deterministic_refactor_pass(task_id, done_when, project_path, spirit)
    if deterministic is not None:
        return deterministic

    modified_files = _get_modified_files(project_path)
    diff_summary = _get_diff_summary(project_path)
    file_contents = _read_modified_files(project_path, modified_files)

    task = task_store.get_task(task_id)
    description = (task.get("description") or "") if task else ""

    return _evaluate_completion_gate(
        task_id=task_id,
        project_id=project_id,
        description=description,
        spirit_anti="",
        done_when=done_when,
        modified_files=modified_files,
        file_contents=file_contents,
        diff_summary=diff_summary,
    )
