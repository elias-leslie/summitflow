"""Add ordered, idempotent fleet rows to the shared events table.

Revision ID: d714ab902e31
Revises: c32e8b917a60
"""

from alembic import op

revision = "d714ab902e31"
down_revision = "c32e8b917a60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS stream_sequence BIGINT")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS source_key TEXT")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS source_digest TEXT")
    op.execute("""
        ALTER TABLE events ADD CONSTRAINT events_fleet_stream_fields CHECK (
            (stream_sequence IS NULL AND source_key IS NULL AND source_digest IS NULL)
            OR (source = 'fleet' AND stream_sequence IS NOT NULL AND stream_sequence > 0 AND source_key IS NOT NULL
                AND source_digest IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS events_fleet_sequence ON events (trace_id, stream_sequence)
        WHERE stream_sequence IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS events_fleet_source_key ON events (trace_id, source_key)
        WHERE stream_sequence IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX events_fleet_source_key")
    op.execute("DROP INDEX events_fleet_sequence")
    op.execute("ALTER TABLE events DROP CONSTRAINT events_fleet_stream_fields")
    op.execute("ALTER TABLE events DROP COLUMN source_digest")
    op.execute("ALTER TABLE events DROP COLUMN source_key")
    op.execute("ALTER TABLE events DROP COLUMN stream_sequence")
