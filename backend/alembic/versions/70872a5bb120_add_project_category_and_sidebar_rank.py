"""add project category and sidebar rank

Revision ID: 70872a5bb120
Revises: 1f7ad32e4c91
Create Date: 2026-04-01 15:00:30.835219

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "70872a5bb120"
down_revision: str | Sequence[str] | None = "1f7ad32e4c91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "projects",
        sa.Column("category", sa.Text(), nullable=False, server_default="dev"),
    )
    op.add_column(
        "projects",
        sa.Column("sidebar_rank", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "projects_category_check",
        "projects",
        "category IN ('production', 'testing', 'dev')",
    )
    op.create_check_constraint(
        "projects_sidebar_rank_check",
        "projects",
        "sidebar_rank IS NULL OR sidebar_rank >= 0",
    )
    op.execute(
        """
        UPDATE projects
        SET category = CASE
            WHEN id IN ('test1', 'test2', 'test3') THEN 'testing'
            ELSE 'production'
        END
        """
    )
    op.execute(
        """
        UPDATE projects
        SET name = CASE id
            WHEN 'test1' THEN 'Testing 1'
            WHEN 'test2' THEN 'Testing 2'
            WHEN 'test3' THEN 'Testing 3'
            ELSE name
        END
        WHERE id IN ('test1', 'test2', 'test3')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        UPDATE projects
        SET name = CASE id
            WHEN 'test1' THEN 'Testbed 1'
            WHEN 'test2' THEN 'Testbed'
            WHEN 'test3' THEN 'Testbed 3'
            ELSE name
        END
        WHERE id IN ('test1', 'test2', 'test3')
        """
    )
    op.drop_constraint("projects_sidebar_rank_check", "projects", type_="check")
    op.drop_constraint("projects_category_check", "projects", type_="check")
    op.drop_column("projects", "sidebar_rank")
    op.drop_column("projects", "category")
