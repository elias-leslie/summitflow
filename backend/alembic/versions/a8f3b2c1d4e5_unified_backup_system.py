"""unified backup system

Add storage_backends table, extend backup_sources and backups tables
for the unified backup system (infrastructure backups, storage backend
management, WAL archiving support).

Revision ID: a8f3b2c1d4e5
Revises: 537e356aff9f
Create Date: 2026-03-15 10:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8f3b2c1d4e5"
down_revision: str | Sequence[str] | None = "537e356aff9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- storage_backends table ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS storage_backends (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            backend_type TEXT NOT NULL DEFAULT 'smb',
            config JSONB NOT NULL DEFAULT '{}',
            is_default BOOLEAN DEFAULT false,
            enabled BOOLEAN DEFAULT true,
            last_test_at TIMESTAMPTZ,
            last_test_ok BOOLEAN,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # --- Extend backup_sources ---
    # Add 'infrastructure' and 'hourly' to allowed values
    # Drop existing constraints if they exist, then recreate with new values
    op.execute("""
        ALTER TABLE backup_sources
        DROP CONSTRAINT IF EXISTS source_type_check
    """)
    op.execute("""
        ALTER TABLE backup_sources
        ADD CONSTRAINT source_type_check
        CHECK (source_type IN ('project', 'config', 'workspace', 'infrastructure'))
    """)

    op.execute("""
        ALTER TABLE backup_sources
        DROP CONSTRAINT IF EXISTS source_frequency_check
    """)
    op.execute("""
        ALTER TABLE backup_sources
        ADD CONSTRAINT source_frequency_check
        CHECK (frequency IN ('daily', 'weekly', 'monthly', 'hourly'))
    """)

    # Add storage_backend_id FK to backup_sources
    op.execute("""
        ALTER TABLE backup_sources
        ADD COLUMN IF NOT EXISTS storage_backend_id TEXT REFERENCES storage_backends(id)
    """)

    # --- Extend backups ---
    op.execute("""
        ALTER TABLE backups
        ADD COLUMN IF NOT EXISTS storage_backend_id TEXT
    """)
    op.execute("""
        ALTER TABLE backups
        ADD COLUMN IF NOT EXISTS wal_start_lsn TEXT
    """)
    op.execute("""
        ALTER TABLE backups
        ADD COLUMN IF NOT EXISTS wal_end_lsn TEXT
    """)


def downgrade() -> None:
    # Remove new columns from backups
    op.execute("ALTER TABLE backups DROP COLUMN IF EXISTS wal_end_lsn")
    op.execute("ALTER TABLE backups DROP COLUMN IF EXISTS wal_start_lsn")
    op.execute("ALTER TABLE backups DROP COLUMN IF EXISTS storage_backend_id")

    # Remove storage_backend_id from backup_sources
    op.execute("ALTER TABLE backup_sources DROP COLUMN IF EXISTS storage_backend_id")

    # Revert constraints
    op.execute("ALTER TABLE backup_sources DROP CONSTRAINT IF EXISTS source_frequency_check")
    op.execute("""
        ALTER TABLE backup_sources
        ADD CONSTRAINT source_frequency_check
        CHECK (frequency IN ('daily', 'weekly', 'monthly'))
    """)

    op.execute("ALTER TABLE backup_sources DROP CONSTRAINT IF EXISTS source_type_check")
    op.execute("""
        ALTER TABLE backup_sources
        ADD CONSTRAINT source_type_check
        CHECK (source_type IN ('project', 'config', 'workspace'))
    """)

    # Drop storage_backends table
    op.execute("DROP TABLE IF EXISTS storage_backends")
