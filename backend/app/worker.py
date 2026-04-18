"""Hatchet worker entrypoint.

Registers all workflows and starts the worker process.
Run with: python -m app.worker
"""

from __future__ import annotations

from app.hatchet_app import hatchet
from app.workflows.pipeline import (
    dispatch_wf,
    escalation_wf,
    execute_wf,
    ideate_wf,
    merge_cleanup_wf,
    plan_wf,
    review_wf,
    triage_wf,
)
from app.workflows.scheduled import (
    health_monitor_wf,
    pending_drain_wf,
    prod_smoke_test_wf,
    refresh_precision_indexes_wf,
    reset_claims_wf,
    restore_tests_wf,
    scan_projects_wf,
    scheduled_backups_wf,
    self_healing_wf,
    stale_cleanup_wf,
    task_generation_wf,
    work_pickup_wf,
)
from app.workflows.utility import (
    arch_tasks_wf,
    backup_create_wf,
    backup_restore_wf,
    check_resolved_wf,
    checkpoint_cleanup_wf,
    enrich_wf,
    page_health_wf,
    pr_review_wf,
    refactor_regen_wf,
    schema_tasks_wf,
)


def main() -> None:
    worker = hatchet.worker(
        "summitflow-worker",
        workflows=[
            # Pipeline (8)
            dispatch_wf,
            ideate_wf,
            triage_wf,
            plan_wf,
            execute_wf,
            review_wf,
            merge_cleanup_wf,
            escalation_wf,
            # Scheduled (12)
            work_pickup_wf,
            reset_claims_wf,
            scan_projects_wf,
            refresh_precision_indexes_wf,
            scheduled_backups_wf,
            stale_cleanup_wf,
            task_generation_wf,
            self_healing_wf,
            prod_smoke_test_wf,
            health_monitor_wf,
            pending_drain_wf,
            restore_tests_wf,
            # Utility (10)
            backup_create_wf,
            backup_restore_wf,
            enrich_wf,
            pr_review_wf,
            checkpoint_cleanup_wf,
            refactor_regen_wf,
            schema_tasks_wf,
            arch_tasks_wf,
            check_resolved_wf,
            page_health_wf,
        ],
    )
    worker.start()


if __name__ == "__main__":
    main()
