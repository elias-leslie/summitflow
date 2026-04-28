"""Batch worker execution helpers for Claude worker commands."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

import typer

from ..output import output_error
from ._claude_constants import _COMMIT_COMMAND, WorkerDispatch

_FetchFn = Callable[[str], dict[str, object]]
_RunWorkerFn = Callable[..., int]
_CommitFn = Callable[["WorkerDispatch"], int]


def run_batch_workers(
    dispatches: list[WorkerDispatch],
    *,
    max_subagents: int,
    stop_on_error: bool,
    run_worker_fn: _RunWorkerFn,
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
                futures[executor.submit(
                    lambda s=spec: (s, run_worker_fn(command=s.command, cwd=s.cwd))
                )] = spec

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


def commit_and_done_task(spec: WorkerDispatch, *, fetch_task_fn: _FetchFn, fatal: Callable) -> int:
    """Commit/push the task checkout, then run canonical closeout."""
    fetch_task_fn(spec.task_id)
    commit_result = subprocess.run(
        [*_COMMIT_COMMAND, "--push", "--task", spec.task_id,
         "--message", f"claude(batch): complete {spec.task_id}"],
        cwd=spec.project_root, check=False,
    )
    if commit_result.returncode != 0:
        return int(commit_result.returncode)
    done_result = subprocess.run(
        ["st", "done", spec.task_id], cwd=spec.project_root, check=False,
    )
    return int(done_result.returncode)


def process_batch_results(
    results: list[tuple[WorkerDispatch, int]],
    *,
    commit_and_done: bool,
    commit_fn: _CommitFn,
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
        closeout_code = commit_fn(spec)
        if closeout_code != 0:
            closeout_failed = True
            output_error(f"Closeout failed for {spec.task_id} (exit {closeout_code})")
        else:
            typer.echo(f"Committed and closed {spec.task_id}")
    if worker_failed or closeout_failed:
        raise typer.Exit(1)
