"""Hatchet worker entrypoint.

Registers all workflows and starts the worker process.
Run with: python -m app.worker
"""

from __future__ import annotations

from typing import Any

from app.hatchet_app import hatchet
from app.workflows.automation_dispatch import (
    automation_outbox_reconcile_wf,
    automation_owner_run_wf,
)
from app.workflows.scheduled import (
    dependency_reviews_wf,
    hatchet_retention_wf,
    health_monitor_wf,
    nightly_deep_lane_wf,
    nightly_publication_wf,
    pending_drain_wf,
    prod_smoke_test_wf,
    refresh_graphify_graphs_wf,
    refresh_precision_indexes_wf,
    reset_claims_wf,
    restore_tests_wf,
    runtime_hygiene_wf,
    scan_projects_wf,
    scheduled_backups_wf,
    stale_cleanup_wf,
)
from app.workflows.utility import (
    backup_create_wf,
    backup_offsite_sync_wf,
    backup_restore_wf,
    check_resolved_wf,
    page_health_wf,
)


def _registered_workflows() -> list[Any]:
    """Return every workflow explicitly served by this SummitFlow worker."""
    return [
        # Agent Hub automation tasks
        automation_owner_run_wf,
        automation_outbox_reconcile_wf,
        # Scheduled
        reset_claims_wf,
        scan_projects_wf,
        dependency_reviews_wf,
        refresh_precision_indexes_wf,
        refresh_graphify_graphs_wf,
        scheduled_backups_wf,
        stale_cleanup_wf,
        hatchet_retention_wf,
        prod_smoke_test_wf,
        health_monitor_wf,
        pending_drain_wf,
        restore_tests_wf,
        runtime_hygiene_wf,
        nightly_publication_wf,
        nightly_deep_lane_wf,
        # Utility
        backup_create_wf,
        backup_offsite_sync_wf,
        backup_restore_wf,
        check_resolved_wf,
        page_health_wf,
    ]


def main() -> None:
    worker = hatchet.worker(
        "summitflow-worker",
        workflows=_registered_workflows(),
    )
    worker.start()


if __name__ == "__main__":
    main()
