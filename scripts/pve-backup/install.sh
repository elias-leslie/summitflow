#!/usr/bin/env bash
# Install or refresh SummitFlow's Proxmox backup dispatcher on davion-gem (idempotent).
#
#   sudo scripts/pve-backup/install.sh      # as root: the authorized_keys change is an install receipt, not a tripwire ask
#   scripts/pve-backup/install.sh           # as the owner: same install, Nightshift then asks about the key change
#   ... install.sh --yes DIGEST             # no terminal: install only the dispatcher and source list a first run
#                                           # (without --yes) printed as 'Approval digest: DIGEST'
#
# Layout:  PVE host     /usr/local/sbin/summitflow-pve-backup     (forced command, root 0755)
#                       /etc/summitflow-pve-backup/sources.json   (what each source captures, root 0644)
#          workstation  <backup key dir>/pve-backup.ed25519       (no passphrase; bound to the forced command only)
# The owner's PVE ssh alias runs the one install session; the new key can only run the dispatcher's verbs
# (guests, thinpool, sources, capture SOURCE DIGEST), from the workstation address only.
# Re-run after adding or changing a proxmox:// backup source: the dispatcher refuses a source whose path changed.
# Agents can register sources and commit, so the list is shown against the installed one, and nothing is installed
# until the owner confirms at the terminal or passes the approval digest of exactly what was shown (the dispatcher's
# sha256 and the source list). The dispatcher installed is the committed one (git HEAD), and root keeps every file it
# installs from or submits as evidence in its own 0700 work directory.
set -euo pipefail
approved=""
case "$#:${1:-}" in
  2:--yes) approved="$2" ;;
  0:) ;;
  *) echo "usage: install.sh [--yes DIGEST]" >&2; exit 2 ;;
esac
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
[[ $FROM =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "SUMMITFLOW_PVE_FROM must be one IPv4 address" >&2; exit 1; }
# One public ed25519 key, with no options: anything else (a second line, an options prefix) would add a key to root's
# authorized_keys without restrict, from= and command=. The PVE side checks the whole line again.
KEY_RE='^(ssh-ed25519 [A-Za-z0-9+/]{68})( [^[:cntrl:]]*)?$'

work="$(mktemp -d)"; chmod 700 "$work"  # Root's own when run as root: nothing an agent can swap between show and install.
rid=""; finished=0
receipt() { python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from nightshift.installs import main; raise SystemExit(main(sys.argv[2:]))' \
  /usr/local/lib/nightshift-exec/current "$@"; }
trap '[ -z "$rid" ] || [ "$finished" = 1 ] || receipt finish "$rid" --failed || true; rm -rf "$work"' EXIT

# shellcheck disable=SC2016  # expanded by the admin shell
uv_bin="$(as_admin sh -c 'command -v uv || printf %s "$HOME/.local/bin/uv"')"
if [ -n "$(as_admin git -C "$ROOT" status --porcelain -- scripts/pve-backup)" ]; then
  echo "scripts/pve-backup has uncommitted changes; only the committed dispatcher is installed" >&2; exit 1
fi
head="$(as_admin git -C "$ROOT" rev-parse HEAD)"
as_admin git -C "$ROOT" show "$head:scripts/pve-backup/summitflow-pve-backup" > "$work/dispatcher"
sha256() { python3 -I -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"; }
dispatcher_sha="$(sha256 "$work/dispatcher")"
echo "Dispatcher: scripts/pve-backup/summitflow-pve-backup at $head, sha256 $dispatcher_sha"

(cd "$ROOT/backend" && as_admin "$uv_bin" run --quiet python -m app.tasks.backup_proxmox dispatcher-sources "$PVE") > "$work/built.json"
# Canonical bytes, so the approval digest names the list and not its formatting.
python3 -I -c 'import json, sys; json.dump(json.load(open(sys.argv[1])), sys.stdout, indent=1, sort_keys=True); print()' \
  "$work/built.json" > "$work/sources.json"
# The new key reaches only the dispatcher (from here: what is installed now; at the end: the proof).
check=(ssh -F /dev/null -i "$KEY" -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes
  -o "UserKnownHostsFile=$admin_home/.ssh/known_hosts" "root@$(as_admin ssh -G "$PVE" | awk '$1 == "hostname" {print $2}')")
if [ -f "$KEY" ]; then as_admin "${check[@]}" sources > "$work/installed.json" 2>/dev/null || true; fi
echo "Sources this key may capture on $PVE (+ new, ~ changed, - removed):"
changed=0
python3 -I - "$work/installed.json" "$work/sources.json" <<'PY' || changed=$?
import json, sys
try:
    installed = json.load(open(sys.argv[1]))
    installed = installed if isinstance(installed, dict) else {}
except (OSError, ValueError):
    installed = {}
wanted = json.load(open(sys.argv[2]))
def show(mark, name, item):
    files = item.get("files") or {}
    print("  %s %-28s %-6s %-5s %s" % (mark, name, item.get("kind"), item.get("vmid") or "", " ".join(files.get("paths", []))))
for name in sorted(set(installed) | set(wanted)):
    if name not in wanted:
        show("-", name, installed[name])
    else:
        show(" " if installed.get(name) == wanted[name] else ("~" if name in installed else "+"), name, wanted[name])
sys.exit(0 if installed == wanted else 3)
PY
[ "$changed" = 0 ] || [ "$changed" = 3 ] || { echo "cannot read the source list SummitFlow built" >&2; exit 1; }
{ printf 'dispatcher %s\n' "$dispatcher_sha"; cat "$work/sources.json"; } > "$work/approval"
digest="$(sha256 "$work/approval")"
echo "Approval digest: $digest (this dispatcher and this source list)"
if [ -n "$approved" ]; then
  [ "$approved" = "$digest" ] || { echo "the dispatcher or source list is not the one approved ($approved); nothing installed" >&2; exit 1; }
else
  [ -t 0 ] || { echo "review the dispatcher and list above; to install them, re-run with --yes $digest" >&2; exit 1; }
  read -r -p "Install this dispatcher and source list on $PVE? [y/N] " answer
  [ "$answer" = y ] || [ "$answer" = Y ] || { echo "nothing installed" >&2; exit 1; }
fi

if [ ! -f "$KEY" ]; then
  as_admin rm -f "$KEY.new" "$KEY.new.pub"
  as_admin ssh-keygen -q -t ed25519 -N '' -C summitflow-pve-backup -f "$KEY.new"
  private="$KEY.new"
else
  private="$KEY"
fi
# Derived from the private key, never read from the .pub file next to it.
public="$(as_admin ssh-keygen -y -f "$private")"
[[ $public =~ $KEY_RE ]] || { echo "$private does not hold exactly one ed25519 key; nothing installed" >&2; exit 1; }
line="restrict,from=\"$FROM\",command=\"/usr/local/sbin/summitflow-pve-backup\" ${BASH_REMATCH[1]} summitflow-pve-backup"

if [ "$(id -u)" = 0 ] && [ -d /usr/local/lib/nightshift-exec/current/nightshift ]; then
  rid=$(receipt begin summitflow-pve-backup --repo "$ROOT" \
    --expect "pve=/usr/local/sbin/summitflow-pve-backup" --expect "pve=/etc/summitflow-pve-backup/*")
fi

# One session: ssh re-splits remote arguments, so the files and the key line travel base64-encoded.
dispatcher_b64="$(base64 -w0 < "$work/dispatcher")"
sources_b64="$(base64 -w0 < "$work/sources.json")"
line_b64="$(printf '%s' "$line" | base64 -w0)"
[ -n "$dispatcher_b64" ] && [ -n "$sources_b64" ] || { echo "nothing to install" >&2; exit 1; }
as_admin ssh "$PVE" bash -s -- "$dispatcher_b64" "$sources_b64" "$line_b64" > "$work/pve-install.out" <<'REMOTE'
set -euo pipefail
line="$(printf '%s' "$3" | base64 -d)"
re='^restrict,from="[0-9.]+",command="/usr/local/sbin/summitflow-pve-backup" ssh-ed25519 [A-Za-z0-9+/]{68} summitflow-pve-backup$'
[[ $line =~ $re ]] || { echo "refusing a malformed summitflow-pve-backup key line; nothing installed" >&2; exit 1; }
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
as_admin "${check[@]}" guests > /dev/null && echo "key answers: guests"
if as_admin "${check[@]}" id 2>/dev/null; then echo "the key ran a shell command; remove its line from $PVE:/root/.ssh/authorized_keys" >&2; exit 1; fi
echo "key refuses other commands"
