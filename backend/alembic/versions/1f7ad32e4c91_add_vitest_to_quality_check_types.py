"""add vitest to quality check types

Revision ID: 1f7ad32e4c91
Revises: 026023735979
Create Date: 2026-03-25 14:24:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f7ad32e4c91"
down_revision: str | Sequence[str] | None = "026023735979"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("quality_check_results_check_type_check", "quality_check_results", type_="check")
    op.create_check_constraint(
        "quality_check_results_check_type_check",
        "quality_check_results",
        "check_type IN ('pytest', 'vitest', 'ruff', 'types', 'biome', 'tsc')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("quality_check_results_check_type_check", "quality_check_results", type_="check")
    op.execute("DELETE FROM quality_check_results WHERE check_type = 'vitest'")
    op.create_check_constraint(
        "quality_check_results_check_type_check",
        "quality_check_results",
        "check_type IN ('pytest', 'ruff', 'types', 'biome', 'tsc')",
    )
