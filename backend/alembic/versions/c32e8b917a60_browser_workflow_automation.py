"""Extend the existing automation outbox for resumable browser workflows.

Revision ID: c32e8b917a60
Revises: a71e0c6d2f94
"""

from alembic import op

revision = "c32e8b917a60"
down_revision = "a71e0c6d2f94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE automation_dispatch_receipts DROP CONSTRAINT automation_dispatch_receipts_workflow_key_check")
    op.execute("ALTER TABLE automation_dispatch_receipts ADD CONSTRAINT automation_dispatch_receipts_workflow_key_check CHECK (workflow_key IN ('work_pickup', 'task_generation', 'browser_workflow'))")
    op.execute("ALTER TABLE automation_dispatch_receipts DROP CONSTRAINT automation_dispatch_receipts_status_check")
    op.execute("ALTER TABLE automation_dispatch_receipts ADD CONSTRAINT automation_dispatch_receipts_status_check CHECK (status IN ('pending', 'queued', 'running', 'waiting', 'succeeded', 'failed', 'skipped', 'cancelled'))")
    op.execute("ALTER TABLE automation_dispatch_receipts ADD COLUMN control_action JSONB")
    op.execute("ALTER TABLE automation_dispatch_receipts ADD COLUMN control_history JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    # These constraints deliberately refuse downgrade while browser receipts
    # exist. Never discard an accepted run or its unresolved human checkpoint.
    op.execute("ALTER TABLE automation_dispatch_receipts DROP CONSTRAINT automation_dispatch_receipts_workflow_key_check")
    op.execute("ALTER TABLE automation_dispatch_receipts ADD CONSTRAINT automation_dispatch_receipts_workflow_key_check CHECK (workflow_key IN ('work_pickup', 'task_generation'))")
    op.execute("ALTER TABLE automation_dispatch_receipts DROP CONSTRAINT automation_dispatch_receipts_status_check")
    op.execute("ALTER TABLE automation_dispatch_receipts ADD CONSTRAINT automation_dispatch_receipts_status_check CHECK (status IN ('pending', 'queued', 'running', 'succeeded', 'failed', 'skipped', 'cancelled'))")
    op.execute("ALTER TABLE automation_dispatch_receipts DROP COLUMN control_action")
    op.execute("ALTER TABLE automation_dispatch_receipts DROP COLUMN control_history")
