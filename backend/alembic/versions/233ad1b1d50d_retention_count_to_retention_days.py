"""retention_count_to_retention_days

Switch backup retention from count-based to time-based (14 days).

Revision ID: 233ad1b1d50d
Revises: bd41844e715b
Create Date: 2026-02-11 11:00:54.970882
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "233ad1b1d50d"
down_revision: str | Sequence[str] | None = "bd41844e715b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("backup_schedules"):
        columns = {column["name"] for column in inspector.get_columns("backup_schedules")}
        # Add retention_days column with default 14
        if "retention_days" not in columns:
            op.execute(
                "ALTER TABLE backup_schedules ADD COLUMN retention_days INTEGER NOT NULL DEFAULT 14"
            )
        op.execute("UPDATE backup_schedules SET retention_days = 14")
        op.execute("ALTER TABLE backup_schedules DROP COLUMN IF EXISTS retention_count")



def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("backup_schedules"):
        return

    columns = {column["name"] for column in inspector.get_columns("backup_schedules")}
    if "retention_count" not in columns:
        op.execute(
            "ALTER TABLE backup_schedules ADD COLUMN retention_count INTEGER NOT NULL DEFAULT 5"
        )
    op.execute("UPDATE backup_schedules SET retention_count = 5")
    op.execute("ALTER TABLE backup_schedules DROP COLUMN IF EXISTS retention_days")
