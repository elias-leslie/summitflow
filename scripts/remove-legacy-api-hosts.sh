#!/usr/bin/env bash
set -euo pipefail

CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
CADDY_CONFIG="${CADDY_CONFIG:-/etc/caddy/Caddyfile}"
HOSTS_CSV="${HOSTS_CSV:-agentapi.summitflow.dev,devapi.summitflow.dev,portapi.summitflow.dev,atermapi.summitflow.dev}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

backup_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    local backup_path="${path}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$path" "$backup_path"
    echo "Backup written to $backup_path"
  fi
}

remove_cloudflared_hosts() {
  local config_path="$1"
  [[ -f "$config_path" ]] || return 0

  python3 - "$config_path" "$HOSTS_CSV" <<'PY'
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
hosts = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
text = config_path.read_text()

for host in hosts:
    pattern = re.compile(
        rf"(?ms)^  - hostname: {re.escape(host)}\n(?:    .*?\n)+?(?=  - hostname:|  - service: http_status:404\n|\Z)"
    )
    text = pattern.sub("", text)

config_path.write_text(text)
PY
}

remove_caddy_hosts() {
  local config_path="$1"
  [[ -f "$config_path" ]] || return 0

  python3 - "$config_path" "$HOSTS_CSV" <<'PY'
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
hosts = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
text = config_path.read_text()

for host in hosts:
    matcher_name = re.sub(r"[^a-zA-Z0-9]+", "", host).lower()
    pattern = re.compile(
        rf"\n\t@{re.escape(matcher_name)} host {re.escape(host)}\n"
        rf"\thandle @{re.escape(matcher_name)} \{{\n"
        rf"(?:\t\t.*\n)+?"
        rf"\t\}}\n",
        re.S,
    )
    text = pattern.sub("\n", text)

config_path.write_text(text)
PY
}

echo "Removing legacy API hosts: ${HOSTS_CSV}"

backup_file "$CLOUDFLARED_CONFIG"
remove_cloudflared_hosts "$CLOUDFLARED_CONFIG"

if command -v cloudflared >/dev/null 2>&1 && [[ -f "$CLOUDFLARED_CONFIG" ]]; then
  cloudflared --config "$CLOUDFLARED_CONFIG" tunnel ingress validate
  systemctl restart cloudflared
  systemctl --no-pager --lines=20 status cloudflared
fi

backup_file "$CADDY_CONFIG"
remove_caddy_hosts "$CADDY_CONFIG"

if command -v caddy >/dev/null 2>&1 && [[ -f "$CADDY_CONFIG" ]]; then
  caddy validate --config "$CADDY_CONFIG"
  systemctl restart caddy
  systemctl --no-pager --lines=20 status caddy
fi

echo "Legacy API host cleanup complete."
