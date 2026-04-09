"""normalize notes scope names

Revision ID: 3bd998f79eb7
Revises: c68eb0a27edb
Create Date: 2026-04-06 18:10:34.195245

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3bd998f79eb7'
down_revision: str | Sequence[str] | None = 'c68eb0a27edb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Normalize legacy note scope identifiers to canonical names."""
    op.execute(
        """
        UPDATE notes
        SET project_scope = 'a-term'
        WHERE lower(project_scope) = 'terminal'
        """
    )


def downgrade() -> None:
    """Data normalization is intentionally not reversed."""
