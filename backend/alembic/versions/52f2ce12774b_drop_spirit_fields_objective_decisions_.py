"""drop spirit fields objective decisions constraints spirit_anti

Revision ID: 52f2ce12774b
Revises: 6ce254b8aa82
Create Date: 2026-03-19 14:10:00.000000

Simplifies task_spirit table:
- Copies objective into task description where description is empty
- Drops: objective, spirit_anti, decisions, constraints
- Keeps: task_id, done_when, context, plan_status, plan_approved_at,
         plan_approved_by, plan_history, created_at, updated_at, complexity
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "52f2ce12774b"
down_revision: str | Sequence[str] | None = "6ce254b8aa82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Copy objective to task description, then drop removed spirit columns."""
    # Copy objective into task description where description is empty or null
    op.execute("""
        UPDATE tasks t
        SET description = ts.objective
        FROM task_spirit ts
        WHERE t.id = ts.task_id
          AND ts.objective IS NOT NULL
          AND ts.objective != ''
          AND (t.description IS NULL OR t.description = '')
    """)

    op.drop_column("task_spirit", "objective")
    op.drop_column("task_spirit", "spirit_anti")
    op.drop_column("task_spirit", "decisions")
    op.drop_column("task_spirit", "constraints")


def downgrade() -> None:
    """Re-add dropped columns (data is lost)."""
    op.add_column("task_spirit", sa.Column("objective", sa.Text(), nullable=True))
    op.add_column("task_spirit", sa.Column("spirit_anti", sa.Text(), nullable=True))
    op.add_column("task_spirit", sa.Column("decisions", sa.JSON(), nullable=True))
    op.add_column("task_spirit", sa.Column("constraints", sa.JSON(), nullable=True))
