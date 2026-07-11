#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SYSTEMD_DIR="$ROOT_DIR/scripts/systemd"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

sudo install -d -m 0755 /usr/local/libexec /var/lib/summitflow-host-guardian
sudo install -m 0755 "$ROOT_DIR/scripts/host-guardian.py" /usr/local/libexec/summitflow-host-guardian

units=(
  summitflow-host-guardian.service summitflow-host-guardian.timer
  summitflow-host-maintenance.service summitflow-host-maintenance.timer
  summitflow-btrfs-scrub.service summitflow-btrfs-scrub.timer
  summitflow-nvme-short-test.service summitflow-nvme-short-test.timer
  summitflow-nvme-long-test.service summitflow-nvme-long-test.timer
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

sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/20-storage-guardrails.conf >/dev/null <<'EOF'
[Journal]
SystemMaxUse=500M
SystemKeepFree=5G
MaxRetentionSec=14day
EOF

# The older user timer removed every dangling volume immediately and duplicated
# the application-aware daily maintenance path. Disable it in favor of the
# age-gated, system-level guardian.
systemctl --user disable --now docker-prune.timer 2>/dev/null || true

# Reconcile core Compose infrastructure without depending on st, the API,
# PostgreSQL, or Hatchet. Application services remain ordered after this unit.
install -d -m 0755 "$USER_SYSTEMD_DIR"
cat >"$USER_SYSTEMD_DIR/summitflow-infra-reconcile.service" <<'EOF'
[Unit]
Description=Reconcile SummitFlow shared Docker infrastructure directly from Compose
After=basic.target
Before=agent-hub-backend.service agent-hub-hatchet-agent-worker.service agent-hub-hatchet-ops-worker.service summitflow-backend.service summitflow-hatchet-worker.service portfolio-backend.service portfolio-hatchet-worker.service a-term-backend.service

[Service]
Type=oneshot
WorkingDirectory=/srv/workspaces/projects/summitflow/docker/compose
ExecStart=/usr/bin/docker compose --env-file /srv/workspaces/projects/summitflow/docker/compose/.env -f /srv/workspaces/projects/summitflow/docker/compose/docker-compose.yml --profile infra up -d --remove-orphans
RemainAfterExit=yes
Restart=on-failure
RestartSec=15
TimeoutStartSec=10min

[Install]
WantedBy=default.target
EOF

sudo systemctl daemon-reload
systemctl --user daemon-reload
sudo systemctl enable --now \
  summitflow-host-guardian.timer \
  summitflow-host-maintenance.timer \
  summitflow-btrfs-scrub.timer \
  summitflow-nvme-short-test.timer \
  summitflow-nvme-long-test.timer
systemctl --user enable summitflow-infra-reconcile.service
sudo systemctl try-restart systemd-journald.service

echo "Host maintenance installed. Run: sudo systemctl start summitflow-host-guardian.service"
