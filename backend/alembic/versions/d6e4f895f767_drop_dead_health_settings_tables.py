"""drop_dead_health_settings_tables

Revision ID: d6e4f895f767
Revises: 233ad1b1d50d
Create Date: 2026-02-12 17:55:44.233255

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e4f895f767'
down_revision: Union[str, Sequence[str], None] = '233ad1b1d50d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
