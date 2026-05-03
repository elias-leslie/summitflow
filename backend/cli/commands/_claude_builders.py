"""Pure builder functions for Claude worker command construction."""

from __future__ import annotations

from pathlib import Path

from ._claude_constants import (
    _ORCHESTRATOR_ALLOWED_TOOLS,
    _ORCHESTRATOR_SOURCE,
    _WORKER_SUBAGENT_NAME,
    OrchestratorTask,
)


def build_worker_command(
    *,
    python_bin: Path,
    script_path: Path,
    task_id: str,
    project_id: str,
    project_root: Path,
    model: str,
    timeout_seconds: int,
    source: str,
    claim_if_needed: bool,
    feedback_text: str | None,
    effort: str | None,
    append_system_prompt: str | None,
    skills: list[str] | None,
) -> list[str]:
    """Build the canonical Claude worker wrapper command."""
    command = [
        str(python_bin), str(script_path),
        "--project-id", project_id,
        "--task-id", task_id,
        "--task-root", str(project_root),
        "--model", model,
        "--timeout-seconds", str(timeout_seconds),
        "--source", source,
    ]
    if claim_if_needed:
        command.append("--claim-if-needed")
    if feedback_text:
        command.extend(["--feedback-text", feedback_text])
    if effort:
        command.extend(["--effort", effort])
    if append_system_prompt:
        command.extend(["--append-system-prompt", append_system_prompt])
    for skill in skills or []:
        command.extend(["--skill", skill])
    return command


def build_prompt_worker_command(
    *,
    python_bin: Path,
    script_path: Path,
    prompt_file: Path,
    agents_file: Path | None,
    batch_task_ids: list[str] | None,
    project_id: str,
    project_root: Path,
    model: str,
    timeout_seconds: int,
    effort: str | None,
    append_system_prompt: str | None,
    skills: list[str] | None,
) -> list[str]:
    """Build the orchestrator prompt-based worker command."""
    command = [
        str(python_bin), str(script_path),
        "--prompt-file", str(prompt_file),
        "--project-id", project_id,
        "--workdir", str(project_root),
        "--model", model,
        "--allowed-tools", _ORCHESTRATOR_ALLOWED_TOOLS,
        "--timeout-seconds", str(timeout_seconds),
        "--source", _ORCHESTRATOR_SOURCE,
    ]
    if effort:
        command.extend(["--effort", effort])
    if append_system_prompt:
        command.extend(["--append-system-prompt", append_system_prompt])
    for task_id in batch_task_ids or []:
        command.extend(["--batch-task-id", task_id])
    for skill in skills or []:
        command.extend(["--skill", skill])
    if agents_file is not None:
        command.extend(["--agents-file", str(agents_file)])
    return command


def build_orchestrator_prompt(
    *, project_id: str, project_root: Path, max_subagents: int, tasks: list[OrchestratorTask],
) -> str:
    """Build a single Claude orchestrator prompt for same-project tasks."""
    task_blocks = "".join(
        f"\n\n=== Task {t.task_id} ===\n"
        f"Project root: `{t.project_root}`\n"
        f"Task branch: `{t.task_branch or f'{t.task_id}/main'}`\n"
        "Canonical task context:\n"
        "```text\n"
        f"{t.context_text}\n"
        "```"
        for t in tasks
    )
    return (
        f"You are the main Claude orchestrator for project `{project_id}`.\n\nGoal:\n"
        f"- Complete the assigned task set from project root `{project_root}`.\n"
        f"- Launch up to {max_subagents} Agent subagents using the named subagent"
        f" `{_WORKER_SUBAGENT_NAME}`.\n"
        "- This repo now uses one shared checkout. Serialize task execution and branch changes.\n"
        "- You own task coordination, review, and closeout."
        " Subagents are implementation workers, not the final authority.\n\n"
        "Main orchestrator responsibilities:\n"
        "1. Keep work serialized through the shared project checkout.\n"
        "2. Dispatch at most one task-worker subagent at a time.\n"
        "3. Ensure each subagent stays inside the assigned project checkout.\n"
        "4. Review each subagent result yourself: changed files, verification output,"
        " and whether the task spirit was actually met.\n"
        "5. Require each subagent to run task-appropriate verification plus"
        " `st check --quick --changed-only` before claiming success.\n"
        "6. If a subagent is blocked, give it the missing tool, permission, or context and redrive once.\n"
        f"7. Run `st done <task-id> -m \"...\"` yourself from `{project_root}`, serially, after review is satisfied.\n\n"
        "Hard constraints:\n"
        "- Do not overlap task execution in the shared checkout.\n"
        "- Do not treat subagent output as final without review.\n"
        "- Do not edit task files directly when a subagent can do the work,"
        " unless you are explicitly fixing a failed pass.\n"
        "- No partial completions, placeholders, or unrelated cleanup.\n"
        f"- Stay within this project only.\n\nTask set:{task_blocks}\n\n"
        "Final response must include:\n"
        "- task ids completed\n"
        "- files changed per task\n"
        "- verification commands run per task\n"
        "- whether `st done` succeeded for each task"
    )
