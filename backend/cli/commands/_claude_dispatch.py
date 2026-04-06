"""Dispatch preparation helpers for Claude worker commands — dependency-injected."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from ..output import output_error
from ._claude_builders import (
    build_orchestrator_prompt,
    build_prompt_worker_command,
    build_worker_command,
)
from ._claude_constants import (
    _AGENT_HUB_PROJECT_ID,
    _BACKEND_SUBDIR,
    _DEFAULT_SOURCE,
    _ORCHESTRATE_TMPDIR_PREFIX,
    _ORCHESTRATOR_AGENTS_FNAME,
    _ORCHESTRATOR_PROMPT_FNAME,
    _TASK_STATUS_RUNNING,
    _WORKER_SUBAGENT_PAYLOAD,
    _WORKTREE_PATH_PREFIX,
    OrchestratorTask,
    WorkerDispatch,
)
from ._projects_helpers import UNEXPECTED_RESPONSE_MSG

_FetchFn = Callable[[str], dict[str, object]]
_TextCmdFn = Callable[..., str]


def fetch_task(task_id: str, *, client_cls: Any, handle_api_error: Callable) -> dict[str, object]:
    """Fetch task details from SummitFlow."""
    from ..client import APIError
    client = client_cls(require_project=False)
    try:
        return client.get_task(task_id)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None


def validate_task_readiness(
    *, task_id: str, project_id: str, allow_unready: bool, client_cls: Any,
) -> None:
    """Ensure the task is ready for worker dispatch unless explicitly overridden."""
    if allow_unready:
        return
    client = client_cls(project_id=project_id, require_project=False)
    readiness = client.validate_ready(task_id)
    if readiness.get("ready", False):
        return
    output_error(f"Task {task_id} is not execution-ready for Claude worker dispatch.")
    for issue in readiness.get("issues", [])[:8]:
        output_error(f"  - {issue}")
    for suggestion in readiness.get("suggestions", [])[:5]:
        output_error(f"  hint: {suggestion}")
    raise typer.Exit(1)


def resolve_project_root(project_id: str, *, projects_api_fn: Any, fatal: Callable) -> Path:
    """Resolve a project root through the projects API."""
    project = projects_api_fn("GET", f"/{project_id}")
    if not isinstance(project, dict):
        fatal(UNEXPECTED_RESPONSE_MSG)
    root_path = project.get("root_path")
    if not isinstance(root_path, str) or not root_path.strip():
        fatal(f"Project '{project_id}' has no root_path configured")
    return Path(root_path).resolve()


def resolve_agent_hub_paths(*, resolve_root_fn: Callable, fatal: Callable) -> tuple[Path, Path]:
    """Resolve the canonical Agent Hub Python entrypoint for the worker wrapper."""
    agent_hub_root = resolve_root_fn(_AGENT_HUB_PROJECT_ID)
    python_bin = agent_hub_root / _BACKEND_SUBDIR / ".venv" / "bin" / "python"
    script_path = agent_hub_root / _BACKEND_SUBDIR / "scripts" / "run_claude_orchestrated_worker.py"
    if not python_bin.is_file():
        fatal(f"Agent Hub python not found: {python_bin}")
    if not script_path.is_file():
        fatal(f"Claude worker script not found: {script_path}")
    return python_bin, script_path


def resolve_feedback_text(
    feedback_text: str | None, feedback_file: Path | None, *, fatal: Callable,
) -> str | None:
    """Resolve evaluator feedback from inline text or a file."""
    if feedback_text and feedback_file:
        fatal("Use either --feedback-text or --feedback-file, not both.")
    if feedback_file is None:
        return feedback_text
    if not feedback_file.is_file():
        fatal(f"Feedback file not found: {feedback_file}")
    return feedback_file.read_text().strip() or None


def run_text_command(*, command: list[str], cwd: Path) -> str:
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


def run_worker(*, command: list[str], cwd: Path) -> int:
    """Run the worker wrapper and stream output through the current terminal."""
    env = os.environ.copy()
    env["PYTHONPATH"] = _BACKEND_SUBDIR
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    return int(result.returncode)


def extract_worktree_path(task: dict[str, object]) -> Path | None:
    worktree = task.get("worktree")
    if not isinstance(worktree, dict):
        return None
    raw_path = worktree.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return Path(raw_path).resolve()


def worktree_from_context(context_text: str) -> Path | None:
    """Extract a worktree path from context output lines."""
    for raw_line in context_text.splitlines():
        if raw_line.startswith(_WORKTREE_PATH_PREFIX):
            raw_path = raw_line.split(":", 1)[1].strip()
            if raw_path:
                return Path(raw_path).resolve()
    return None


def prepare_worker_dispatch(
    *,
    task_id: str,
    model: str,
    timeout_seconds: int,
    claim_if_needed: bool,
    allow_unready: bool,
    feedback_text: str | None,
    effort: str | None,
    append_system_prompt: str | None,
    skills: list[str] | None,
    index: int = 0,
    fetch_task_fn: _FetchFn,
    validate_readiness_fn: Callable,
    resolve_root_fn: Callable,
    resolve_hub_fn: Callable,
) -> WorkerDispatch:
    """Prepare one Claude worker dispatch with resolved project roots."""
    task = fetch_task_fn(task_id)
    resolved_task_id = str(task.get("id", task_id))
    project_id = str(task.get("project_id") or "")
    if not project_id:
        output_error(f"Task {resolved_task_id} has no project_id")
        raise typer.Exit(1)
    validate_readiness_fn(
        task_id=resolved_task_id, project_id=project_id, allow_unready=allow_unready,
    )
    project_root = resolve_root_fn(project_id)
    python_bin, script_path = resolve_hub_fn()
    command = build_worker_command(
        python_bin=python_bin, script_path=script_path, task_id=resolved_task_id,
        project_id=project_id, project_root=project_root, model=model,
        timeout_seconds=timeout_seconds, source=_DEFAULT_SOURCE,
        claim_if_needed=claim_if_needed, feedback_text=feedback_text,
        effort=effort, append_system_prompt=append_system_prompt, skills=skills,
    )
    return WorkerDispatch(
        index=index, task_id=resolved_task_id, project_id=project_id,
        project_root=project_root, command=command, cwd=script_path.parent.parent,
    )


def prepare_orchestrator_task(
    *,
    task: dict[str, object],
    allow_unready: bool,
    claim_if_needed: bool,
    index: int,
    fetch_task_fn: _FetchFn,
    validate_readiness_fn: Callable,
    resolve_root_fn: Callable,
    run_text_fn: _TextCmdFn,
    fatal: Callable,
) -> OrchestratorTask:
    """Resolve one task into an orchestrator-ready assignment."""
    resolved_task_id = str(task.get("id") or "")
    if not resolved_task_id:
        fatal("Orchestrator task payload is missing an id")
    project_id = str(task.get("project_id") or "")
    if not project_id:
        fatal(f"Task {resolved_task_id} has no project_id")
    project_root = resolve_root_fn(project_id)
    worktree_path = extract_worktree_path(task)
    status = str(task.get("status") or "")
    if status != _TASK_STATUS_RUNNING:
        validate_readiness_fn(
            task_id=resolved_task_id, project_id=project_id, allow_unready=allow_unready,
        )
    if worktree_path is None and claim_if_needed and status != _TASK_STATUS_RUNNING:
        run_text_fn(command=["st", "claim", resolved_task_id], cwd=project_root)
        task = fetch_task_fn(resolved_task_id)
        worktree_path = extract_worktree_path(task)
    context_text = run_text_fn(command=["st", "context", resolved_task_id], cwd=project_root)
    if worktree_path is None:
        worktree_path = worktree_from_context(context_text)
    if worktree_path is None:
        fatal(f"Task {resolved_task_id} has no active worktree for orchestration")
    return OrchestratorTask(
        index=index, task_id=resolved_task_id, project_id=project_id,
        project_root=project_root, worktree_path=worktree_path, context_text=context_text.strip(),
    )


def execute_orchestrator(
    *,
    task_ids: list[str],
    model: str,
    timeout_seconds: int,
    max_subagents: int,
    claim_if_needed: bool,
    allow_unready: bool,
    effort: str | None,
    append_system_prompt: str | None,
    skills: list[str] | None,
    fetch_task_fn: _FetchFn,
    prepare_task_fn: Callable,
    resolve_hub_fn: Callable,
    run_worker_fn: Callable,
    fatal: Callable,
) -> int:
    """Validate task set, build orchestrator prompt, and launch the worker. Returns exit code."""
    if not task_ids:
        fatal("Provide at least one task id.")
    raw_tasks = [fetch_task_fn(tid) for tid in task_ids]
    project_ids = {str(t.get("project_id") or "") for t in raw_tasks}
    if "" in project_ids:
        fatal("All orchestrated tasks must have a project_id.")
    if len(project_ids) != 1:
        fatal("All orchestrated tasks must belong to the same project.")
    tasks = [
        prepare_task_fn(task=task, allow_unready=allow_unready, claim_if_needed=claim_if_needed, index=i)
        for i, task in enumerate(raw_tasks)
    ]
    project_id = tasks[0].project_id
    project_root = tasks[0].project_root
    python_bin, script_path = resolve_hub_fn()
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
            batch_task_ids=[task.task_id for task in tasks],
            project_id=project_id, project_root=project_root,
            model=model, timeout_seconds=timeout_seconds,
            effort=effort, append_system_prompt=append_system_prompt, skills=skills,
        )
        return run_worker_fn(command=command, cwd=script_path.parent.parent)
