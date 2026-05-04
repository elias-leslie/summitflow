"""Implementation helpers for scheduled Explorer scans."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def run_scan_job_isolated(
    project_id: str,
    entry_type: str | None,
    *,
    backend_root: Path,
    sentinel: str,
    subprocess_run: Callable[..., Any],
) -> dict[str, Any]:
    """Run one explorer scan in a short-lived child process."""
    proc = subprocess_run(
        [sys.executable, "-c", _isolated_scan_code(project_id, entry_type, sentinel)],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return _isolated_scan_payload(proc, sentinel)


def _isolated_scan_code(project_id: str, entry_type: str | None, sentinel: str) -> str:
    return f"""
import json
from app.services import explorer

payload = {{}}
try:
    result = explorer.run_scan_job(
        {project_id!r},
        {entry_type!r},
        triggered_by='scheduled',
    )
    payload = {{
        'status': 'success',
        'scan_id': result.get('scan_id'),
        'metrics': result.get('metrics', {{}}),
        'results': result.get('results', []),
        'error': result.get('error'),
    }}
except explorer.ScanAlreadyRunningError as exc:
    payload = {{
        'status': 'skipped_already_running',
        'scan_status': exc.scan_status,
    }}
except Exception as exc:
    payload = {{
        'status': 'error',
        'error': str(exc),
    }}

print({sentinel!r} + json.dumps(payload))
"""


def _isolated_scan_payload(proc: Any, sentinel: str) -> dict[str, Any]:
    stdout_lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    payload_line = next(
        (line for line in reversed(stdout_lines) if line.startswith(sentinel)),
        None,
    )
    if payload_line is None:
        raise RuntimeError(
            "isolated explorer scan produced no result payload"
            + _process_error_suffix(proc)
        )

    payload = json.loads(payload_line.removeprefix(sentinel))
    if proc.returncode != 0 and payload.get("status") != "error":
        raise RuntimeError(
            "isolated explorer scan exited unexpectedly"
            + _process_error_suffix(proc)
        )
    return payload


def _process_error_suffix(proc: Any) -> str:
    stderr = (proc.stderr or "")[-400:]
    return f" (rc={proc.returncode}, stderr={stderr!r})" if stderr or proc.returncode else ""


def scan_single_project(
    proj_id: str,
    proj_name: str,
    entry_type: str | None,
    dispatch: Callable[[str, str, str], None] | None,
    *,
    isolate_process: bool,
    run_scan_job: Callable[..., dict[str, Any]],
    run_scan_job_isolated: Callable[[str, str | None], dict[str, Any]],
    dispatch_post_scan_tasks: Callable[[Callable[[str, str, str], None], str], None],
    logger: Any,
) -> tuple[dict[str, Any], bool]:
    """Scan one project; return (detail_dict, success_flag)."""
    started_at = time.perf_counter()
    try:
        result = _run_project_scan(proj_id, entry_type, isolate_process, run_scan_job, run_scan_job_isolated)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        if result.get("status") == "skipped_already_running":
            return _skipped_scan_detail(proj_id, proj_name, entry_type, duration_ms, result, logger)
        if result.get("status") == "error":
            raise RuntimeError(str(result.get("error") or "isolated explorer scan failed"))
        _dispatch_after_scan(dispatch, dispatch_post_scan_tasks, proj_id, logger)
        return _success_scan_detail(proj_id, proj_name, entry_type, duration_ms, result, logger)
    except Exception as exc:
        return _error_scan_detail(proj_id, proj_name, entry_type, started_at, exc, logger)


def _run_project_scan(
    proj_id: str,
    entry_type: str | None,
    isolate_process: bool,
    run_scan_job: Callable[..., dict[str, Any]],
    run_scan_job_isolated: Callable[[str, str | None], dict[str, Any]],
) -> dict[str, Any]:
    if isolate_process:
        return run_scan_job_isolated(proj_id, entry_type)
    return run_scan_job(
        proj_id,
        entry_type,
        triggered_by="scheduled",
        enforce_exclusive=False,
    )


def _skipped_scan_detail(
    proj_id: str,
    proj_name: str,
    entry_type: str | None,
    duration_ms: float,
    result: dict[str, Any],
    logger: Any,
) -> tuple[dict[str, Any], bool]:
    logger.info(
        "project_scan_skipped_already_running",
        project_id=proj_id,
        entry_type=entry_type or "all",
        duration_ms=duration_ms,
    )
    return {
        "project_id": proj_id,
        "project_name": proj_name,
        "status": "skipped_already_running",
        "duration_ms": duration_ms,
        "scan_status": result.get("scan_status"),
    }, True


def _dispatch_after_scan(
    dispatch: Callable[[str, str, str], None] | None,
    dispatch_post_scan_tasks: Callable[[Callable[[str, str, str], None], str], None],
    proj_id: str,
    logger: Any,
) -> None:
    if not dispatch:
        return
    try:
        dispatch_post_scan_tasks(dispatch, proj_id)
    except Exception:
        logger.exception("post_scan_dispatch_failed", project_id=proj_id)


def _success_scan_detail(
    proj_id: str,
    proj_name: str,
    entry_type: str | None,
    duration_ms: float,
    result: dict[str, Any],
    logger: Any,
) -> tuple[dict[str, Any], bool]:
    logger.info(
        "project_scanned",
        project_id=proj_id,
        entry_type=entry_type or "all",
        results_count=len(result.get("results", [])),
        duration_ms=duration_ms,
    )
    return {
        "project_id": proj_id,
        "project_name": proj_name,
        "status": "success",
        "results": result.get("results", []),
        "scan_id": result.get("scan_id"),
        "metrics": result.get("metrics", {}),
        "duration_ms": duration_ms,
    }, True


def _error_scan_detail(
    proj_id: str,
    proj_name: str,
    entry_type: str | None,
    started_at: float,
    exc: Exception,
    logger: Any,
) -> tuple[dict[str, Any], bool]:
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    logger.error(
        "project_scan_failed",
        project_id=proj_id,
        entry_type=entry_type or "all",
        duration_ms=duration_ms,
        error=str(exc),
    )
    return {
        "project_id": proj_id,
        "project_name": proj_name,
        "status": "error",
        "error": str(exc),
        "duration_ms": duration_ms,
    }, False
