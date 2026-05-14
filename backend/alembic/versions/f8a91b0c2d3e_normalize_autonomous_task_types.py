"""normalize autonomous task type settings

Revision ID: f8a91b0c2d3e
Revises: e5d7a9c2b8f1
Create Date: 2026-05-14 23:20:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8a91b0c2d3e"
down_revision: str | Sequence[str] | None = "e5d7a9c2b8f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CANONICAL_ALLOWED_TYPES = '["feature", "bug", "task", "refactor", "debt", "regression"]'
LEGACY_ALLOWED_TYPES = '["refactor", "bug", "regression", "feature", "chore", "docs"]'


def upgrade() -> None:
    """Replace legacy autonomous allowed-type defaults with canonical task types."""
    op.execute(
        f"""
        UPDATE projects
        SET agent_configs = jsonb_set(
            COALESCE(agent_configs, '{{}}'::jsonb),
            '{{autonomous_allowed_types}}',
            '{CANONICAL_ALLOWED_TYPES}'::jsonb
        )
        WHERE agent_configs->'autonomous_allowed_types' = '{LEGACY_ALLOWED_TYPES}'::jsonb
        """
    )


def downgrade() -> None:
    """Restore the previous legacy default allowed-type list."""
    op.execute(
        f"""
        UPDATE projects
        SET agent_configs = jsonb_set(
            COALESCE(agent_configs, '{{}}'::jsonb),
            '{{autonomous_allowed_types}}',
            '{LEGACY_ALLOWED_TYPES}'::jsonb
        )
        WHERE agent_configs->'autonomous_allowed_types' = '{CANONICAL_ALLOWED_TYPES}'::jsonb
        """
    )
