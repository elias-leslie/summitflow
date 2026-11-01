"""Portfolio-AI backup freshness reads the backup unit inside its Proxmox guest

Revision ID: a4d9e2c7f1b8
Revises: 6537e645f71c

Portfolio-AI production moved into Proxmox VM 180 (project.identity.json runtime.deployment) and its
weekly portfolio-backup.timer runs there now, writing to the guest's /var/lib/app-backups/portfolio-weekly
(captured off-site by the pve-vm-180-app-recovery source). The external source still watched the retired
workstation folder, so it went stale on 2026-11-01 while the guest's backups kept succeeding.

A new kind, guest_unit, reads a systemd unit's last run inside the owner project's guest; the
portfolio-ai-complete row moves to it. Downgrade restores the workstation glob.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4d9e2c7f1b8"
down_revision: str | Sequence[str] | None = "6537e645f71c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_GLOB = "/srv/workspaces/projects/portfolio-ai/data/backups/portfolio_ai_complete_*.tar.gz"


def upgrade() -> None:
    op.drop_constraint("external_backup_sources_kind", "external_backup_sources", type_="check")
    op.create_check_constraint("external_backup_sources_kind", "external_backup_sources",
                               "kind IN ('systemd_unit', 'guest_unit', 'artifact_glob')")
    op.execute("UPDATE external_backup_sources SET kind = 'guest_unit', target = 'portfolio-backup.service' "
               "WHERE id = 'portfolio-ai-complete'")


def downgrade() -> None:
    op.execute(f"UPDATE external_backup_sources SET kind = 'artifact_glob', target = '{_OLD_GLOB}' "
               "WHERE id = 'portfolio-ai-complete'")
    op.execute("DELETE FROM external_backup_sources WHERE kind = 'guest_unit'")
    op.drop_constraint("external_backup_sources_kind", "external_backup_sources", type_="check")
    op.create_check_constraint("external_backup_sources_kind", "external_backup_sources",
                               "kind IN ('systemd_unit', 'artifact_glob')")
