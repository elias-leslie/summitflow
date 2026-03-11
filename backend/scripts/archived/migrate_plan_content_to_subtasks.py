#!/usr/bin/env python3
"""Migrate task plan_content.tasks[] to normalized task_subtasks table.

This script extracts subtasks from the legacy plan_content JSONB column
and inserts them into the task_subtasks table for better query performance
and API access.

Usage:
    python migrate_plan_content_to_subtasks.py --dry-run  # Preview changes
    python migrate_plan_content_to_subtasks.py            # Execute migration

"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Auto-detect and re-exec into the backend venv if needed
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import lib.ensure_backend_venv  # noqa: E402, F401

from app.storage.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_tasks_with_plan_content() -> list[dict]:
    """Fetch all tasks that have plan_content with tasks array."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, plan_content
            FROM tasks
            WHERE plan_content IS NOT NULL
              AND plan_content->'tasks' IS NOT NULL
              AND jsonb_array_length(plan_content->'tasks') > 0
            ORDER BY created_at
            """
        )
        rows = cur.fetchall()

    tasks = []
    for row in rows:
        tasks.append(
            {
                "id": row[0],
                "title": row[1],
                "plan_content": row[2],
            }
        )
    return tasks


def check_existing_subtasks(task_id: str) -> int:
    """Check if task already has subtasks in task_subtasks table."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM task_subtasks WHERE task_id = %s",
            (task_id,),
        )
        row = cur.fetchone()
        return row[0] if row else 0


def extract_subtasks_from_plan(task_id: str, plan_content: dict) -> list[dict]:
    """Extract subtask data from plan_content.tasks array.

    Each subtask in plan_content has:
        - id: str (e.g., "1.1", "2.3")
        - description: str
        - steps: list[str]
        - passes: bool
        - category: str (optional, maps to phase)
    """
    tasks_data = plan_content.get("tasks", [])
    subtasks = []

    for idx, task_data in enumerate(tasks_data):
        subtask_id = task_data.get("id", str(idx + 1))
        description = task_data.get("description", "")
        steps = task_data.get("steps", [])
        passes = task_data.get("passes", False)
        category = task_data.get("category")  # Maps to phase

        subtasks.append(
            {
                "task_id": task_id,
                "subtask_id": subtask_id,
                "description": description,
                "steps": steps,
                "passes": passes,
                "phase": category,
                "display_order": idx,
            }
        )

    return subtasks


def migrate_subtasks(subtasks: list[dict], dry_run: bool = True) -> int:
    """Insert subtasks into task_subtasks table.

    Returns:
        Number of subtasks migrated.
    """
    if dry_run or not subtasks:
        return len(subtasks)

    with get_connection() as conn, conn.cursor() as cur:
        for subtask in subtasks:
            table_id = f"{subtask['task_id']}-{subtask['subtask_id']}"

            cur.execute(
                """
                INSERT INTO task_subtasks (
                    id, task_id, subtask_id, phase, description,
                    steps, passes, display_order
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (task_id, subtask_id) DO NOTHING
                """,
                (
                    table_id,
                    subtask["task_id"],
                    subtask["subtask_id"],
                    subtask["phase"],
                    subtask["description"],
                    json.dumps(subtask["steps"]),
                    subtask["passes"],
                    subtask["display_order"],
                ),
            )
        conn.commit()

    return len(subtasks)


def run_migration(dry_run: bool = True) -> dict:
    """Run the full migration.

    Returns:
        Summary dict with counts.
    """
    tasks = get_tasks_with_plan_content()
    logger.info("Found %d tasks with plan_content.tasks[]", len(tasks))

    summary = {
        "tasks_found": len(tasks),
        "tasks_migrated": 0,
        "tasks_skipped": 0,
        "subtasks_migrated": 0,
        "dry_run": dry_run,
        "details": [],
    }

    for task in tasks:
        task_id = task["id"]
        title = task["title"]

        # Check if already migrated
        existing_count = check_existing_subtasks(task_id)
        if existing_count > 0:
            logger.info("Skipping %s: already has %d subtasks", task_id, existing_count)
            summary["tasks_skipped"] += 1
            continue

        # Extract subtasks from plan_content
        subtasks = extract_subtasks_from_plan(task_id, task["plan_content"])

        if not subtasks:
            logger.info("Skipping %s: no subtasks to migrate", task_id)
            summary["tasks_skipped"] += 1
            continue

        # Migrate
        count = migrate_subtasks(subtasks, dry_run=dry_run)
        summary["tasks_migrated"] += 1
        summary["subtasks_migrated"] += count

        detail = {
            "task_id": task_id,
            "title": title[:60],
            "subtask_count": count,
        }
        summary["details"].append(detail)

        action = "Would migrate" if dry_run else "Migrated"
        logger.info("%s %s: %d subtasks from '%s'", action, task_id, count, title[:50])

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Migrate plan_content.tasks[] to task_subtasks table"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview changes without modifying database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    logger.info("=== Migration: plan_content -> task_subtasks (%s) ===", mode)

    summary = run_migration(dry_run=args.dry_run)

    print("\n=== Migration Summary ===")
    print(f"Mode: {'DRY RUN (no changes made)' if summary['dry_run'] else 'LIVE'}")
    print(f"Tasks found: {summary['tasks_found']}")
    print(f"Tasks migrated: {summary['tasks_migrated']}")
    print(f"Tasks skipped: {summary['tasks_skipped']}")
    print(f"Subtasks migrated: {summary['subtasks_migrated']}")

    if summary["details"]:
        print("\n=== Details ===")
        for detail in summary["details"]:
            print(f"  {detail['task_id']}: {detail['subtask_count']} subtasks - {detail['title']}")

    if args.dry_run:
        print("\n[DRY RUN] Run without --dry-run to execute migration")

    return 0 if summary["subtasks_migrated"] > 0 or summary["tasks_found"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
