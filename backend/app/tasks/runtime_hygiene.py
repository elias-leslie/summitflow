"""Daily runtime hygiene audit for SummitFlow and Agent Hub."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import psutil
import psycopg
from psycopg import sql

from app.logging_config import get_logger
from app.services.explorer.types.database_config import get_db_url_for_project
from app.services.resource_monitor import get_cpu_usage, get_disk_usages, get_memory_usage
from app.services.self_healing.monitor import SystemdMonitor
from app.storage import backups as backup_store
from app.storage import maintenance_runs as maintenance_store
from app.storage import tasks as task_store
from app.storage.connection import get_cursor
from app.storage.task_spirit import (
    approve_plan,
    create_task_spirit,
    get_task_spirit,
    update_task_spirit,
)
from app.tasks.autonomous._subtask_builder import create_single_subtask_with_steps
from app.tasks.backup_drain import drain_pending_backups
from app.tasks.backup_executor import create_backup
from app.tasks.host_retention import cleanup_host_artifacts

from . import runtime_hygiene_backups as backups_impl
from . import runtime_hygiene_db as db_impl
from . import runtime_hygiene_host as host_impl
from . import runtime_hygiene_project as project_impl
from . import runtime_hygiene_runner as runner_impl
from .runtime_hygiene_common import (
    WORKFLOW_NAME as _WORKFLOW_NAME,
)
from .runtime_hygiene_common import (
    coerce_datetime as _coerce_datetime,
)
from .runtime_hygiene_common import (
    json_safe as _json_safe,
)
from .runtime_hygiene_common import (
    now_utc as _now,
)
from .runtime_hygiene_common import (
    severity_rank as _severity_rank,
)
from .runtime_hygiene_issues import (
    create_or_refresh_issue_task as _create_or_refresh_issue_task_impl,
)
from .runtime_hygiene_issues import (
    highest_severity,
    host_issue,
    persist_issues,
    project_issue,
)

logger = get_logger(__name__)
_PATCH_SURFACE = (
    psutil,
    psycopg,
    sql,
    get_db_url_for_project,
    get_cpu_usage,
    get_disk_usages,
    get_memory_usage,
    SystemdMonitor,
    backup_store,
    maintenance_store,
    task_store,
    get_cursor,
    approve_plan,
    create_task_spirit,
    get_task_spirit,
    update_task_spirit,
    create_single_subtask_with_steps,
    drain_pending_backups,
    create_backup,
    cleanup_host_artifacts,
    _coerce_datetime,
    _json_safe,
    _now,
    _severity_rank,
    highest_severity,
    host_issue,
    persist_issues,
    project_issue,
)


def _deps() -> Any:
    return sys.modules[__name__]


def _latest_runtime_hygiene_run() -> dict[str, Any] | None:
    return backups_impl.latest_run(_WORKFLOW_NAME, _deps())


def _run_started_within(workflow_name: str, *, hours: float, now: datetime) -> bool:
    return backups_impl.run_started_within(workflow_name, hours=hours, now=now, deps=_deps())


def _recent_action_succeeded(
    latest_run: dict[str, Any] | None,
    *,
    action_type: str,
    fingerprint: str,
    now: datetime,
) -> bool:
    return backups_impl.recent_action_succeeded(
        latest_run,
        action_type=action_type,
        fingerprint=fingerprint,
        now=now,
        deps=_deps(),
    )


def _backup_rows_by_source() -> dict[str, dict[str, Any]]:
    return backups_impl.backup_rows_by_source(_deps())


def _ensure_backup_fresh(
    *,
    project_id: str,
    source_id: str,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    return backups_impl.ensure_backup_fresh(
        project_id=project_id,
        source_id=source_id,
        backup_rows=backup_rows,
        latest_runtime_hygiene=latest_runtime_hygiene,
        actions_taken=actions_taken,
        now=now,
        deps=_deps(),
    )


def _infrastructure_protection(
    *,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    return backups_impl.infrastructure_protection(
        backup_rows=backup_rows,
        latest_runtime_hygiene=latest_runtime_hygiene,
        actions_taken=actions_taken,
        now=now,
        deps=_deps(),
    )


def _query_bloat_candidates(project_id: str) -> dict[str, Any]:
    return db_impl.query_bloat_candidates(project_id, _deps())


def _vacuum_analyze_table(project_id: str, schema_name: str, table_name: str) -> dict[str, Any]:
    return db_impl.vacuum_analyze_table(project_id, schema_name, table_name, _deps())


def _create_or_refresh_issue_task(issue: dict[str, Any]) -> tuple[str, bool]:
    return _create_or_refresh_issue_task_impl(issue, _deps())


def _collect_host_snapshot(*, include_top_processes: bool) -> dict[str, Any]:
    return host_impl.collect_host_snapshot(include_top_processes=include_top_processes, deps=_deps())


def _host_pressure(
    *,
    latest_runtime_hygiene: dict[str, Any] | None,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    return host_impl.host_pressure(
        latest_runtime_hygiene=latest_runtime_hygiene,
        now=now,
        deps=_deps(),
    )


def _journal_findings(project_id: str) -> dict[str, Any]:
    return project_impl.journal_findings(project_id, _deps())


def _project_target(
    project_id: str,
    *,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    return project_impl.project_target(
        project_id,
        backup_rows=backup_rows,
        latest_runtime_hygiene=latest_runtime_hygiene,
        now=now,
        deps=_deps(),
    )


def run_runtime_hygiene() -> dict[str, Any]:
    """Run one daily runtime hygiene audit and record the summary."""
    return runner_impl.run_runtime_hygiene(_deps())


__all__ = ["run_runtime_hygiene"]
