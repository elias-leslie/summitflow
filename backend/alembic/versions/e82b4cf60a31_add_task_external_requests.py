"""Persist atomic external task request identities across task archival."""

from alembic import op

revision = "e82b4cf60a31"
down_revision = "c935fa8c0398"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_external_requests (
            principal_scope TEXT NOT NULL,
            external_origin TEXT NOT NULL,
            external_request_key TEXT NOT NULL,
            external_payload_digest TEXT NOT NULL,
            task_id TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (principal_scope, external_origin, external_request_key)
        )
    """)


def downgrade() -> None:
    op.drop_table("task_external_requests")
