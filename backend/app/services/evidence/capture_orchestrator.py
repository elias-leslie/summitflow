"""Capture orchestrator - coordinates evidence capture across entries and strategies."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ...storage import evidence_config as config_storage
from ...storage.connection import get_connection
from .capture_strategies.base import (
    CaptureConfig,
    CaptureStrategy,
    EvidenceResult,
    ExplorerEntry,
)
from .capture_strategies.browser import BrowserCapture
from .capture_strategies.http import HttpCapture

logger = logging.getLogger(__name__)

# Registry of available capture strategies
_strategies: list[CaptureStrategy] = [
    BrowserCapture(),
    HttpCapture(),
]


def get_strategy_for_entry_type(entry_type: str) -> CaptureStrategy | None:
    """Get the appropriate capture strategy for an entry type."""
    for strategy in _strategies:
        if strategy.supports_entry_type(entry_type):
            return strategy
    return None


def register_strategy(strategy: CaptureStrategy) -> None:
    """Register a new capture strategy."""
    _strategies.append(strategy)


async def orchestrate_capture(
    project_id: str,
    scope: str = "project",
    entry_ids: list[int] | None = None,
    viewports: list[dict[str, Any]] | None = None,
    environment: str = "local",
) -> CaptureJobResult:
    """Orchestrate evidence capture for a project or specific entries.

    Args:
        project_id: Project ID to capture evidence for
        scope: 'project' (all entries), 'entry' (specific entries), or 'type' (by entry type)
        entry_ids: Specific entry IDs to capture (when scope='entry')
        viewports: Override viewports (uses project config if not specified)
        environment: Environment name (local, staging, production)

    Returns:
        CaptureJobResult with capture statistics
    """
    # Get project config
    project_config = config_storage.get_config(project_id)
    if viewports is None:
        # Cast ViewportConfig to dict[str, Any] for flexibility
        config_viewports = project_config.get("viewports", config_storage.DEFAULT_VIEWPORTS)
        viewports = [dict(v) for v in config_viewports]

    # Create capture job record
    job_id = await _create_capture_job(
        project_id=project_id,
        scope=scope,
        entry_ids=entry_ids,
    )

    # Get entries to capture
    entries = await _get_entries_to_capture(project_id, scope, entry_ids)

    result = CaptureJobResult(
        job_id=job_id,
        project_id=project_id,
        scope=scope,
        started_at=datetime.now(),
    )

    # Capture evidence for each entry
    for entry in entries:
        entry_type = entry.get("entry_type", "")
        strategy = get_strategy_for_entry_type(entry_type)

        if strategy is None:
            result.skipped += 1
            result.errors.append(f"No strategy for entry type: {entry_type}")
            continue

        try:
            # Build capture config
            capture_config: CaptureConfig = {
                "viewports": viewports,
                "environment": environment,
                "auth_headers": _get_auth_headers(project_id, environment),
            }

            # Cast entry to ExplorerEntry type
            explorer_entry: ExplorerEntry = {
                "id": entry.get("id", 0),
                "project_id": entry.get("project_id", ""),
                "entry_type": entry.get("entry_type", ""),
                "path": entry.get("path", ""),
                "name": entry.get("name", ""),
                "health_status": entry.get("health_status", "unknown"),
                "metadata": entry.get("metadata", {}),
            }

            # Capture evidence
            evidence_results = await strategy.capture(explorer_entry, capture_config)

            for ev_result in evidence_results:
                if ev_result.success:
                    # Store evidence in database
                    await _store_evidence(
                        project_id=project_id,
                        explorer_entry_id=entry.get("id"),
                        evidence_result=ev_result,
                        environment=environment,
                    )
                    result.captured += 1
                else:
                    result.failed += 1
                    result.errors.extend(ev_result.errors)

        except Exception as e:
            logger.exception(f"Error capturing evidence for entry {entry.get('id')}")
            result.failed += 1
            result.errors.append(str(e))

    # Complete job
    result.completed_at = datetime.now()
    await _complete_capture_job(job_id, result)

    return result


class CaptureJobResult:
    """Result of a capture job."""

    def __init__(
        self,
        job_id: int,
        project_id: str,
        scope: str,
        started_at: datetime,
    ):
        self.job_id = job_id
        self.project_id = project_id
        self.scope = scope
        self.started_at = started_at
        self.completed_at: datetime | None = None
        self.captured = 0
        self.failed = 0
        self.skipped = 0
        self.regressions_found = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "scope": self.scope,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "captured": self.captured,
            "failed": self.failed,
            "skipped": self.skipped,
            "regressions_found": self.regressions_found,
            "errors": self.errors[:10],  # Limit errors in response
        }


async def _create_capture_job(
    project_id: str,
    scope: str,
    entry_ids: list[int] | None,
) -> int:
    """Create a capture job record."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evidence_capture_jobs (
                project_id, job_type, scope, target_entry_ids, status, started_at
            )
            VALUES (%s, 'manual', %s, %s, 'running', NOW())
            RETURNING id
            """,
            (project_id, scope, entry_ids),
        )
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else 0


async def _complete_capture_job(job_id: int, result: CaptureJobResult) -> None:
    """Update job with completion status."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evidence_capture_jobs
            SET status = %s,
                completed_at = NOW(),
                entries_captured = %s,
                regressions_found = %s,
                error_message = %s
            WHERE id = %s
            """,
            (
                "completed" if not result.errors else "completed_with_errors",
                result.captured,
                result.regressions_found,
                "\n".join(result.errors[:5]) if result.errors else None,
                job_id,
            ),
        )
        conn.commit()


async def _get_entries_to_capture(
    project_id: str,
    scope: str,
    entry_ids: list[int] | None,
) -> list[dict[str, Any]]:
    """Get explorer entries to capture evidence for."""
    with get_connection() as conn, conn.cursor() as cur:
        if scope == "entry" and entry_ids:
            cur.execute(
                """
                SELECT id, project_id, entry_type, path, name, health_status, metadata
                FROM explorer_entries
                WHERE project_id = %s AND id = ANY(%s)
                """,
                (project_id, entry_ids),
            )
        else:
            # Get all capturable entries (pages and endpoints)
            cur.execute(
                """
                SELECT id, project_id, entry_type, path, name, health_status, metadata
                FROM explorer_entries
                WHERE project_id = %s AND entry_type IN ('page', 'endpoint')
                ORDER BY entry_type, path
                """,
                (project_id,),
            )

        return [
            {
                "id": row[0],
                "project_id": row[1],
                "entry_type": row[2],
                "path": row[3],
                "name": row[4],
                "health_status": row[5],
                "metadata": row[6] or {},
            }
            for row in cur.fetchall()
        ]


async def _store_evidence(
    project_id: str,
    explorer_entry_id: int | None,
    evidence_result: EvidenceResult,
    environment: str,
) -> int | None:
    """Store captured evidence in database."""
    with get_connection() as conn, conn.cursor() as cur:
        # Generate evidence ID
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        evidence_id = f"ev-{explorer_entry_id or 'manual'}-{timestamp}"

        cur.execute(
            """
            INSERT INTO evidence (
                project_id, evidence_id, explorer_entry_id,
                evidence_type, environment,
                file_path, file_size_bytes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                project_id,
                evidence_id,
                explorer_entry_id,
                evidence_result.evidence_type,
                environment,
                evidence_result.file_path,
                evidence_result.file_size_bytes,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        # Update denormalized count on explorer_entries
        if explorer_entry_id:
            cur.execute(
                """
                UPDATE explorer_entries
                SET evidence_count = evidence_count + 1,
                    last_evidence_at = NOW()
                WHERE id = %s
                """,
                (explorer_entry_id,),
            )
            conn.commit()

        return row[0] if row else None


def _get_auth_headers(project_id: str, environment: str) -> dict[str, str]:
    """Get authentication headers for a project/environment.

    TODO: Implement proper credential management.
    """
    # Placeholder - would fetch from secure storage
    return {}
