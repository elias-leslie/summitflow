"""Add local clock ownership fences for Agent Hub cutovers.

Revision ID: b81f04c7a22d
Revises: 9ab4d2e6c810
Create Date: 2026-09-23 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b81f04c7a22d"
down_revision: str | Sequence[str] | None = "9ab4d2e6c810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE automation_clock_fences (
            project_id TEXT NOT NULL,
            workflow_key TEXT NOT NULL CHECK (
                workflow_key IN ('work_pickup', 'task_generation')
            ),
            clock_owner TEXT NOT NULL CHECK (clock_owner = 'agent_hub'),
            fence_receipt TEXT NOT NULL UNIQUE,
            fenced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (project_id, workflow_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS automation_clock_fences")
