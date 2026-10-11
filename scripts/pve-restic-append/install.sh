#!/usr/bin/env bash
# Install or refresh the append-only restic copy on davion-gem (idempotent).
#
# Layout:  PVE host  /usr/local/sbin/restic-append-serve  (forced command)
#          CT 160    /usr/local/sbin/restic-append-{stdio,maintain.py}
#                    /etc/restic-append/{password,policy.json}
#                    /srv/restic/repo  (150 GB thin volume, mp0)
# The workstation key ($KEY) is restricted to the forced command, so it can
# append snapshots and read status but cannot delete repository data.
#
# Re-run after changing source retention so the PVE-side policy follows.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PVE="${PVE_HOST:-proxmox-gem}"
CT="${RESTIC_APPEND_CT:-160}"
KEYDIR="${SUMMITFLOW_BACKUP_KEYS:-$HOME/.local/state/summitflow/backup-keys}"
KEY="$KEYDIR/pve-append.ed25519"
PASSWORD="$KEYDIR/restic-local.password"  # Same secret the owner already stores.

[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C summitflow-pve-append -f "$KEY"
chmod 600 "$KEY"

policy="$(cd "$HERE/../.." && st db query -t "SELECT json_object_agg(id, retention_days) FROM backup_sources WHERE enabled")"
policy_file="$(mktemp)"; trap 'rm -f "$policy_file"' EXIT
python3 -I -c 'import json,sys; s=json.loads(sys.argv[1]); json.dump({"default_days":30,"min_days":7,"sources":s}, open(sys.argv[2],"w"), indent=2, sort_keys=True)' "$policy" "$policy_file"

scp -q "$HERE/restic-append-serve" "$PVE:/usr/local/sbin/restic-append-serve"
ssh "$PVE" chmod 0755 /usr/local/sbin/restic-append-serve
stage="/root/restic-append-stage"
ssh "$PVE" "install -d -m 700 $stage"
scp -q "$HERE/restic-append-stdio" "$HERE/restic-append-maintain.py" "$HERE/restic-append-maintain.service" \
  "$HERE/restic-append-maintain.timer" "$HERE/README.txt" "$PASSWORD" "$PVE:$stage/"
scp -q "$policy_file" "$PVE:$stage/policy.json"
ssh "$PVE" bash -s -- "$CT" "$stage" "$(basename "$PASSWORD")" <<'REMOTE'
set -euo pipefail
ct="$1"; stage="$2"; pw="$3"
p() { pct push "$ct" "$stage/$1" "$2" --perms "$3"; }
pct exec "$ct" -- install -d -m 750 -o root -g restic /etc/restic-append
pct exec "$ct" -- install -d -m 755 -o restic -g restic /var/lib/restic-append
p restic-append-stdio /usr/local/sbin/restic-append-stdio 0755
p restic-append-maintain.py /usr/local/sbin/restic-append-maintain.py 0755
p restic-append-maintain.service /etc/systemd/system/restic-append-maintain.service 0644
p restic-append-maintain.timer /etc/systemd/system/restic-append-maintain.timer 0644
p policy.json /etc/restic-append/policy.json 0644
pct push "$ct" "$stage/$pw" /etc/restic-append/password --perms 0440 --user 0 --group "$(pct exec "$ct" -- id -g restic)"
pct exec "$ct" -- systemctl daemon-reload
pct exec "$ct" -- systemctl enable --now restic-append-maintain.timer
install -m 0644 "$stage/README.txt" /root/RESTIC-APPEND-README.txt
shred -u "$stage/$pw"; rm -rf "$stage"
REMOTE

line="restrict,command=\"/usr/local/sbin/restic-append-serve\" $(cut -d' ' -f1,2 "$KEY.pub") summitflow-pve-append"
# ssh re-splits remote arguments, so pass the key line base64-encoded.
ssh "$PVE" bash -s -- "$(printf '%s' "$line" | base64 -w0)" <<'REMOTE'
set -euo pipefail
keys=/root/.ssh/authorized_keys
line="$(printf '%s' "$1" | base64 -d)"
grep -v -e 'summitflow-pve-append$' -e '^restrict,command=/usr/local/sbin/restic-append-serve$' "$keys" > "$keys.new" || true
printf '%s\n' "$line" >> "$keys.new"
cat "$keys.new" > "$keys"; rm -f "$keys.new"
REMOTE
echo "restic-append installed on $PVE CT $CT"
