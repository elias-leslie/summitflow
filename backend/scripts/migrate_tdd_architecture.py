#!/usr/bin/env python3
"""Data migration script for TDD Architecture Coherence.

Migrates:
1. Task acceptance_criteria JSONB → acceptance_criteria + task_criteria tables
2. capability_tests → criterion_tests (via auto-generated criteria)
3. Evidence TEXT criterion_id → INTEGER criterion_db_id FK

Usage:
    python scripts/migrate_tdd_architecture.py --dry-run  # Preview changes
    python scripts/migrate_tdd_architecture.py            # Execute migration
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.connection import get_connection
from app.storage.criteria import get_next_criterion_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
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


def create_backup_table(conn, ctx: MigrationContext):
    """Create backup table to store original state for rollback."""
    ctx.log_action("backup", "Creating migration_backup table")

    if ctx.dry_run:
        return

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS migration_backup (
                id SERIAL PRIMARY KEY,
                migration_name TEXT NOT NULL,
                table_name TEXT NOT NULL,
                row_id TEXT NOT NULL,
                original_data JSONB NOT NULL,
                migrated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_migration_backup_name
                ON migration_backup(migration_name);
        """)
        conn.commit()

    logger.info("Backup table created/verified")


def migrate_task_criteria(conn, ctx: MigrationContext):
    """Migrate tasks.acceptance_criteria JSONB to normalized tables.

    For each task with acceptance_criteria JSONB:
    1. Create acceptance_criteria rows
    2. Create task_criteria junction rows
    3. Backup original JSONB
    """
    logger.info("\n=== Migrating Task Criteria ===")

    with conn.cursor() as cur:
        # Find tasks with actual JSONB criteria
        cur.execute("""
            SELECT id, project_id, acceptance_criteria
            FROM tasks
            WHERE acceptance_criteria IS NOT NULL
              AND acceptance_criteria::text NOT IN ('null', '[]', '{}')
        """)
        tasks_with_criteria = cur.fetchall()

    logger.info(f"Found {len(tasks_with_criteria)} tasks with JSONB criteria")

    if not tasks_with_criteria:
        logger.info("No task criteria to migrate")
        return

    for task_id, project_id, criteria_jsonb in tasks_with_criteria:
        if not criteria_jsonb:
            continue

        criteria_list = criteria_jsonb if isinstance(criteria_jsonb, list) else []
        if not criteria_list:
            continue

        ctx.log_action(
            "migrate_task",
            f"Task {task_id}: {len(criteria_list)} criteria",
        )

        if ctx.dry_run:
            ctx.stats["task_criteria_created"] += len(criteria_list)
            ctx.stats["task_criteria_links"] += len(criteria_list)
            continue

        # Backup original data
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO migration_backup
                    (migration_name, table_name, row_id, original_data)
                VALUES ('tdd_architecture', 'tasks', %s, %s)
                """,
                (task_id, json.dumps({"acceptance_criteria": criteria_jsonb})),
            )

        # Migrate each criterion
        for crit in criteria_list:
            criterion_text = crit.get("criterion", crit.get("description", ""))
            if not criterion_text:
                continue

            criterion_id = get_next_criterion_id(conn, project_id)

            with conn.cursor() as cur:
                # Create acceptance_criteria row
                cur.execute(
                    """
                    INSERT INTO acceptance_criteria
                        (project_id, criterion_id, criterion, category,
                         measurement, threshold, created_by_task_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        project_id,
                        criterion_id,
                        criterion_text,
                        crit.get("category", "correctness"),
                        crit.get("measurement", "test"),
                        crit.get("threshold"),
                        task_id,
                    ),
                )
                criterion_db_id = cur.fetchone()[0]
                ctx.stats["task_criteria_created"] += 1

                # Create task_criteria junction
                cur.execute(
                    """
                    INSERT INTO task_criteria
                        (task_id, criterion_id, verified, verified_at, verified_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        task_id,
                        criterion_db_id,
                        crit.get("verified", False),
                        crit.get("verified_at"),
                        crit.get("verified_by"),
                    ),
                )
                ctx.stats["task_criteria_links"] += 1

        conn.commit()

    logger.info(
        f"Task criteria migration: {ctx.stats['task_criteria_created']} criteria created, "
        f"{ctx.stats['task_criteria_links']} links created"
    )


def migrate_capability_tests(conn, ctx: MigrationContext):
    """Migrate capability_tests to criterion_tests via auto-generated criteria.

    For each capability_tests row:
    1. Create acceptance_criteria row: "Test: {test_name}"
    2. Link criterion to capability via capability_criteria
    3. Link test to criterion via criterion_tests
    """
    logger.info("\n=== Migrating Capability Tests ===")

    with conn.cursor() as cur:
        # Get all capability_tests with capability and test info
        cur.execute("""
            SELECT ct.capability_id, ct.test_id, ct.is_primary,
                   c.project_id, c.capability_id as cap_str_id,
                   t.name as test_name
            FROM capability_tests ct
            JOIN capabilities c ON ct.capability_id = c.id
            JOIN tests t ON ct.test_id = t.id
            ORDER BY c.project_id, c.capability_id, t.name
        """)
        capability_tests = cur.fetchall()

    logger.info(f"Found {len(capability_tests)} capability_tests rows to migrate")

    if not capability_tests:
        logger.info("No capability_tests to migrate")
        return

    # Track which criteria we've created per capability to avoid duplicates
    created_criteria: dict[tuple[int, int], int] = {}  # (cap_id, test_id) -> criterion_db_id

    for cap_db_id, test_db_id, is_primary, project_id, cap_str_id, test_name in capability_tests:
        # Check if already migrated (idempotent)
        key = (cap_db_id, test_db_id)
        if key in created_criteria:
            continue

        ctx.log_action(
            "migrate_cap_test",
            f"Capability {cap_str_id} -> Test: {test_name[:50]}...",
        )

        if ctx.dry_run:
            ctx.stats["capability_criteria_created"] += 1
            ctx.stats["criterion_tests_created"] += 1
            continue

        # Backup original data
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO migration_backup
                    (migration_name, table_name, row_id, original_data)
                VALUES ('tdd_architecture', 'capability_tests', %s, %s)
                """,
                (
                    f"{cap_db_id}:{test_db_id}",
                    json.dumps(
                        {
                            "capability_id": cap_db_id,
                            "test_id": test_db_id,
                            "is_primary": is_primary,
                        }
                    ),
                ),
            )

        # Create criterion for this test
        criterion_id = get_next_criterion_id(conn, project_id)
        criterion_text = f"Test passes: {test_name}"

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO acceptance_criteria
                    (project_id, criterion_id, criterion, category, measurement)
                VALUES (%s, %s, %s, 'correctness', 'test')
                RETURNING id
                """,
                (project_id, criterion_id, criterion_text),
            )
            criterion_db_id = cur.fetchone()[0]
            ctx.stats["capability_criteria_created"] += 1

            # Link criterion to capability
            cur.execute(
                """
                INSERT INTO capability_criteria (capability_id, criterion_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (cap_db_id, criterion_db_id),
            )

            # Link test to criterion
            cur.execute(
                """
                INSERT INTO criterion_tests (criterion_id, test_id, is_primary)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (criterion_db_id, test_db_id, is_primary),
            )
            ctx.stats["criterion_tests_created"] += 1

        created_criteria[key] = criterion_db_id
        conn.commit()

    logger.info(
        f"Capability tests migration: {ctx.stats['capability_criteria_created']} criteria created, "
        f"{ctx.stats['criterion_tests_created']} criterion_tests links created"
    )


def migrate_evidence(conn, ctx: MigrationContext):
    """Migrate evidence TEXT criterion_id to INTEGER criterion_db_id FK.

    For evidence with TEXT capability_id + criterion_id:
    1. Lookup matching acceptance_criteria row
    2. Set criterion_db_id FK
    """
    logger.info("\n=== Migrating Evidence ===")

    with conn.cursor() as cur:
        # Find evidence with TEXT criterion_id but no criterion_db_id
        cur.execute("""
            SELECT id, project_id, capability_id, criterion_id
            FROM evidence
            WHERE criterion_id IS NOT NULL
              AND criterion_id != ''
              AND criterion_db_id IS NULL
        """)
        evidence_to_migrate = cur.fetchall()

    logger.info(f"Found {len(evidence_to_migrate)} evidence rows to migrate")

    if not evidence_to_migrate:
        logger.info("No evidence to migrate")
        return

    for ev_id, project_id, cap_id, crit_id in evidence_to_migrate:
        ctx.log_action(
            "migrate_evidence",
            f"Evidence {ev_id}: capability={cap_id}, criterion={crit_id}",
        )

        if ctx.dry_run:
            ctx.stats["evidence_updated"] += 1
            continue

        # Backup original data
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO migration_backup
                    (migration_name, table_name, row_id, original_data)
                VALUES ('tdd_architecture', 'evidence', %s, %s)
                """,
                (
                    str(ev_id),
                    json.dumps(
                        {
                            "capability_id": cap_id,
                            "criterion_id": crit_id,
                        }
                    ),
                ),
            )

        # Try to find matching criterion
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM acceptance_criteria
                WHERE project_id = %s AND criterion_id = %s
                """,
                (project_id, crit_id),
            )
            row = cur.fetchone()

            if row:
                cur.execute(
                    "UPDATE evidence SET criterion_db_id = %s WHERE id = %s",
                    (row[0], ev_id),
                )
                ctx.stats["evidence_updated"] += 1
                conn.commit()
            else:
                ctx.log_error(
                    f"No matching criterion found for evidence {ev_id}: "
                    f"project={project_id}, criterion_id={crit_id}"
                )

    logger.info(f"Evidence migration: {ctx.stats['evidence_updated']} rows updated")


def rollback(conn, migration_name: str = "tdd_architecture"):
    """Rollback migration using backup data.

    Note: This is a best-effort rollback. After schema changes in Phase 7.3,
    full rollback requires restoring from pg_dump backup.
    """
    logger.warning("\n=== ROLLBACK MODE ===")
    logger.warning("This will attempt to restore original state from backup table")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, row_id, original_data
            FROM migration_backup
            WHERE migration_name = %s
            ORDER BY id DESC
            """,
            (migration_name,),
        )
        backups = cur.fetchall()

    if not backups:
        logger.error("No backup data found for rollback")
        return False

    logger.info(f"Found {len(backups)} backup records")

    # Delete migrated data (criterion_tests, capability_criteria, task_criteria created by migration)
    with conn.cursor() as cur:
        # Get criterion IDs created by migration
        cur.execute("""
            SELECT DISTINCT ac.id
            FROM acceptance_criteria ac
            WHERE ac.criterion LIKE 'Test passes:%'
               OR ac.created_by_task_id IS NOT NULL
        """)
        migrated_criteria = [r[0] for r in cur.fetchall()]

        if migrated_criteria:
            # Delete in correct order for FK constraints
            cur.execute(
                "DELETE FROM criterion_tests WHERE criterion_id = ANY(%s)",
                (migrated_criteria,),
            )
            cur.execute(
                "DELETE FROM capability_criteria WHERE criterion_id = ANY(%s)",
                (migrated_criteria,),
            )
            cur.execute(
                "DELETE FROM task_criteria WHERE criterion_id = ANY(%s)",
                (migrated_criteria,),
            )
            cur.execute(
                "DELETE FROM acceptance_criteria WHERE id = ANY(%s)",
                (migrated_criteria,),
            )
            logger.info(f"Deleted {len(migrated_criteria)} migrated criteria and their links")

        # Reset evidence criterion_db_id
        cur.execute(
            """
            UPDATE evidence SET criterion_db_id = NULL
            WHERE id IN (
                SELECT row_id::integer FROM migration_backup
                WHERE migration_name = %s AND table_name = 'evidence'
            )
            """,
            (migration_name,),
        )

        # Clean up backup table
        cur.execute(
            "DELETE FROM migration_backup WHERE migration_name = %s",
            (migration_name,),
        )

        conn.commit()

    logger.info("Rollback completed")
    return True


def print_summary(ctx: MigrationContext):
    """Print migration summary."""
    logger.info("\n" + "=" * 60)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 60)

    if ctx.dry_run:
        logger.info("MODE: DRY RUN (no changes made)")
    else:
        logger.info("MODE: EXECUTED")

    logger.info("\nTask Criteria:")
    logger.info(f"  - Criteria created: {ctx.stats['task_criteria_created']}")
    logger.info(f"  - Task links created: {ctx.stats['task_criteria_links']}")

    logger.info("\nCapability Tests:")
    logger.info(f"  - Criteria created: {ctx.stats['capability_criteria_created']}")
    logger.info(f"  - Criterion-test links: {ctx.stats['criterion_tests_created']}")

    logger.info("\nEvidence:")
    logger.info(f"  - Rows updated: {ctx.stats['evidence_updated']}")

    if ctx.stats["errors"]:
        logger.warning(f"\nErrors ({len(ctx.stats['errors'])}):")
        for error in ctx.stats["errors"]:
            logger.warning(f"  - {error}")

    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="TDD Architecture Migration")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback previous migration",
    )
    args = parser.parse_args()

    logger.info("TDD Architecture Migration")
    logger.info(f"Timestamp: {datetime.now(UTC).isoformat()}")

    with get_connection() as conn:
        if args.rollback:
            success = rollback(conn)
            sys.exit(0 if success else 1)

        ctx = MigrationContext(dry_run=args.dry_run)

        # Create backup table first
        create_backup_table(conn, ctx)

        # Run migrations
        migrate_task_criteria(conn, ctx)
        migrate_capability_tests(conn, ctx)
        migrate_evidence(conn, ctx)

        print_summary(ctx)

        if ctx.stats["errors"]:
            logger.error("Migration completed with errors")
            sys.exit(1)

        if ctx.dry_run:
            logger.info("\nTo execute migration, run without --dry-run flag")
        else:
            logger.info("\nMigration completed successfully")


if __name__ == "__main__":
    main()
