"""Add share users and grants.

Revision ID: d4a7e9b1c602
Revises: c6d9a2f4b8e1
Create Date: 2026-06-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a7e9b1c602"
down_revision: str | Sequence[str] | None = "c6d9a2f4b8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS share_users (
            email TEXT PRIMARY KEY,
            role TEXT NOT NULL CHECK (role IN ('owner', 'viewer')),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS share_grants (
            id BIGSERIAL PRIMARY KEY,
            user_email TEXT NOT NULL REFERENCES share_users(email) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            section TEXT NOT NULL CHECK (section IN ('design')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_email, project_id, section)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_share_grants_user ON share_grants(user_email)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_share_grants_project ON share_grants(project_id)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_share_grants_project")
    op.execute("DROP INDEX IF EXISTS idx_share_grants_user")
    op.execute("DROP TABLE IF EXISTS share_grants")
    op.execute("DROP TABLE IF EXISTS share_users")
