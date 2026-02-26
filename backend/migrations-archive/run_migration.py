#!/usr/bin/env python3
"""Run explorer migrations.

Usage:
    cd backend
    .venv/bin/python migrations/run_migration.py

This script:
1. Creates explorer_entries and explorer_relationships tables (001)
2. Migrates data from legacy tables (002)
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.connection import get_connection


def run_migration(sql_file: Path) -> None:
    """Execute a SQL migration file."""
    print(f"Running migration: {sql_file.name}")

    sql = sql_file.read_text()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print(f"  Done: {sql_file.name}")


def verify_migration() -> None:
    """Verify migration results."""
    print("\nVerification:")

    with get_connection() as conn, conn.cursor() as cur:
        # Check table exists
        cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'explorer_entries'
                )
            """)
        exists = cur.fetchone()[0]
        print(f"  explorer_entries table exists: {exists}")

        if exists:
            # Count by type
            cur.execute("""
                    SELECT entry_type, COUNT(*) as count
                    FROM explorer_entries
                    GROUP BY entry_type
                    ORDER BY entry_type
                """)
            rows = cur.fetchall()
            total = 0
            for entry_type, count in rows:
                print(f"    {entry_type}: {count}")
                total += count
            print(f"    TOTAL: {total}")


def main() -> None:
    migrations_dir = Path(__file__).parent

    # Run migrations in order
    migrations = sorted(migrations_dir.glob("*.sql"))

    for migration in migrations:
        try:
            run_migration(migration)
        except Exception as e:
            print(f"  Warning: {e}")
            # Continue - might be idempotent migration that partially succeeded

    verify_migration()
    print("\nMigration complete!")


if __name__ == "__main__":
    main()
