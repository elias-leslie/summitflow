#!/usr/bin/env python3
"""Data migration script for TDD Architecture Coherence.

Migrates: Task criteria JSONB to normalized tables, capability_tests to criterion_tests, evidence FK.
Usage: python scripts/migrate_tdd_architecture.py [--dry-run] [--rollback]
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Auto-detect and re-exec into the backend venv if needed
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import lib.ensure_backend_venv  # noqa: E402, F401

from app.storage.criteria import get_next_criterion_id

from app.storage.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class MigrationContext:
    """Track migration state and statistics."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stats = {
            "task_criteria_created": 0,
            "task_criteria_links": 0,
            "capability_criteria_created": 0,
            "criterion_tests_created": 0,
            "evidence_updated": 0,
            "errors": [],
        }

    def log_action(self, action: str, details: str):
        prefix = "[DRY-RUN]" if self.dry_run else "[EXECUTE]"
        logger.info(f"{prefix} {action}: {details}")

    def log_error(self, error: str):
        self.stats["errors"].append(error)
        logger.error(f"ERROR: {error}")


def backup_row(conn, table_name: str, row_id: str, data: dict):
    """Store original data for rollback."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO migration_backup (migration_name, table_name, row_id, original_data)
               VALUES ('tdd_architecture', %s, %s, %s)""",
            (table_name, row_id, json.dumps(data)),
        )


def create_criterion(conn, project_id: int, criterion_text: str,
                    category: str = "correctness", measurement: str = "test",
                    threshold: str | None = None, task_id: int | None = None) -> int:
    """Create acceptance_criteria row and return DB ID."""
    criterion_id = get_next_criterion_id(conn, project_id)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO acceptance_criteria
               (project_id, criterion_id, criterion, category, measurement, threshold, created_by_task_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (project_id, criterion_id, criterion_text, category, measurement, threshold, task_id),
        )
        return cur.fetchone()[0]


def create_backup_table(conn, ctx: MigrationContext):
    """Create backup table to store original state for rollback."""
    ctx.log_action("backup", "Creating migration_backup table")
    if ctx.dry_run:
        return

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS migration_backup (
                id SERIAL PRIMARY KEY, migration_name TEXT NOT NULL, table_name TEXT NOT NULL,
                row_id TEXT NOT NULL, original_data JSONB NOT NULL, migrated_at TIMESTAMPTZ DEFAULT NOW());
            CREATE INDEX IF NOT EXISTS idx_migration_backup_name ON migration_backup(migration_name);""")
        conn.commit()


def migrate_single_task_criterion(conn, ctx: MigrationContext, task_id: int, project_id: int, crit: dict):
    """Migrate a single task criterion."""
    criterion_text = crit.get("criterion", crit.get("description", ""))
    if not criterion_text:
        return

    criterion_db_id = create_criterion(conn, project_id, criterion_text, crit.get("category", "correctness"),
                                      crit.get("measurement", "test"), crit.get("threshold"), task_id)
    ctx.stats["task_criteria_created"] += 1

    with conn.cursor() as cur:
        cur.execute("INSERT INTO task_criteria (task_id, criterion_id, verified, verified_at, verified_by) VALUES (%s, %s, %s, %s, %s)",
                   (task_id, criterion_db_id, crit.get("verified", False), crit.get("verified_at"), crit.get("verified_by")))
    ctx.stats["task_criteria_links"] += 1


def migrate_task_criteria(conn, ctx: MigrationContext):
    """Migrate tasks.acceptance_criteria JSONB to normalized tables."""
    logger.info("\n=== Migrating Task Criteria ===")

    with conn.cursor() as cur:
        cur.execute("SELECT id, project_id, acceptance_criteria FROM tasks WHERE acceptance_criteria IS NOT NULL AND acceptance_criteria::text NOT IN ('null', '[]', '{}')")
        tasks_with_criteria = cur.fetchall()

    logger.info(f"Found {len(tasks_with_criteria)} tasks with JSONB criteria")
    if not tasks_with_criteria:
        return

    for task_id, project_id, criteria_jsonb in tasks_with_criteria:
        criteria_list = criteria_jsonb if isinstance(criteria_jsonb, list) else []
        if not criteria_list:
            continue

        ctx.log_action("migrate_task", f"Task {task_id}: {len(criteria_list)} criteria")

        if ctx.dry_run:
            ctx.stats["task_criteria_created"] += len(criteria_list)
            ctx.stats["task_criteria_links"] += len(criteria_list)
            continue

        backup_row(conn, "tasks", task_id, {"acceptance_criteria": criteria_jsonb})
        for crit in criteria_list:
            migrate_single_task_criterion(conn, ctx, task_id, project_id, crit)
        conn.commit()

    logger.info(f"Task criteria: {ctx.stats['task_criteria_created']} created, {ctx.stats['task_criteria_links']} links")


def migrate_capability_tests(conn, ctx: MigrationContext):
    """Migrate capability_tests to criterion_tests via auto-generated criteria."""
    logger.info("\n=== Migrating Capability Tests ===")

    with conn.cursor() as cur:
        cur.execute("SELECT ct.capability_id, ct.test_id, ct.is_primary, c.project_id, c.capability_id as cap_str_id, t.name as test_name FROM capability_tests ct JOIN capabilities c ON ct.capability_id = c.id JOIN tests t ON ct.test_id = t.id ORDER BY c.project_id, c.capability_id, t.name")
        capability_tests = cur.fetchall()

    logger.info(f"Found {len(capability_tests)} capability_tests rows")
    if not capability_tests:
        return

    created_criteria: dict[tuple[int, int], int] = {}

    for cap_db_id, test_db_id, is_primary, project_id, cap_str_id, test_name in capability_tests:
        key = (cap_db_id, test_db_id)
        if key in created_criteria:
            continue

        ctx.log_action("migrate_cap_test", f"Capability {cap_str_id} -> Test: {test_name[:50]}...")

        if ctx.dry_run:
            ctx.stats["capability_criteria_created"] += 1
            ctx.stats["criterion_tests_created"] += 1
            continue

        backup_row(conn, "capability_tests", f"{cap_db_id}:{test_db_id}",
                  {"capability_id": cap_db_id, "test_id": test_db_id, "is_primary": is_primary})

        criterion_db_id = create_criterion(conn, project_id, f"Test passes: {test_name}")
        ctx.stats["capability_criteria_created"] += 1

        with conn.cursor() as cur:
            cur.execute("INSERT INTO capability_criteria (capability_id, criterion_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cap_db_id, criterion_db_id))
            cur.execute("INSERT INTO criterion_tests (criterion_id, test_id, is_primary) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (criterion_db_id, test_db_id, is_primary))
        ctx.stats["criterion_tests_created"] += 1
        created_criteria[key] = criterion_db_id
        conn.commit()

    logger.info(f"Capability tests: {ctx.stats['capability_criteria_created']} criteria, {ctx.stats['criterion_tests_created']} links")


def migrate_evidence(conn, ctx: MigrationContext):
    """Migrate evidence TEXT criterion_id to INTEGER criterion_db_id FK."""
    logger.info("\n=== Migrating Evidence ===")

    with conn.cursor() as cur:
        cur.execute("SELECT id, project_id, capability_id, criterion_id FROM evidence WHERE criterion_id IS NOT NULL AND criterion_id != '' AND criterion_db_id IS NULL")
        evidence_to_migrate = cur.fetchall()

    logger.info(f"Found {len(evidence_to_migrate)} evidence rows")
    if not evidence_to_migrate:
        return

    for ev_id, project_id, cap_id, crit_id in evidence_to_migrate:
        ctx.log_action("migrate_evidence", f"Evidence {ev_id}: capability={cap_id}, criterion={crit_id}")

        if ctx.dry_run:
            ctx.stats["evidence_updated"] += 1
            continue

        backup_row(conn, "evidence", str(ev_id), {"capability_id": cap_id, "criterion_id": crit_id})

        with conn.cursor() as cur:
            cur.execute("SELECT id FROM acceptance_criteria WHERE project_id = %s AND criterion_id = %s", (project_id, crit_id))
            row = cur.fetchone()

            if row:
                cur.execute("UPDATE evidence SET criterion_db_id = %s WHERE id = %s", (row[0], ev_id))
                ctx.stats["evidence_updated"] += 1
                conn.commit()
            else:
                ctx.log_error(f"No criterion for evidence {ev_id}: project={project_id}, criterion_id={crit_id}")

    logger.info(f"Evidence: {ctx.stats['evidence_updated']} rows updated")


def rollback(conn, migration_name: str = "tdd_architecture"):
    """Rollback migration using backup data."""
    logger.warning("\n=== ROLLBACK MODE ===")

    with conn.cursor() as cur:
        cur.execute("SELECT table_name, row_id, original_data FROM migration_backup WHERE migration_name = %s ORDER BY id DESC", (migration_name,))
        backups = cur.fetchall()

    if not backups:
        logger.error("No backup data found")
        return False

    logger.info(f"Found {len(backups)} backup records")

    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ac.id FROM acceptance_criteria ac WHERE ac.criterion LIKE 'Test passes:%' OR ac.created_by_task_id IS NOT NULL")
        migrated_criteria = [r[0] for r in cur.fetchall()]

        if migrated_criteria:
            cur.execute("DELETE FROM criterion_tests WHERE criterion_id = ANY(%s)", (migrated_criteria,))
            cur.execute("DELETE FROM capability_criteria WHERE criterion_id = ANY(%s)", (migrated_criteria,))
            cur.execute("DELETE FROM task_criteria WHERE criterion_id = ANY(%s)", (migrated_criteria,))
            cur.execute("DELETE FROM acceptance_criteria WHERE id = ANY(%s)", (migrated_criteria,))
            logger.info(f"Deleted {len(migrated_criteria)} migrated criteria")

        cur.execute("UPDATE evidence SET criterion_db_id = NULL WHERE id IN (SELECT row_id::integer FROM migration_backup WHERE migration_name = %s AND table_name = 'evidence')", (migration_name,))
        cur.execute("DELETE FROM migration_backup WHERE migration_name = %s", (migration_name,))
        conn.commit()

    logger.info("Rollback completed")
    return True


def print_summary(ctx: MigrationContext):
    """Print migration summary."""
    logger.info("\n" + "=" * 60)
    logger.info(f"MIGRATION SUMMARY - {'DRY RUN' if ctx.dry_run else 'EXECUTED'}")
    logger.info("=" * 60)
    logger.info(f"Task Criteria: {ctx.stats['task_criteria_created']} created, {ctx.stats['task_criteria_links']} links")
    logger.info(f"Capability Tests: {ctx.stats['capability_criteria_created']} criteria, {ctx.stats['criterion_tests_created']} links")
    logger.info(f"Evidence: {ctx.stats['evidence_updated']} updated")

    if ctx.stats["errors"]:
        logger.warning(f"\nErrors ({len(ctx.stats['errors'])}):")
        for error in ctx.stats["errors"]:
            logger.warning(f"  - {error}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="TDD Architecture Migration")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--rollback", action="store_true", help="Rollback previous migration")
    args = parser.parse_args()

    logger.info(f"TDD Architecture Migration - {datetime.now(UTC).isoformat()}")

    with get_connection() as conn:
        if args.rollback:
            sys.exit(0 if rollback(conn) else 1)

        ctx = MigrationContext(dry_run=args.dry_run)
        create_backup_table(conn, ctx)
        migrate_task_criteria(conn, ctx)
        migrate_capability_tests(conn, ctx)
        migrate_evidence(conn, ctx)
        print_summary(ctx)

        if ctx.stats["errors"]:
            logger.error("Migration completed with errors")
            sys.exit(1)

        logger.info("\nTo execute migration, run without --dry-run flag" if ctx.dry_run else "\nMigration completed successfully")


if __name__ == "__main__":
    main()
