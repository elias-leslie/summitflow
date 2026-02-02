"""drop task_subtasks details column

Revision ID: 800fff09a547
Revises: f53cfc3e6e4d
Create Date: 2026-02-02 16:04:54.702754

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "800fff09a547"
down_revision: str | None = "f53cfc3e6e4d"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE task_subtasks DROP COLUMN IF EXISTS details")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE task_subtasks ADD COLUMN IF NOT EXISTS details JSONB")
