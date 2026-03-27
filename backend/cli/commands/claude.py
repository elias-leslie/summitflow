"""Claude Code worker dispatch commands."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error
from ._claude_builders import (
    build_orchestrator_prompt,
    build_prompt_worker_command,
    build_worker_command,
)
from ._claude_constants import (
    _AGENT_HUB_PROJECT_ID,
    _BACKEND_SUBDIR,
    _COMMIT_SCRIPT,
    _DEFAULT_MAX_SUBAGENTS,
    _DEFAULT_MODEL,
    _DEFAULT_SOURCE,
    _DEFAULT_TIMEOUT_SECONDS,
    _ORCHESTRATE_TMPDIR_PREFIX,
    _ORCHESTRATOR_AGENTS_FNAME,
    _ORCHESTRATOR_PROMPT_FNAME,
    _TASK_STATUS_RUNNING,
    _WORKER_SUBAGENT_PAYLOAD,
    _WORKTREE_PATH_PREFIX,
    OrchestratorTask,
    WorkerDispatch,
)
from ._projects_helpers import UNEXPECTED_RESPONSE_MSG, projects_api

app = typer.Typer(help="Claude Code worker dispatch")

_Opt = typer.Option
_Arg = typer.Argument


def _fatal(msg: str) -> NoReturn:
    output_error(msg)
    raise typer.Exit(1)


def _fetch_task(task_id: str) -> dict[str, object]:
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
    """Run a command and return stdout, surfacing failures through Typer."""
    result = subprocess.run(
        command, cwd=cwd, env=os.environ.copy(), check=False, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return result.stdout
    stderr = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    output_error(f"Command failed: {' '.join(command)}")
    output_error(f"  {stderr}")
    raise typer.Exit(1)


def _run_worker(*, command: list[str], cwd: Path) -> int:
    """Run the worker wrapper and stream output through the current terminal."""
    env = os.environ.copy()
    env["PYTHONPATH"] = _BACKEND_SUBDIR
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    return int(result.returncode)


def _extract_worktree_path(task: dict[str, object]) -> Path | None:
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
    command = build_worker_command(
        python_bin=python_bin,
        script_path=script_path,
        task_id=resolved_task_id,
        project_id=project_id,
        project_root=project_root,
        model=model,
        timeout_seconds=timeout_seconds,
        source=_DEFAULT_SOURCE,
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
    task: dict[str, object],
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
        worktree_path = _worktree_from_context(context_text)
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


def _worktree_from_context(context_text: str) -> Path | None:
    """Extract a worktree path from context output lines."""
    for raw_line in context_text.splitlines():
        if raw_line.startswith(_WORKTREE_PATH_PREFIX):
            raw_path = raw_line.split(":", 1)[1].strip()
            if raw_path:
                return Path(raw_path).resolve()
    return None


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
        futures: dict[Future[tuple[WorkerDispatch, int]], WorkerDispatch] = {}
        next_index = 0
        stop_submitting = False

        def enqueue() -> None:
            nonlocal next_index, stop_submitting
            while not stop_submitting and next_index < len(dispatches) and len(futures) < limit:
                spec = dispatches[next_index]
                next_index += 1
                futures[executor.submit(lambda s=spec: (s, _run_worker(command=s.command, cwd=s.cwd)))] = spec

        def drain_done(done: set[Future[tuple[WorkerDispatch, int]]]) -> None:
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
        int, _Opt("--timeout-seconds", min=1, help="Worker timeout budget in seconds"),
    ] = _DEFAULT_TIMEOUT_SECONDS,
    claim_if_needed: Annotated[
        bool, _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim the task if not already claimed"),
    ] = True,
    allow_unready: Annotated[
        bool, _Opt("--allow-unready", help="Skip execution-readiness validation"),
    ] = False,
    feedback_text: Annotated[
        str | None, _Opt("--feedback-text", help="Inline evaluator feedback for a redrive"),
    ] = None,
    feedback_file: Annotated[
        Path | None, _Opt("--feedback-file", help="Read evaluator feedback from a file"),
    ] = None,
) -> None:
    """Run a task through the canonical Agent Hub Claude worker wrapper."""
    feedback = _resolve_feedback_text(feedback_text, feedback_file)
    dispatch = _prepare_worker_dispatch(
        task_id=task_id, model=model, timeout_seconds=timeout_seconds,
        claim_if_needed=claim_if_needed, allow_unready=allow_unready, feedback_text=feedback,
    )
    exit_code = _run_worker(command=dispatch.command, cwd=dispatch.cwd)
    if exit_code != 0:
        raise typer.Exit(exit_code)


@app.command("batch")
def run_batch(
    task_ids: Annotated[list[str], _Arg(help="Task IDs to dispatch through the Claude worker wrapper")],
    model: Annotated[str, _Opt("--model", help="Claude model override")] = _DEFAULT_MODEL,
    timeout_seconds: Annotated[
        int, _Opt("--timeout-seconds", min=1, help="Worker timeout budget in seconds"),
    ] = _DEFAULT_TIMEOUT_SECONDS,
    max_subagents: Annotated[
        int, _Opt("--max-subagents", min=1, help="Maximum concurrent Claude worker runs"),
    ] = _DEFAULT_MAX_SUBAGENTS,
    claim_if_needed: Annotated[
        bool, _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim tasks if needed before dispatch"),
    ] = True,
    allow_unready: Annotated[
        bool, _Opt("--allow-unready", help="Skip execution-readiness validation"),
    ] = False,
    stop_on_error: Annotated[
        bool, _Opt("--stop-on-error/--keep-going", help="Stop submitting after first worker failure"),
    ] = False,
    commit_and_done: Annotated[
        bool, _Opt("--commit-and-done/--no-commit-and-done", help="Commit/push and run st done on success"),
    ] = False,
    feedback_text: Annotated[
        str | None, _Opt("--feedback-text", help="Inline evaluator feedback for a redrive"),
    ] = None,
    feedback_file: Annotated[
        Path | None, _Opt("--feedback-file", help="Read evaluator feedback from a file"),
    ] = None,
) -> None:
    """Run multiple tasks through the canonical Claude worker wrapper with bounded parallelism."""
    if not task_ids:
        _fatal("Provide at least one task id.")
    feedback = _resolve_feedback_text(feedback_text, feedback_file)
    dispatches = [
        _prepare_worker_dispatch(
            task_id=tid, model=model, timeout_seconds=timeout_seconds,
            claim_if_needed=claim_if_needed, allow_unready=allow_unready,
            feedback_text=feedback, index=index,
        )
        for index, tid in enumerate(task_ids)
    ]
    results = _run_batch_workers(dispatches, max_subagents=max_subagents, stop_on_error=stop_on_error)
    _process_batch_results(results, commit_and_done=commit_and_done)


@app.command("orchestrator")
def orchestrate_tasks(
    task_ids: Annotated[list[str], _Arg(help="Task IDs to orchestrate through a single Claude session")],
    model: Annotated[str, _Opt("--model", help="Claude model override")] = _DEFAULT_MODEL,
    timeout_seconds: Annotated[
        int, _Opt("--timeout-seconds", min=1, help="Worker timeout budget in seconds"),
    ] = _DEFAULT_TIMEOUT_SECONDS,
    max_subagents: Annotated[
        int, _Opt("--max-subagents", min=1, help="Maximum concurrent Claude subagents for the orchestrator"),
    ] = _DEFAULT_MAX_SUBAGENTS,
    claim_if_needed: Annotated[
        bool, _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim tasks if needed before orchestration"),
    ] = True,
    allow_unready: Annotated[
        bool, _Opt("--allow-unready", help="Skip execution-readiness validation"),
    ] = False,
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
    prompt = build_orchestrator_prompt(
        project_id=project_id, project_root=project_root, max_subagents=max_subagents, tasks=tasks,
    )
    with tempfile.TemporaryDirectory(prefix=_ORCHESTRATE_TMPDIR_PREFIX) as temp_dir:
        temp_root = Path(temp_dir)
        prompt_file = temp_root / _ORCHESTRATOR_PROMPT_FNAME
        agents_file = temp_root / _ORCHESTRATOR_AGENTS_FNAME
        prompt_file.write_text(prompt)
        agents_file.write_text(json.dumps(_WORKER_SUBAGENT_PAYLOAD, indent=2))
        command = build_prompt_worker_command(
            python_bin=python_bin, script_path=script_path,
            prompt_file=prompt_file, agents_file=agents_file,
            project_id=project_id, project_root=project_root,
            model=model, timeout_seconds=timeout_seconds,
        )
        exit_code = _run_worker(command=command, cwd=script_path.parent.parent)
    if exit_code != 0:
        raise typer.Exit(exit_code)
