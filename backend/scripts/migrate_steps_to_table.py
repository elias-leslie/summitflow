#!/usr/bin/env python3
"""Migrate steps from task_subtasks.steps JSONB to task_subtask_steps table.

Usage:
    python migrate_steps_to_table.py --dry-run   # Preview without changes
    python migrate_steps_to_table.py             # Execute migration
"""

import argparse
import sys
from pathlib import Path

# Add backend to path for imports
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.storage.connection import get_connection
from app.storage.steps import bulk_create_steps


def get_subtasks_with_steps() -> list[dict]:
    """Get all subtasks that have non-empty steps JSONB array."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, task_id, subtask_id, steps
            FROM task_subtasks
            WHERE steps IS NOT NULL AND steps <> '[]'::jsonb
            ORDER BY task_id, subtask_id
        """)
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "task_id": row[1],
            "subtask_id": row[2],
            "steps": row[3],  # Already parsed as list by psycopg
        }
        for row in rows
    ]


def check_existing_steps(subtask_table_id: str) -> int:
    """Count existing steps in the table for a subtask."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM task_subtask_steps WHERE subtask_id = %s",
            (subtask_table_id,),
        )
        row = cur.fetchone()
        return row[0] if row else 0


def migrate_subtask_steps(subtask: dict, dry_run: bool = True) -> dict:
    """Migrate steps for a single subtask.

    Returns:
        Dict with migration status
    """
    subtask_table_id = subtask["id"]
    steps = subtask["steps"]

    if not steps or not isinstance(steps, list):
        return {"id": subtask_table_id, "skipped": True, "reason": "No valid steps"}

    # Filter to string steps only
    step_descriptions = [s for s in steps if isinstance(s, str) and s.strip()]
    if not step_descriptions:
        return {"id": subtask_table_id, "skipped": True, "reason": "No string steps"}

    # Check if already migrated
    existing_count = check_existing_steps(subtask_table_id)
    if existing_count > 0:
        return {
            "id": subtask_table_id,
            "skipped": True,
            "reason": f"Already has {existing_count} steps in table",
        }

    if dry_run:
        return {
            "id": subtask_table_id,
            "dry_run": True,
            "steps_count": len(step_descriptions),
            "steps": step_descriptions[:3],  # Preview first 3
        }

    # Actually create the steps
    try:
        created = bulk_create_steps(subtask_table_id, step_descriptions)
        return {
            "id": subtask_table_id,
            "success": True,
            "steps_created": len(created),
        }
    except Exception as e:
        return {
            "id": subtask_table_id,
            "error": True,
            "message": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="Migrate steps from JSONB to table")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing steps before migrating (use with caution)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Steps Migration: JSONB → Table")
    print("=" * 60)

    # Get subtasks with steps
    subtasks = get_subtasks_with_steps()
    print(f"\nFound {len(subtasks)} subtasks with steps to migrate")

    if not subtasks:
        print("Nothing to migrate!")
        return

    # Migration stats
    stats = {
        "total": len(subtasks),
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
        "total_steps": 0,
    }

    for subtask in subtasks:
        result = migrate_subtask_steps(subtask, dry_run=args.dry_run)

        if result.get("skipped"):
            stats["skipped"] += 1
            if args.dry_run:
                print(f"  [SKIP] {result['id']}: {result['reason']}")
        elif result.get("error"):
            stats["errors"] += 1
            print(f"  [ERROR] {result['id']}: {result['message']}")
        elif result.get("dry_run"):
            stats["migrated"] += 1
            stats["total_steps"] += result["steps_count"]
            print(
                f"  [DRY] {result['id']}: {result['steps_count']} steps - {result['steps'][:1]}..."
            )
        elif result.get("success"):
            stats["migrated"] += 1
            stats["total_steps"] += result["steps_created"]
            print(f"  [OK] {result['id']}: {result['steps_created']} steps created")

    # Summary
    print("\n" + "=" * 60)
    print("Migration Summary:")
    print("=" * 60)
    print(f"  Total subtasks: {stats['total']}")
    print(f"  Migrated: {stats['migrated']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Total steps: {stats['total_steps']}")

    if args.dry_run:
        print("\n[DRY RUN] No changes made. Run without --dry-run to execute.")


if __name__ == "__main__":
    main()
