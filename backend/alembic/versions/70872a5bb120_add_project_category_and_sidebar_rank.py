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


def _existing_project_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("projects")}


def _existing_project_constraints() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {constraint["name"] for constraint in inspector.get_check_constraints("projects")}


def upgrade() -> None:
    """Upgrade schema."""
    existing_columns = _existing_project_columns()
    if "category" not in existing_columns:
        op.add_column(
            "projects",
            sa.Column("category", sa.Text(), nullable=False, server_default="dev"),
        )
    if "sidebar_rank" not in existing_columns:
        op.add_column(
            "projects",
            sa.Column("sidebar_rank", sa.Integer(), nullable=True),
        )
    existing_constraints = _existing_project_constraints()
    if "projects_category_check" not in existing_constraints:
        op.create_check_constraint(
            "projects_category_check",
            "projects",
            "category IN ('production', 'testing', 'dev')",
        )
    if "projects_sidebar_rank_check" not in existing_constraints:
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
    existing_constraints = _existing_project_constraints()
    if "projects_sidebar_rank_check" in existing_constraints:
        op.drop_constraint("projects_sidebar_rank_check", "projects", type_="check")
    if "projects_category_check" in existing_constraints:
        op.drop_constraint("projects_category_check", "projects", type_="check")
    existing_columns = _existing_project_columns()
    if "sidebar_rank" in existing_columns:
        op.drop_column("projects", "sidebar_rank")
    if "category" in existing_columns:
        op.drop_column("projects", "category")
