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


def _existing_backup_columns() -> set[str]:
    """Return the current column names on backups."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("backups")}


def upgrade() -> None:
    """Add verification columns to backups table.

    These columns store backup verification results from verify_backup():
    - verified: whether the archive passed integrity checks
    - verified_at: when verification was performed
    - checksum: SHA256 checksum of the archive
    - total_files: number of files in the archive
    - verification_json: full verification output (tree, errors, etc.)
    """
    existing_columns = _existing_backup_columns()
    if "verified" not in existing_columns:
        op.add_column("backups", sa.Column("verified", sa.Boolean(), nullable=True))
    if "verified_at" not in existing_columns:
        op.add_column(
            "backups",
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "checksum" not in existing_columns:
        op.add_column("backups", sa.Column("checksum", sa.Text(), nullable=True))
    if "total_files" not in existing_columns:
        op.add_column("backups", sa.Column("total_files", sa.Integer(), nullable=True))
    if "verification_json" not in existing_columns:
        op.add_column("backups", sa.Column("verification_json", JSONB(), nullable=True))


def downgrade() -> None:
    """Remove verification columns from backups table."""
    existing_columns = _existing_backup_columns()
    if "verification_json" in existing_columns:
        op.drop_column("backups", "verification_json")
    if "total_files" in existing_columns:
        op.drop_column("backups", "total_files")
    if "checksum" in existing_columns:
        op.drop_column("backups", "checksum")
    if "verified_at" in existing_columns:
        op.drop_column("backups", "verified_at")
    if "verified" in existing_columns:
        op.drop_column("backups", "verified")
