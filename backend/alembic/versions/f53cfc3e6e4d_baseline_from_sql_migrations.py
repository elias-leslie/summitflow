"""baseline_from_sql_migrations

Revision ID: f53cfc3e6e4d
Revises:
Create Date: 2026-01-29 13:01:38.575477

This is a baseline migration that marks the starting point for Alembic tracking.
The actual schema was created by raw SQL migrations now archived in migrations-archive/.

To apply this baseline on an existing database:
    alembic stamp head

Future migrations are tracked by Alembic from this point forward.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f53cfc3e6e4d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline migration - schema already exists from SQL migrations.

    This migration is intentionally empty. The schema was created by
    100 raw SQL migration files in the migrations/ directory.

    Run `alembic stamp head` to mark this baseline as applied.
    """
    pass


def downgrade() -> None:
    """Cannot downgrade past baseline.

    The original schema was created by raw SQL files, not Alembic.
    To reset, restore from backup or recreate the database.
    """
    raise RuntimeError(
        "Cannot downgrade past baseline migration. "
        "The original schema was created by raw SQL migrations in migrations/*.sql"
    )
