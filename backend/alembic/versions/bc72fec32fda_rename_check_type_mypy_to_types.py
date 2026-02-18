"""rename check_type mypy to types

Revision ID: bc72fec32fda
Revises: a3b7c1d2e4f5
Create Date: 2026-02-18 12:48:08.921956

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc72fec32fda'
down_revision: Union[str, Sequence[str], None] = 'a3b7c1d2e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('quality_check_results_check_type_check', 'quality_check_results', type_='check')
    op.execute("UPDATE quality_check_results SET check_type = 'types' WHERE check_type = 'mypy'")
    op.create_check_constraint(
        'quality_check_results_check_type_check',
        'quality_check_results',
        "check_type IN ('pytest', 'ruff', 'types', 'biome', 'tsc')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('quality_check_results_check_type_check', 'quality_check_results', type_='check')
    op.execute("UPDATE quality_check_results SET check_type = 'mypy' WHERE check_type = 'types'")
    op.create_check_constraint(
        'quality_check_results_check_type_check',
        'quality_check_results',
        "check_type IN ('pytest', 'ruff', 'mypy', 'biome', 'tsc')"
    )
