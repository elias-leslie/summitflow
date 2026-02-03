"""add_agent_hub_session_ids_to_tasks

Revision ID: 028147425749
Revises: 800fff09a547
Create Date: 2026-02-03 09:43:50.961067

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "028147425749"
down_revision: str | Sequence[str] | None = "800fff09a547"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add agent_hub_session_ids column to tasks table.

    This column stores Agent Hub session IDs for full observability.
    A task can have multiple sessions due to retries or multiple subtask executions.
    """
    op.add_column(
        "tasks",
        sa.Column("agent_hub_session_ids", sa.ARRAY(sa.Text()), nullable=True, server_default="{}"),
    )


def downgrade() -> None:
    """Remove agent_hub_session_ids column from tasks table."""
    op.drop_column("tasks", "agent_hub_session_ids")
