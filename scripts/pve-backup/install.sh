#!/usr/bin/env bash
# Install or refresh SummitFlow's Proxmox backup dispatcher on davion-gem (idempotent).
#
#   sudo scripts/pve-backup/install.sh      # as root: the authorized_keys change is an install receipt, not a tripwire ask
#   scripts/pve-backup/install.sh           # as the owner: same install, Nightshift then asks about the key change
#
# Layout:  PVE host     /usr/local/sbin/summitflow-pve-backup     (forced command, root 0755)
#                       /etc/summitflow-pve-backup/sources.json   (what each source captures, root 0644)
#          workstation  <backup key dir>/pve-backup.ed25519       (no passphrase; bound to the forced command only)
# The owner's PVE ssh alias runs the one install session; the new key can only run the dispatcher's verbs
# (guests, thinpool, capture SOURCE DIGEST), from the workstation address only.
# Re-run after adding or changing a proxmox:// backup source: the dispatcher refuses a source whose path changed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PVE="${PVE_HOST:-proxmox-gem}"
FROM="${SUMMITFLOW_PVE_FROM:-192.168.86.128}"  # The workstation; every root key on PVE is pinned to it.
admin="${SUDO_USER:-$(id -un)}"
as_admin() { if [ "$(id -u)" = 0 ]; then sudo -u "$admin" -H "$@"; else "$@"; fi; }
# shellcheck disable=SC2016  # expanded by the admin shell
admin_home="$(as_admin sh -c 'printf %s "$HOME"')"
# shellcheck disable=SC2016  # expanded by the admin shell
KEYDIR="$(as_admin sh -c 'printf %s "${SUMMITFLOW_BACKUP_KEY_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/summitflow/backup-keys}"')"
KEY="$KEYDIR/pve-backup.ed25519"
[ -n "$admin_home" ] && [ -d "$KEYDIR" ] || { echo "backup key directory $KEYDIR is missing" >&2; exit 1; }

work="$(as_admin mktemp -d)"
rid=""; finished=0
receipt() { python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from nightshift.installs import main; raise SystemExit(main(sys.argv[2:]))' \
  /usr/local/lib/nightshift-exec/current "$@"; }
trap '[ -z "$rid" ] || [ "$finished" = 1 ] || receipt finish "$rid" --failed || true; rm -rf "$work"' EXIT

# shellcheck disable=SC2016  # expanded by the admin shell
uv_bin="$(as_admin sh -c 'command -v uv || printf %s "$HOME/.local/bin/uv"')"
(cd "$ROOT/backend" && as_admin "$uv_bin" run --quiet python -m app.tasks.backup_proxmox dispatcher-sources "$PVE") > "$work/sources.json"
echo "Sources this key may capture on $PVE:"
python3 -I -c 'import json, sys
for name, item in sorted(json.load(open(sys.argv[1])).items()):
    files = item.get("files") or {}
    print("  %-28s %-6s %-5s %s" % (name, item["kind"], item.get("vmid") or "", " ".join(files.get("paths", []))))' "$work/sources.json"

if [ ! -f "$KEY" ]; then
  as_admin rm -f "$KEY.new" "$KEY.new.pub"
  as_admin ssh-keygen -q -t ed25519 -N '' -C summitflow-pve-backup -f "$KEY.new"
  pub="$KEY.new.pub"
else
  pub="$KEY.pub"
fi
line="restrict,from=\"$FROM\",command=\"/usr/local/sbin/summitflow-pve-backup\" $(cut -d' ' -f1,2 "$pub") summitflow-pve-backup"

if [ "$(id -u)" = 0 ] && [ -d /usr/local/lib/nightshift-exec/current/nightshift ]; then
  rid=$(receipt begin summitflow-pve-backup --repo "$ROOT" \
    --expect "pve=/usr/local/sbin/summitflow-pve-backup" --expect "pve=/etc/summitflow-pve-backup/*")
fi

# One session: ssh re-splits remote arguments, so the files and the key line travel base64-encoded.
dispatcher_b64="$(base64 -w0 < "$HERE/summitflow-pve-backup")"
sources_b64="$(base64 -w0 < "$work/sources.json")"
line_b64="$(printf '%s' "$line" | base64 -w0)"
[ -n "$dispatcher_b64" ] && [ -n "$sources_b64" ] || { echo "nothing to install" >&2; exit 1; }
as_admin ssh "$PVE" bash -s -- "$dispatcher_b64" "$sources_b64" "$line_b64" > "$work/pve-install.out" <<'REMOTE'
set -euo pipefail
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
printf '%s' "$1" | base64 -d > "$tmp"
/usr/bin/python3 -I -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$tmp"
install -m 0755 -o root -g root "$tmp" /usr/local/sbin/summitflow-pve-backup
install -d -m 0755 -o root -g root /etc/summitflow-pve-backup
printf '%s' "$2" | base64 -d > "$tmp"
/usr/bin/python3 -I -c 'import json, sys; assert isinstance(json.load(open(sys.argv[1])), dict)' "$tmp"
install -m 0644 -o root -g root "$tmp" /etc/summitflow-pve-backup/sources.json
# Tripwire signature, byte for byte Nightshift's format (deploy/executor/install-pve.sh): the AUTH lines name each
# auth file transition this session makes, for the install receipt.
sig() {
  local f=$1 h t
  { [ -e "$f" ] || [ -L "$f" ]; } && [ ! -d "$f" ] || { echo MISSING; return; }
  h=$(sha256sum < "$f" 2>/dev/null | cut -c1-64); [ -n "$h" ] || h=UNREADABLE
  t=file; [ -L "$f" ] && t="symlink->$(readlink "$f")"; [ -L "$f" ] || [ -f "$f" ] || t=other
  printf '%s %s %s %s\n' "$h" "$(stat -c %u:%g "$f")" "$(stat -c %a "$f")" "$t"
}
auth_paths="/root/.ssh/authorized_keys /etc/pve/priv/authorized_keys"
declare -A before
for f in $auth_paths; do before[$f]=$(sig "$f"); done
ak=/root/.ssh/authorized_keys
line="$(printf '%s' "$3" | base64 -d)"
if ! grep -qxF "$line" "$ak"; then
  grep -v ' summitflow-pve-backup$' "$ak" > "$tmp" || true
  printf '%s\n' "$line" >> "$tmp"
  cat "$tmp" > "$ak"
fi
for f in $auth_paths; do
  after=$(sig "$f")
  [ "$after" = "${before[$f]}" ] || printf 'AUTH\t%s\t%s\t%s\n' "$f" "${before[$f]}" "$after"
done
echo "summitflow-pve-backup installed"
REMOTE
cat "$work/pve-install.out"
if [ -f "$KEY.new" ]; then as_admin mv -f "$KEY.new.pub" "$KEY.pub"; as_admin mv -f "$KEY.new" "$KEY"; fi
if [ -n "$rid" ]; then receipt finish "$rid" --auth "pve=$work/pve-install.out"; finished=1; fi
# The new key reaches only the dispatcher: a shell command is refused, the guest list answers.
check=(ssh -F /dev/null -i "$KEY" -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes
  -o "UserKnownHostsFile=$admin_home/.ssh/known_hosts" "root@$(as_admin ssh -G "$PVE" | awk '$1 == "hostname" {print $2}')")
as_admin "${check[@]}" guests > /dev/null && echo "key answers: guests"
if as_admin "${check[@]}" id 2>/dev/null; then echo "the key ran a shell command; remove its line from $PVE:/root/.ssh/authorized_keys" >&2; exit 1; fi
echo "key refuses other commands"
