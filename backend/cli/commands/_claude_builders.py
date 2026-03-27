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
    for task_id in batch_task_ids or []:
        command.extend(["--batch-task-id", task_id])
    if agents_file is not None:
        command.extend(["--agents-file", str(agents_file)])
    return command


def build_orchestrator_prompt(
    *, project_id: str, project_root: Path, max_subagents: int, tasks: list[OrchestratorTask],
) -> str:
    """Build a single Claude orchestrator prompt for multiple same-project tasks."""
    task_blocks = "".join(
        f"\n\n=== Task {t.task_id} ===\n"
        f"Worktree: `{t.worktree_path}`\n"
        "Canonical task context:\n"
        "```text\n"
        f"{t.context_text}\n"
        "```"
        for t in tasks
    )
    return (
        f"You are the main Claude orchestrator for project `{project_id}`.\n\nGoal:\n"
        f"- Complete the assigned task set from project root `{project_root}`.\n"
        f"- Launch up to {max_subagents} Agent subagents in parallel using the named subagent"
        f" `{_WORKER_SUBAGENT_NAME}`.\n"
        "- Use one subagent per task lane when tasks are safely parallelizable;"
        " serialize if they converge on shared files or shared plumbing.\n"
        "- You own task coordination, review, git, cleanup, and closeout."
        " Subagents are implementation workers, not the final authority.\n\n"
        "Main orchestrator responsibilities:\n"
        "1. Confirm each listed task stays mapped to exactly one worktree and one subagent.\n"
        "2. Dispatch the task-worker subagents across the listed tasks, up to the concurrency limit.\n"
        "3. Ensure each subagent works only inside its assigned worktree.\n"
        "4. Review each subagent result yourself: changed files, verification output,"
        " and whether the task spirit was actually met.\n"
        "5. Require each subagent to run task-appropriate verification plus"
        " `dt --quick --changed-only` before claiming success.\n"
        "6. If a subagent misses task spirit, drifts scope, or fails verification,"
        " redrive or fix it within this same orchestrator session before closeout.\n"
        '7. Require each successful subagent to run `commit.sh --current --push --task <task-id> --msg "..."`'
        " from its assigned worktree.\n"
        f"8. Before each `st done <task-id>` call from `{project_root}`, check `st cleanup status`"
        " and resolve any task-related git or lane cleanup blockers.\n"
        "9. Run `st done <task-id>` yourself, serially, only after review and cleanup are satisfied.\n\n"
        "Hard constraints:\n"
        "- Do not mix files between task lanes.\n"
        "- Do not treat subagent output as final without review.\n"
        "- Do not edit task files directly when a subagent can do the work,"
        " unless you are explicitly fixing a failed pass.\n"
        "- No partial completions, placeholders, or unrelated cleanup.\n"
        f"- Stay within this project only.\n\nTask set:{task_blocks}\n\n"
        "Final response must include:\n"
        "- task ids completed\n"
        "- files changed per task\n"
        "- verification commands run per task\n"
        "- whether `commit.sh` and `st done` succeeded for each task"
    )
