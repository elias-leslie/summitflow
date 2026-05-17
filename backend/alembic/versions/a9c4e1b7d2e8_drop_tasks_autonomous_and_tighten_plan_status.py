"""drop tasks.autonomous and tighten task_spirit.plan_status default to 'draft'

Revision ID: a9c4e1b7d2e8
Revises: f8a91b0c2d3e
Create Date: 2026-05-17 13:05:00.000000

Removes the redundant boolean `tasks.autonomous` column. The canonical
source of truth is the `execution_mode` enum; the boolean was derived from
it but kept in lockstep, doubling write paths and producing schema drift
between the API model (which exposed both) and the storage layer.

Tightens `task_spirit.plan_status` to `NOT NULL DEFAULT 'draft'` so the
binary gate in `st claim` (draft → approved transitions) can rely on a
populated value for every task. Nulls are backfilled to 'draft' before the
constraint is applied.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c4e1b7d2e8"
down_revision: str | Sequence[str] | None = "f8a91b0c2d3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop tasks.autonomous; tighten task_spirit.plan_status default + NOT NULL."""
    # 1) tasks.autonomous → derived from execution_mode at read time.
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS autonomous")

    # 2) task_spirit.plan_status backfill + tighten.
    op.execute(
        "UPDATE task_spirit SET plan_status = 'draft' WHERE plan_status IS NULL"
    )
    op.execute(
        "ALTER TABLE task_spirit ALTER COLUMN plan_status SET DEFAULT 'draft'"
    )
    op.execute(
        "ALTER TABLE task_spirit ALTER COLUMN plan_status SET NOT NULL"
    )


def downgrade() -> None:
    """Restore tasks.autonomous (derived from execution_mode); relax plan_status."""
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS autonomous boolean DEFAULT false"
    )
    op.execute(
        "UPDATE tasks SET autonomous = (execution_mode = 'autonomous')"
    )
    op.execute("ALTER TABLE task_spirit ALTER COLUMN plan_status DROP NOT NULL")
    op.execute("ALTER TABLE task_spirit ALTER COLUMN plan_status DROP DEFAULT")
