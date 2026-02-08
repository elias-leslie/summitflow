"""add_backup_verification_columns

Revision ID: 1c2176c7fa7a
Revises: 028147425749
Create Date: 2026-02-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c2176c7fa7a"
down_revision: str | Sequence[str] | None = "028147425749"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add verification columns to backups table.

    These columns store backup verification results from verify_backup():
    - verified: whether the archive passed integrity checks
    - verified_at: when verification was performed
    - checksum: SHA256 checksum of the archive
    - total_files: number of files in the archive
    - verification_json: full verification output (tree, errors, etc.)
    """
    op.add_column("backups", sa.Column("verified", sa.Boolean(), nullable=True))
    op.add_column(
        "backups",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("backups", sa.Column("checksum", sa.Text(), nullable=True))
    op.add_column("backups", sa.Column("total_files", sa.Integer(), nullable=True))
    op.add_column("backups", sa.Column("verification_json", JSONB(), nullable=True))


def downgrade() -> None:
    """Remove verification columns from backups table."""
    op.drop_column("backups", "verification_json")
    op.drop_column("backups", "total_files")
    op.drop_column("backups", "checksum")
    op.drop_column("backups", "verified_at")
    op.drop_column("backups", "verified")
