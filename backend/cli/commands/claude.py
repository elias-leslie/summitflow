"""Claude Code worker dispatch commands."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error
from ._projects_helpers import UNEXPECTED_RESPONSE_MSG, projects_api

app = typer.Typer(help="Claude Code worker dispatch")

_Opt = typer.Option
_Arg = typer.Argument

_AGENT_HUB_PROJECT_ID = "agent-hub"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_TIMEOUT_SECONDS = 1800
_DEFAULT_SOURCE = "st-cli"
_DEFAULT_MAX_SUBAGENTS = 4
_ORCHESTRATOR_SOURCE = "st-cli-orchestrator"
_ORCHESTRATOR_ALLOWED_TOOLS = "Read,Agent,Edit,MultiEdit,Write,Bash,Glob,Grep,LS"
_BACKEND_SUBDIR = "backend"
_TASK_STATUS_RUNNING = "running"
_WORKER_SUBAGENT_NAME = "task-worker"
_WORKER_SUBAGENT_MODEL = "sonnet"
_COMMIT_SCRIPT = "commit.sh"
_WORKTREE_PATH_PREFIX = "WORKTREE_PATH:"
_ORCHESTRATE_TMPDIR_PREFIX = "st-claude-orchestrate-"
_ORCHESTRATOR_PROMPT_FNAME = "orchestrator_prompt.md"
_ORCHESTRATOR_AGENTS_FNAME = "orchestrator_agents.json"

_WORKER_SUBAGENT_PAYLOAD: dict[str, Any] = {
    _WORKER_SUBAGENT_NAME: {
        "description": "Lane-bound task implementation worker",
        "prompt": (
            "You are assigned exactly one SummitFlow task lane. Work only inside the provided "
            "task worktree and only on files required for that task. Preserve behavior unless "
            "the task explicitly changes it. Run task-appropriate verification and `dt --quick "
            "--changed-only` before reporting success. If everything passes, run "
            '`commit.sh --current --push --task <task-id> --msg "..."` from the assigned '
            "worktree. Do not run `st done`; report back to the orchestrator."
        ),
        "tools": ["Read", "Edit", "MultiEdit", "Write", "Bash", "Glob", "Grep", "LS"],
        "model": _WORKER_SUBAGENT_MODEL,
    }
}


@dataclass(frozen=True)
class WorkerDispatch:
    index: int
    task_id: str
    project_id: str
    project_root: Path
    command: list[str]
    cwd: Path


@dataclass(frozen=True)
class OrchestratorTask:
    index: int
    task_id: str
    project_id: str
    project_root: Path
    worktree_path: Path
    context_text: str


def _fatal(msg: str) -> NoReturn:
    output_error(msg)
    raise typer.Exit(1)


def _fetch_task(task_id: str) -> dict[str, Any]:
    """Fetch task details from SummitFlow."""
    client = STClient(require_project=False)
    try:
        return client.get_task(task_id)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None


def _validate_task_readiness(*, task_id: str, project_id: str, allow_unready: bool) -> None:
    """Ensure the task is ready for worker dispatch unless explicitly overridden."""
    if allow_unready:
        return
    client = STClient(project_id=project_id, require_project=False)
    readiness = client.validate_ready(task_id)
    if readiness.get("ready", False):
        return
    output_error(f"Task {task_id} is not execution-ready for Claude worker dispatch.")
    for issue in readiness.get("issues", [])[:8]:
        output_error(f"  - {issue}")
    for suggestion in readiness.get("suggestions", [])[:5]:
        output_error(f"  hint: {suggestion}")
    raise typer.Exit(1)


def _resolve_project_root(project_id: str) -> Path:
    """Resolve a project root through the projects API."""
    project = projects_api("GET", f"/{project_id}")
    if not isinstance(project, dict):
        _fatal(UNEXPECTED_RESPONSE_MSG)
    root_path = project.get("root_path")
    if not isinstance(root_path, str) or not root_path.strip():
        _fatal(f"Project '{project_id}' has no root_path configured")
    return Path(root_path).resolve()


def _resolve_agent_hub_paths() -> tuple[Path, Path]:
    """Resolve the canonical Agent Hub Python entrypoint for the worker wrapper."""
    agent_hub_root = _resolve_project_root(_AGENT_HUB_PROJECT_ID)
    python_bin = agent_hub_root / _BACKEND_SUBDIR / ".venv" / "bin" / "python"
    script_path = agent_hub_root / _BACKEND_SUBDIR / "scripts" / "run_claude_orchestrated_worker.py"
    if not python_bin.is_file():
        _fatal(f"Agent Hub python not found: {python_bin}")
    if not script_path.is_file():
        _fatal(f"Claude worker script not found: {script_path}")
    return python_bin, script_path


def _resolve_feedback_text(feedback_text: str | None, feedback_file: Path | None) -> str | None:
    """Resolve evaluator feedback from inline text or a file."""
    if feedback_text and feedback_file:
        _fatal("Use either --feedback-text or --feedback-file, not both.")
    if feedback_file is None:
        return feedback_text
    if not feedback_file.is_file():
        _fatal(f"Feedback file not found: {feedback_file}")
    return feedback_file.read_text().strip() or None


def _run_text_command(*, command: list[str], cwd: Path) -> str:
    """Run a text command and return stdout, surfacing failures through Typer."""
    result = subprocess.run(
        command,
        cwd=cwd,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    stderr = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    output_error(f"Command failed: {' '.join(command)}")
    output_error(f"  {stderr}")
    raise typer.Exit(1)


def _build_worker_command(
    *,
    python_bin: Path,
    script_path: Path,
    task_id: str,
    project_id: str,
    project_root: Path,
    model: str,
    timeout_seconds: int,
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
        "--source", _DEFAULT_SOURCE,
    ]
    if claim_if_needed:
        command.append("--claim-if-needed")
    if feedback_text:
        command.extend(["--feedback-text", feedback_text])
    return command


def _run_worker(*, command: list[str], cwd: Path) -> int:
    """Run the worker wrapper and stream output through the current terminal."""
    env = os.environ.copy()
    env["PYTHONPATH"] = _BACKEND_SUBDIR
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    return int(result.returncode)


def _extract_worktree_path(task: dict[str, Any]) -> Path | None:
    worktree = task.get("worktree")
    if not isinstance(worktree, dict):
        return None
    raw_path = worktree.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return Path(raw_path).resolve()


def _prepare_worker_dispatch(
    *,
    task_id: str,
    model: str,
    timeout_seconds: int,
    claim_if_needed: bool,
    allow_unready: bool,
    feedback_text: str | None,
    index: int = 0,
) -> WorkerDispatch:
    """Prepare one Claude worker dispatch with resolved project roots."""
    task = _fetch_task(task_id)
    resolved_task_id = str(task.get("id", task_id))
    project_id = str(task.get("project_id") or "")
    if not project_id:
        _fatal(f"Task {resolved_task_id} has no project_id")
    _validate_task_readiness(
        task_id=resolved_task_id, project_id=project_id, allow_unready=allow_unready,
    )
    project_root = _resolve_project_root(project_id)
    python_bin, script_path = _resolve_agent_hub_paths()
    command = _build_worker_command(
        python_bin=python_bin,
        script_path=script_path,
        task_id=resolved_task_id,
        project_id=project_id,
        project_root=project_root,
        model=model,
        timeout_seconds=timeout_seconds,
        claim_if_needed=claim_if_needed,
        feedback_text=feedback_text,
    )
    return WorkerDispatch(
        index=index,
        task_id=resolved_task_id,
        project_id=project_id,
        project_root=project_root,
        command=command,
        cwd=script_path.parent.parent,
    )


def _prepare_orchestrator_task(
    *,
    task: dict[str, Any],
    allow_unready: bool,
    claim_if_needed: bool,
    index: int,
) -> OrchestratorTask:
    """Resolve one task into an orchestrator-ready assignment."""
    resolved_task_id = str(task.get("id") or "")
    if not resolved_task_id:
        _fatal("Orchestrator task payload is missing an id")
    project_id = str(task.get("project_id") or "")
    if not project_id:
        _fatal(f"Task {resolved_task_id} has no project_id")
    project_root = _resolve_project_root(project_id)
    worktree_path = _extract_worktree_path(task)
    status = str(task.get("status") or "")
    if status != _TASK_STATUS_RUNNING:
        _validate_task_readiness(
            task_id=resolved_task_id, project_id=project_id, allow_unready=allow_unready,
        )
    if worktree_path is None and claim_if_needed and status != _TASK_STATUS_RUNNING:
        _run_text_command(command=["st", "claim", resolved_task_id], cwd=project_root)
        task = _fetch_task(resolved_task_id)
        worktree_path = _extract_worktree_path(task)
    context_text = _run_text_command(command=["st", "context", resolved_task_id], cwd=project_root)
    if worktree_path is None:
        for raw_line in context_text.splitlines():
            if raw_line.startswith(_WORKTREE_PATH_PREFIX):
                raw_path = raw_line.split(":", 1)[1].strip()
                if raw_path:
                    worktree_path = Path(raw_path).resolve()
                    break
    if worktree_path is None:
        _fatal(f"Task {resolved_task_id} has no active worktree for orchestration")
    return OrchestratorTask(
        index=index,
        task_id=resolved_task_id,
        project_id=project_id,
        project_root=project_root,
        worktree_path=worktree_path,
        context_text=context_text.strip(),
    )


def _build_orchestrator_prompt(
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
        f"- Launch up to {max_subagents} Agent subagents in parallel using the named subagent `{_WORKER_SUBAGENT_NAME}`.\n"
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


def _build_prompt_worker_command(
    *,
    python_bin: Path,
    script_path: Path,
    prompt_file: Path,
    agents_file: Path | None,
    project_id: str,
    project_root: Path,
    model: str,
    timeout_seconds: int,
) -> list[str]:
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
    if agents_file is not None:
        command.extend(["--agents-file", str(agents_file)])
    return command


def _run_batch_workers(
    dispatches: list[WorkerDispatch],
    *,
    max_subagents: int,
    stop_on_error: bool,
) -> list[tuple[WorkerDispatch, int]]:
    """Run prepared worker dispatches with bounded parallelism."""
    if not dispatches:
        return []

    results: list[tuple[WorkerDispatch, int]] = []
    limit = max(1, min(max_subagents, len(dispatches)))

    with ThreadPoolExecutor(max_workers=limit) as executor:
        futures: dict[Any, WorkerDispatch] = {}
        next_index = 0
        stop_submitting = False

        def enqueue() -> None:
            nonlocal next_index, stop_submitting
            while not stop_submitting and next_index < len(dispatches) and len(futures) < limit:
                spec = dispatches[next_index]
                next_index += 1
                futures[executor.submit(lambda s=spec: (s, _run_worker(command=s.command, cwd=s.cwd)))] = spec

        def drain_done(done: Any) -> None:
            nonlocal stop_submitting
            for future in done:
                futures.pop(future)
                completed_spec, exit_code = future.result()
                results.append((completed_spec, exit_code))
                if stop_on_error and exit_code != 0:
                    stop_submitting = True

        enqueue()
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            drain_done(done)
            enqueue()

    results.sort(key=lambda item: item[0].index)
    return results


def _commit_and_done_task(spec: WorkerDispatch) -> int:
    """Commit/push the task worktree, then run canonical closeout."""
    task = _fetch_task(spec.task_id)
    worktree = task.get("worktree")
    if not isinstance(worktree, dict):
        _fatal(f"Task {spec.task_id} has no active worktree to commit/close")
    worktree_path_str = worktree.get("path")
    if not isinstance(worktree_path_str, str) or not worktree_path_str.strip():
        _fatal(f"Task {spec.task_id} returned an invalid worktree path")
    worktree_path = Path(worktree_path_str).resolve()
    commit_result = subprocess.run(
        [_COMMIT_SCRIPT, "--current", "--push", "--task", spec.task_id,
         "--msg", f"claude(batch): complete {spec.task_id}"],
        cwd=worktree_path,
        check=False,
    )
    if commit_result.returncode != 0:
        return int(commit_result.returncode)
    done_result = subprocess.run(
        ["st", "done", spec.task_id], cwd=spec.project_root, check=False,
    )
    return int(done_result.returncode)


def _process_batch_results(
    results: list[tuple[WorkerDispatch, int]], *, commit_and_done: bool
) -> None:
    """Report results and optionally commit/close each successful task."""
    worker_failed = False
    closeout_failed = False
    for spec, exit_code in results:
        if exit_code != 0:
            worker_failed = True
            output_error(f"Worker failed for {spec.task_id} (exit {exit_code})")
            continue
        typer.echo(f"Worker completed for {spec.task_id}")
        if not commit_and_done:
            continue
        closeout_code = _commit_and_done_task(spec)
        if closeout_code != 0:
            closeout_failed = True
            output_error(f"Closeout failed for {spec.task_id} (exit {closeout_code})")
        else:
            typer.echo(f"Committed and closed {spec.task_id}")
    if worker_failed or closeout_failed:
        raise typer.Exit(1)


@app.command("task")
def run_task(
    task_id: Annotated[str, _Arg(help="Task ID to dispatch through the Claude worker wrapper")],
    model: Annotated[str, _Opt("--model", help="Claude model override")] = _DEFAULT_MODEL,
    timeout_seconds: Annotated[
        int,
        _Opt("--timeout-seconds", min=1, help="Worker timeout budget in seconds"),
    ] = _DEFAULT_TIMEOUT_SECONDS,
    claim_if_needed: Annotated[
        bool,
        _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim the task if it is not already claimed"),
    ] = True,
    allow_unready: Annotated[
        bool,
        _Opt("--allow-unready", help="Skip execution-readiness validation"),
    ] = False,
    feedback_text: Annotated[
        str | None,
        _Opt("--feedback-text", help="Inline evaluator feedback for a redrive"),
    ] = None,
    feedback_file: Annotated[
        Path | None,
        _Opt("--feedback-file", help="Read evaluator feedback from a file"),
    ] = None,
) -> None:
    """Run a task through the canonical Agent Hub Claude worker wrapper."""
    feedback = _resolve_feedback_text(feedback_text, feedback_file)
    dispatch = _prepare_worker_dispatch(
        task_id=task_id,
        model=model,
        timeout_seconds=timeout_seconds,
        claim_if_needed=claim_if_needed,
        allow_unready=allow_unready,
        feedback_text=feedback,
    )
    exit_code = _run_worker(command=dispatch.command, cwd=dispatch.cwd)
    if exit_code != 0:
        raise typer.Exit(exit_code)


@app.command("batch")
def run_batch(
    task_ids: Annotated[list[str], _Arg(help="Task IDs to dispatch through the Claude worker wrapper")],
    model: Annotated[str, _Opt("--model", help="Claude model override")] = _DEFAULT_MODEL,
    timeout_seconds: Annotated[int, _Opt("--timeout-seconds", min=1, help="Worker timeout budget in seconds")] = _DEFAULT_TIMEOUT_SECONDS,
    max_subagents: Annotated[int, _Opt("--max-subagents", min=1, help="Maximum concurrent Claude worker runs")] = _DEFAULT_MAX_SUBAGENTS,
    claim_if_needed: Annotated[bool, _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim tasks if needed before dispatch")] = True,
    allow_unready: Annotated[bool, _Opt("--allow-unready", help="Skip execution-readiness validation")] = False,
    stop_on_error: Annotated[bool, _Opt("--stop-on-error/--keep-going", help="Stop submitting new tasks after the first worker failure")] = False,
    commit_and_done: Annotated[bool, _Opt("--commit-and-done/--no-commit-and-done", help="Commit/push each successful task worktree and run st done")] = False,
    feedback_text: Annotated[str | None, _Opt("--feedback-text", help="Inline evaluator feedback for a redrive")] = None,
    feedback_file: Annotated[Path | None, _Opt("--feedback-file", help="Read evaluator feedback from a file")] = None,
) -> None:
    """Run multiple tasks through the canonical Claude worker wrapper with bounded parallelism."""
    if not task_ids:
        _fatal("Provide at least one task id.")
    feedback = _resolve_feedback_text(feedback_text, feedback_file)
    dispatches = [
        _prepare_worker_dispatch(
            task_id=tid,
            model=model,
            timeout_seconds=timeout_seconds,
            claim_if_needed=claim_if_needed,
            allow_unready=allow_unready,
            feedback_text=feedback,
            index=index,
        )
        for index, tid in enumerate(task_ids)
    ]
    results = _run_batch_workers(dispatches, max_subagents=max_subagents, stop_on_error=stop_on_error)
    _process_batch_results(results, commit_and_done=commit_and_done)


@app.command("orchestrator")
def orchestrate_tasks(
    task_ids: Annotated[list[str], _Arg(help="Task IDs to orchestrate through a single Claude session")],
    model: Annotated[str, _Opt("--model", help="Claude model override")] = _DEFAULT_MODEL,
    timeout_seconds: Annotated[int, _Opt("--timeout-seconds", min=1, help="Worker timeout budget in seconds")] = _DEFAULT_TIMEOUT_SECONDS,
    max_subagents: Annotated[int, _Opt("--max-subagents", min=1, help="Maximum concurrent Claude subagents to instruct the orchestrator to use")] = _DEFAULT_MAX_SUBAGENTS,
    claim_if_needed: Annotated[bool, _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim tasks if needed before orchestration")] = True,
    allow_unready: Annotated[bool, _Opt("--allow-unready", help="Skip execution-readiness validation")] = False,
) -> None:
    """Run multiple same-project tasks through one Claude orchestrator session."""
    if not task_ids:
        _fatal("Provide at least one task id.")
    raw_tasks = [_fetch_task(tid) for tid in task_ids]
    project_ids = {str(t.get("project_id") or "") for t in raw_tasks}
    if "" in project_ids:
        _fatal("All orchestrated tasks must have a project_id.")
    if len(project_ids) != 1:
        _fatal("All orchestrated tasks must belong to the same project.")
    tasks = [
        _prepare_orchestrator_task(
            task=task, allow_unready=allow_unready, claim_if_needed=claim_if_needed, index=index,
        )
        for index, task in enumerate(raw_tasks)
    ]
    project_id = tasks[0].project_id
    project_root = tasks[0].project_root
    python_bin, script_path = _resolve_agent_hub_paths()
    prompt = _build_orchestrator_prompt(
        project_id=project_id, project_root=project_root, max_subagents=max_subagents, tasks=tasks,
    )
    with tempfile.TemporaryDirectory(prefix=_ORCHESTRATE_TMPDIR_PREFIX) as temp_dir:
        temp_root = Path(temp_dir)
        prompt_file = temp_root / _ORCHESTRATOR_PROMPT_FNAME
        agents_file = temp_root / _ORCHESTRATOR_AGENTS_FNAME
        prompt_file.write_text(prompt)
        agents_file.write_text(json.dumps(_WORKER_SUBAGENT_PAYLOAD, indent=2))
        command = _build_prompt_worker_command(
            python_bin=python_bin, script_path=script_path,
            prompt_file=prompt_file, agents_file=agents_file,
            project_id=project_id, project_root=project_root,
            model=model, timeout_seconds=timeout_seconds,
        )
        exit_code = _run_worker(command=command, cwd=script_path.parent.parent)
    if exit_code != 0:
        raise typer.Exit(exit_code)
