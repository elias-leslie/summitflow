"""Claude Code worker dispatch commands."""

from __future__ import annotations

import subprocess  # noqa: F401  — kept for test patching: patch("cli.commands.claude.subprocess.run")
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from ..client import STClient
from ..output import handle_api_error, output_error
from ._claude_batch import commit_and_done_task, process_batch_results, run_batch_workers
from ._claude_constants import (
    _DEFAULT_MAX_SUBAGENTS,
    _DEFAULT_MODEL,
    _DEFAULT_TIMEOUT_SECONDS,
    OrchestratorTask,
    WorkerDispatch,
)
from ._claude_dispatch import (
    execute_orchestrator,
    fetch_task,
    prepare_orchestrator_task,
    prepare_worker_dispatch,
    resolve_agent_hub_paths,
    resolve_feedback_text,
    resolve_project_root,
    run_text_command,
    run_worker,
    validate_task_readiness,
)
from ._projects_helpers import projects_api

app = typer.Typer(help="Claude Code worker dispatch")
_Opt = typer.Option
_Arg = typer.Argument


def _fatal(msg: str) -> NoReturn:
    output_error(msg)
    raise typer.Exit(1)


# Thin wrappers: close over module-level names so tests can patch cli.commands.claude.STClient etc.

def _fetch_task(task_id: str) -> dict[str, object]:
    return fetch_task(task_id, client_cls=STClient, handle_api_error=handle_api_error)


def _validate_task_readiness(*, task_id: str, project_id: str, allow_unready: bool) -> None:
    validate_task_readiness(
        task_id=task_id, project_id=project_id, allow_unready=allow_unready, client_cls=STClient,
    )


def _resolve_project_root(project_id: str) -> Path:
    return resolve_project_root(project_id, projects_api_fn=projects_api, fatal=_fatal)


def _resolve_agent_hub_paths() -> tuple[Path, Path]:
    return resolve_agent_hub_paths(resolve_root_fn=_resolve_project_root, fatal=_fatal)


def _resolve_feedback_text(feedback_text: str | None, feedback_file: Path | None) -> str | None:
    return resolve_feedback_text(feedback_text, feedback_file, fatal=_fatal)


def _run_text_command(*, command: list[str], cwd: Path) -> str:
    return run_text_command(command=command, cwd=cwd)


def _prepare_worker_dispatch(
    *, task_id: str, model: str, timeout_seconds: int, claim_if_needed: bool,
    allow_unready: bool, feedback_text: str | None, index: int = 0,
) -> WorkerDispatch:
    return prepare_worker_dispatch(
        task_id=task_id, model=model, timeout_seconds=timeout_seconds,
        claim_if_needed=claim_if_needed, allow_unready=allow_unready,
        feedback_text=feedback_text, index=index,
        fetch_task_fn=_fetch_task, validate_readiness_fn=_validate_task_readiness,
        resolve_root_fn=_resolve_project_root, resolve_hub_fn=_resolve_agent_hub_paths,
    )


def _prepare_orchestrator_task(
    *, task: dict[str, object], allow_unready: bool, claim_if_needed: bool, index: int,
) -> OrchestratorTask:
    return prepare_orchestrator_task(
        task=task, allow_unready=allow_unready, claim_if_needed=claim_if_needed, index=index,
        fetch_task_fn=_fetch_task, validate_readiness_fn=_validate_task_readiness,
        resolve_root_fn=_resolve_project_root, run_text_fn=_run_text_command, fatal=_fatal,
    )


def _run_batch_workers(
    dispatches: list[WorkerDispatch], *, max_subagents: int, stop_on_error: bool,
) -> list[tuple[WorkerDispatch, int]]:
    return run_batch_workers(
        dispatches, max_subagents=max_subagents, stop_on_error=stop_on_error,
        run_worker_fn=lambda *, command, cwd: run_worker(command=command, cwd=cwd),
    )


def _commit_and_done_task(spec: WorkerDispatch) -> int:
    return commit_and_done_task(spec, fetch_task_fn=_fetch_task, fatal=_fatal)


# --- CLI commands ---

_StrOpt = lambda flag, help: _Opt(flag, help=help)  # noqa: E731
_TimeoutArg = Annotated[int, _Opt("--timeout-seconds", min=1, help="Worker timeout in seconds")]
_ModelArg = Annotated[str, _Opt("--model", help="Claude model override")]
_MaxSubArg = Annotated[int, _Opt("--max-subagents", min=1, help="Maximum concurrent Claude workers")]
_ClaimArg = Annotated[bool, _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim the task if unclaimed")]
_UnreadyArg = Annotated[bool, _Opt("--allow-unready", help="Skip execution-readiness validation")]
_FeedbackText = Annotated[str | None, _Opt("--feedback-text", help="Inline evaluator feedback for a redrive")]
_FeedbackFile = Annotated[Path | None, _Opt("--feedback-file", help="Read evaluator feedback from a file")]


@app.command("task")
def run_task(
    task_id: Annotated[str, _Arg(help="Task ID to dispatch through the Claude worker wrapper")],
    model: _ModelArg = _DEFAULT_MODEL,
    timeout_seconds: _TimeoutArg = _DEFAULT_TIMEOUT_SECONDS,
    claim_if_needed: _ClaimArg = True,
    allow_unready: _UnreadyArg = False,
    feedback_text: _FeedbackText = None,
    feedback_file: _FeedbackFile = None,
) -> None:
    """Run a task through the canonical Agent Hub Claude worker wrapper."""
    feedback = _resolve_feedback_text(feedback_text, feedback_file)
    dispatch = _prepare_worker_dispatch(
        task_id=task_id, model=model, timeout_seconds=timeout_seconds,
        claim_if_needed=claim_if_needed, allow_unready=allow_unready, feedback_text=feedback,
    )
    exit_code = run_worker(command=dispatch.command, cwd=dispatch.cwd)
    if exit_code != 0:
        raise typer.Exit(exit_code)


@app.command("batch")
def run_batch(
    task_ids: Annotated[list[str], _Arg(help="Task IDs to dispatch through the Claude worker wrapper")],
    model: _ModelArg = _DEFAULT_MODEL,
    timeout_seconds: _TimeoutArg = _DEFAULT_TIMEOUT_SECONDS,
    max_subagents: _MaxSubArg = _DEFAULT_MAX_SUBAGENTS,
    claim_if_needed: _ClaimArg = True,
    allow_unready: _UnreadyArg = False,
    stop_on_error: Annotated[
        bool, _Opt("--stop-on-error/--keep-going", help="Stop submitting after first worker failure"),
    ] = False,
    commit_and_done: Annotated[
        bool, _Opt("--commit-and-done/--no-commit-and-done", help="Commit/push and run st done on success"),
    ] = False,
    feedback_text: _FeedbackText = None,
    feedback_file: _FeedbackFile = None,
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
    process_batch_results(results, commit_and_done=commit_and_done, commit_fn=_commit_and_done_task)


@app.command("orchestrator")
def orchestrate_tasks(
    task_ids: Annotated[list[str], _Arg(help="Task IDs to orchestrate through a single Claude session")],
    model: _ModelArg = _DEFAULT_MODEL,
    timeout_seconds: _TimeoutArg = _DEFAULT_TIMEOUT_SECONDS,
    max_subagents: _MaxSubArg = _DEFAULT_MAX_SUBAGENTS,
    claim_if_needed: _ClaimArg = True,
    allow_unready: _UnreadyArg = False,
) -> None:
    """Run multiple same-project tasks through one Claude orchestrator session."""
    exit_code = execute_orchestrator(
        task_ids=task_ids, model=model, timeout_seconds=timeout_seconds,
        max_subagents=max_subagents, claim_if_needed=claim_if_needed, allow_unready=allow_unready,
        fetch_task_fn=_fetch_task, prepare_task_fn=_prepare_orchestrator_task,
        resolve_hub_fn=_resolve_agent_hub_paths,
        run_worker_fn=lambda *, command, cwd: run_worker(command=command, cwd=cwd),
        fatal=_fatal,
    )
    if exit_code != 0:
        raise typer.Exit(exit_code)
