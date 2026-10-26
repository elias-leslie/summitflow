#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SYSTEMD_DIR="$ROOT_DIR/scripts/systemd"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

# SummitFlow-specific host infrastructure only. Host-level checks and
# maintenance (disk, Btrfs, SMART, scrubs, journald retention) belong to Nightshift.

# Root-owned: backup jobs make T7 backup storage writable only through it.
sudo install -o root -g root -m 0755 "$ROOT_DIR/scripts/summitflow-backup-window" /usr/local/sbin/summitflow-backup-window
# Root-owned, path-confined helpers: the only root entry points for native capture
# files, steward receipts, snapshot deletion and the host collector install (one exact sudoers line each).
sudo install -o root -g root -m 0755 "$ROOT_DIR/scripts/summitflow-native-capture" /usr/local/sbin/summitflow-native-capture
sudo install -o root -g root -m 0755 "$ROOT_DIR/scripts/summitflow-steward-receipt" /usr/local/sbin/summitflow-steward-receipt
sudo install -o root -g root -m 0755 "$ROOT_DIR/scripts/summitflow-snapshot-delete" /usr/local/sbin/summitflow-snapshot-delete
sudo install -o root -g root -m 0755 "$ROOT_DIR/backend/cli/lib/host_monitor_deploy.py" /usr/local/sbin/summitflow-host-monitor-deploy

units=(
  summitflow-backup-window-guard.service summitflow-backup-window-guard.timer
)
for unit in "${units[@]}"; do
  sudo install -m 0644 "$SYSTEMD_DIR/$unit" "/etc/systemd/system/$unit"
done

# Bound future Docker container logs. Existing containers adopt this on their
# next normal recreation; no forced data-service restart is required here.
sudo install -d -m 0755 /etc/docker
if [[ ! -e /etc/docker/daemon.json ]]; then
  sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "25m",
    "max-file": "3"
  }
}
EOF
fi

# btrbk appends one transaction log per native capture run.
sudo tee /etc/logrotate.d/summitflow-btrbk >/dev/null <<'EOF'
/var/log/summitflow-btrbk.log {
    monthly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
    su root syslog
}
EOF

# The older user timer removed every dangling volume immediately and duplicated
# the application-aware daily maintenance path; Docker pruning is Nightshift's.
systemctl --user disable --now docker-prune.timer 2>/dev/null || true

# Reconcile core Compose infrastructure without depending on st, the API,
# PostgreSQL, or Hatchet. Application services remain ordered after this unit.
install -d -m 0755 "$USER_SYSTEMD_DIR"
cat >"$USER_SYSTEMD_DIR/summitflow-infra-reconcile.service" <<'EOF'
[Unit]
Description=Reconcile SummitFlow shared Docker infrastructure directly from Compose
After=basic.target
Before=agent-hub-backend.service agent-hub-hatchet-agent-worker.service agent-hub-hatchet-ops-worker.service summitflow-backend.service summitflow-hatchet-worker.service portfolio-backend.service portfolio-hatchet-worker.service aico-web.service

[Service]
Type=oneshot
WorkingDirectory=/srv/workspaces/projects/summitflow/docker/compose
ExecStart=/usr/bin/docker compose --env-file %h/.config/credstore/summitflow/compose.env -f /srv/workspaces/projects/summitflow/docker/compose/docker-compose.yml --profile infra up -d --remove-orphans
RemainAfterExit=yes
Restart=on-failure
RestartSec=15
TimeoutStartSec=10min

[Install]
WantedBy=default.target
EOF

# The host backup job: btrbk every 4 hours, one daily Google Drive copy. It runs from the current release.
for unit in summitflow-host-backup.service summitflow-host-backup.timer; do
  install -m 0644 "$SYSTEMD_DIR/$unit" "$USER_SYSTEMD_DIR/$unit"
done

sudo systemctl daemon-reload
systemctl --user daemon-reload
systemctl --user enable --now summitflow-host-backup.timer
sudo systemctl enable --now summitflow-backup-window-guard.timer
sudo systemctl enable summitflow-backup-window-guard.service
systemctl --user enable summitflow-infra-reconcile.service

echo "SummitFlow host infrastructure installed."
