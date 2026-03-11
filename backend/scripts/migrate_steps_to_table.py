#!/usr/bin/env python3
"""Migrate steps from task_subtasks.steps JSONB to task_subtask_steps table.

Usage:
    python migrate_steps_to_table.py --dry-run   # Preview without changes
    python migrate_steps_to_table.py             # Execute migration
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Auto-detect and re-exec into the backend venv if needed
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import lib.ensure_backend_venv  # noqa: F401

from app.storage.connection import get_connection
from app.storage.steps import bulk_create_steps


def get_subtasks_with_steps() -> list[dict[str, Any]]:
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


def migrate_subtask_steps(subtask: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
    """Migrate steps for a single subtask. Returns a dict with migration status."""
    sid = subtask["id"]
    steps = subtask["steps"]

    if not steps or not isinstance(steps, list):
        return {"id": sid, "skipped": True, "reason": "No valid steps"}

    step_descriptions = [s for s in steps if isinstance(s, str) and s.strip()]
    if not step_descriptions:
        return {"id": sid, "skipped": True, "reason": "No string steps"}

    existing_count = check_existing_steps(sid)
    if existing_count > 0:
        return {"id": sid, "skipped": True, "reason": f"Already has {existing_count} steps in table"}

    if dry_run:
        return {"id": sid, "dry_run": True, "steps_count": len(step_descriptions), "steps": step_descriptions[:3]}

    try:
        created = bulk_create_steps(sid, step_descriptions)
        return {"id": sid, "success": True, "steps_created": len(created)}
    except Exception as e:
        return {"id": sid, "error": True, "message": str(e)}


def _handle_skipped(result: dict[str, Any], stats: dict[str, int], dry_run: bool) -> None:
    stats["skipped"] += 1
    if dry_run:
        print(f"  [SKIP] {result['id']}: {result['reason']}")


def _handle_error(result: dict[str, Any], stats: dict[str, int]) -> None:
    stats["errors"] += 1
    print(f"  [ERROR] {result['id']}: {result['message']}")


def _handle_dry_run(result: dict[str, Any], stats: dict[str, int]) -> None:
    stats["migrated"] += 1
    stats["total_steps"] += result["steps_count"]
    print(f"  [DRY] {result['id']}: {result['steps_count']} steps - {result['steps'][:1]}...")


def _handle_success(result: dict[str, Any], stats: dict[str, int]) -> None:
    stats["migrated"] += 1
    stats["total_steps"] += result["steps_created"]
    print(f"  [OK] {result['id']}: {result['steps_created']} steps created")


def _accumulate_result(result: dict[str, Any], stats: dict[str, int], dry_run: bool) -> None:
    """Update stats and print a line for a single migration result."""
    if result.get("skipped"):
        _handle_skipped(result, stats, dry_run)
        return
    if result.get("error"):
        _handle_error(result, stats)
        return
    if result.get("dry_run"):
        _handle_dry_run(result, stats)
        return
    if result.get("success"):
        _handle_success(result, stats)


def _print_summary(stats: dict[str, int], dry_run: bool) -> None:
    """Print the migration summary block."""
    print("\n" + "=" * 60)
    print("Migration Summary:")
    print("=" * 60)
    print(f"  Total subtasks: {stats['total']}")
    print(f"  Migrated: {stats['migrated']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Total steps: {stats['total_steps']}")
    if dry_run:
        print("\n[DRY RUN] No changes made. Run without --dry-run to execute.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate steps from JSONB to table")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without making changes")
    parser.add_argument("--clear-existing", action="store_true", help="Clear existing steps before migrating (use with caution)")
    args = parser.parse_args()

    print("=" * 60)
    print("Steps Migration: JSONB → Table")
    print("=" * 60)

    subtasks = get_subtasks_with_steps()
    print(f"\nFound {len(subtasks)} subtasks with steps to migrate")

    if not subtasks:
        print("Nothing to migrate!")
        return

    stats = {"total": len(subtasks), "migrated": 0, "skipped": 0, "errors": 0, "total_steps": 0}

    for subtask in subtasks:
        result = migrate_subtask_steps(subtask, dry_run=args.dry_run)
        _accumulate_result(result, stats, dry_run=args.dry_run)

    _print_summary(stats, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
