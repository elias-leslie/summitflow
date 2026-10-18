"""Backups SummitFlow does not run itself but tracks for freshness (Blackbox archive pull, Portfolio-AI artifacts).

Each row names how to read its last success: a systemd unit's last successful run, or the newest file matching a
glob. They join the backup-freshness receipt and the Backups page next to SummitFlow's own sources.

Revision ID: e3b7a1c9d4f2
Revises: c8e1f4a2b7d3
"""

import sqlalchemy as sa

from alembic import op

revision = "e3b7a1c9d4f2"
down_revision = "c8e1f4a2b7d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_backup_sources",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("owner_project", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False, server_default="daily"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('systemd_unit', 'artifact_glob')", name="external_backup_sources_kind"),
        sa.CheckConstraint("frequency IN ('hourly', 'four_hourly', 'daily', 'weekly', 'monthly')",
                           name="external_backup_sources_frequency"),
    )
    op.execute(
        """
        INSERT INTO external_backup_sources (id, name, owner_project, kind, target, frequency) VALUES
        ('blackbox-archive', 'Blackbox off-building archive pull', 'blackbox', 'systemd_unit',
         'blackbox-archive.service', 'daily'),
        ('portfolio-ai-complete', 'Portfolio-AI full backup (database and uploads)', 'portfolio-ai', 'artifact_glob',
         '/srv/workspaces/projects/portfolio-ai/data/backups/portfolio_ai_complete_*.tar.gz', 'weekly')
        """
    )


def downgrade() -> None:
    op.drop_table("external_backup_sources")
