"""Retire the per-path backup sources that the host snapshots now cover.

Revision ID: a7d1c3e5f902
Revises: e3b7a1c9d4f2

btrbk snapshots every subvolume every four hours and one daily restic job reads those snapshots into Google
Drive, so the project, workspace, configuration and infrastructure sources under /, /home and /srv/workspaces
no longer run on their own. Their rows and history stay (disabled) so old points remain listed and restorable
while they age out. Proxmox sources and the directories on other drives keep running inside the daily job.
"""

from alembic import op

revision = "a7d1c3e5f902"
down_revision = "e3b7a1c9d4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """UPDATE backup_sources SET enabled = FALSE, updated_at = NOW()
           WHERE enabled
             AND path NOT LIKE 'proxmox://%'
             AND path NOT LIKE '/media/%'
             AND path NOT LIKE '/mnt/%'"""
    )


def downgrade() -> None:
    # Re-enabling sources would start the retired per-path jobs again; the retired scheduler no longer exists.
    pass
