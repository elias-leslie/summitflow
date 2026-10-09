"""Permit four-hour portable captures without activating unqualified sources.

Revision ID: 9c4e2b107a63
Revises: d714ab902e31
"""

from alembic import op

revision = "9c4e2b107a63"
down_revision = "d714ab902e31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE backup_sources DROP CONSTRAINT IF EXISTS source_frequency_check")
    op.execute("""ALTER TABLE backup_sources ADD CONSTRAINT source_frequency_check
                  CHECK (frequency IN ('hourly', 'four_hourly', 'daily', 'weekly', 'monthly'))""")
    # Cadence is activated with each source's qualified Restic backend. Changing
    # it here could launch repeated full archives on the still-active backend.


def downgrade() -> None:
    op.execute("""UPDATE backup_sources SET frequency = 'daily',
                  next_run_at = last_run_at + INTERVAL '1 day', updated_at = NOW()
                  WHERE frequency = 'four_hourly'""")
    op.execute("ALTER TABLE backup_sources DROP CONSTRAINT IF EXISTS source_frequency_check")
    op.execute("""ALTER TABLE backup_sources ADD CONSTRAINT source_frequency_check
                  CHECK (frequency IN ('hourly', 'daily', 'weekly', 'monthly'))""")
