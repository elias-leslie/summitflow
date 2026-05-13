"""Completion gate — hard verification against task done_when with file:line citations.

Replaces the soft intent check. Agents must re-read modified files and confirm
each done_when criterion with specific citations. Confidence < 90 blocks completion.

Public API (re-exported for callers and test patches):
  check_intent, IntentCheckResult, DoneWhenResult,
  _parse_gate_response, _get_modified_files, _read_modified_files,
  _get_diff_summary, _evaluate_completion_gate
"""

from __future__ import annotations

from ....logging_config import get_logger
from ....storage import tasks as task_store
from ....storage.task_spirit import get_task_spirit
from ._intent_git import get_diff_summary as _get_diff_summary
from ._intent_git import get_modified_files as _get_modified_files
from ._intent_git import read_modified_files as _read_modified_files
from ._intent_parser import CONFIDENCE_THRESHOLD as CONFIDENCE_THRESHOLD
from ._intent_parser import DoneWhenResult as DoneWhenResult
from ._intent_parser import IntentCheckResult as IntentCheckResult
from ._intent_parser import parse_gate_response as _parse_gate_response
from ._intent_prompt import build_completion_gate_prompt as _build_completion_gate_prompt

logger = get_logger(__name__)

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

    # If files_to_modify is set, require at least one named file to appear in the diff.
    # Without this, an agent that runs to completion but never edits the target file
    # (e.g. only Read/Bash calls) gets a trivial pass because existing tests still pass.
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
