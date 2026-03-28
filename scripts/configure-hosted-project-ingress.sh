#!/usr/bin/env bash
set -euo pipefail

CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
CADDY_CONFIG="${CADDY_CONFIG:-/etc/caddy/Caddyfile}"
CADDY_ENV_FILE="${CADDY_ENV_FILE:-/etc/caddy/env}"
SITE_HOSTNAME="${SITE_HOSTNAME:-}"
UPSTREAM="${UPSTREAM:-}"
REMOVE_SITE_HOSTNAME="${REMOVE_SITE_HOSTNAME:-}"
REMOVE_API_HOSTNAME="${REMOVE_API_HOSTNAME:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

if [[ -z "$SITE_HOSTNAME" || -z "$UPSTREAM" ]]; then
  echo "SITE_HOSTNAME and UPSTREAM are required." >&2
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

update_cloudflared() {
  python3 - "$CLOUDFLARED_CONFIG" "$SITE_HOSTNAME" "$UPSTREAM" "$REMOVE_SITE_HOSTNAME" "$REMOVE_API_HOSTNAME" <<'PY'
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
site_hostname = sys.argv[2]
upstream = sys.argv[3]
remove_site_hostname = sys.argv[4]
remove_api_hostname = sys.argv[5]
text = config_path.read_text()

site_block = f"  - hostname: {site_hostname}\n    service: http://{upstream}\n"
fallback = "  - service: http_status:404\n"

def strip_block(source: str, hostname: str) -> str:
    if not hostname:
        return source
    pattern = re.compile(
        rf"(?ms)^  - hostname: {re.escape(hostname)}\n(?:    .*?\n)+?(?=  - hostname:|  - service: http_status:404\n|\Z)"
    )
    return pattern.sub("", source)

for hostname in (remove_site_hostname, remove_api_hostname, site_hostname):
    text = strip_block(text, hostname)

if fallback not in text:
    raise SystemExit("Could not find fallback ingress rule in cloudflared config")

text = text.replace(fallback, site_block + fallback, 1)
config_path.write_text(text)
PY
}

update_caddy() {
  python3 - "$CADDY_CONFIG" "$SITE_HOSTNAME" "$UPSTREAM" "$REMOVE_SITE_HOSTNAME" "$REMOVE_API_HOSTNAME" <<'PY'
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
site_hostname = sys.argv[2]
upstream = sys.argv[3]
remove_site_hostname = sys.argv[4]
remove_api_hostname = sys.argv[5]
text = config_path.read_text()

def matcher_name(hostname: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "", hostname).lower() or "site"

def strip_handle(lines: list[str], hostname: str) -> list[str]:
    if not hostname:
        return lines
    host_pattern = re.compile(
        rf"^\t@(?P<name>[A-Za-z0-9_-]+) host {re.escape(hostname)}\s*$"
    )

    while True:
        match_index = None
        match_name = None
        for index, line in enumerate(lines):
            match = host_pattern.match(line.rstrip("\n"))
            if match:
                match_index = index
                match_name = match.group("name")
                break

        if match_index is None or match_name is None:
            return lines

        handle_index = match_index + 1
        if handle_index >= len(lines):
            return lines[:match_index]

        expected_handle = f"\thandle @{match_name} {{"
        if lines[handle_index].rstrip("\n") != expected_handle:
            return lines[:match_index] + lines[match_index + 1 :]

        brace_depth = lines[handle_index].count("{") - lines[handle_index].count("}")
        end_index = handle_index
        while brace_depth > 0 and end_index + 1 < len(lines):
            end_index += 1
            brace_depth += lines[end_index].count("{") - lines[end_index].count("}")

        del lines[match_index : end_index + 1]

        while match_index < len(lines) and lines[match_index].strip() == "":
            del lines[match_index]

lines = text.splitlines(keepends=True)
for hostname in (remove_site_hostname, remove_api_hostname, site_hostname):
    lines = strip_handle(lines, hostname)

block_name = matcher_name(site_hostname)
block = (
    f"\n\t@{block_name} host {site_hostname}\n"
    f"\thandle @{block_name} {{\n"
    f"\t\treverse_proxy {upstream}\n"
    f"\t}}\n"
)
fallback_index = None
for index, line in enumerate(lines):
    if line.rstrip("\n") == "\thandle {":
        fallback_index = index
        break

if fallback_index is None:
    raise SystemExit("Could not find wildcard fallback handle block in Caddyfile")

lines.insert(fallback_index, block)
config_path.write_text("".join(lines))
PY
}

backup_file "$CLOUDFLARED_CONFIG"
update_cloudflared
cloudflared --config "$CLOUDFLARED_CONFIG" tunnel ingress validate
systemctl restart cloudflared
systemctl --no-pager --lines=20 status cloudflared

backup_file "$CADDY_CONFIG"
update_caddy
if [[ -f "$CADDY_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CADDY_ENV_FILE"
  set +a
fi
caddy validate --config "$CADDY_CONFIG"
systemctl restart caddy
systemctl --no-pager --lines=20 status caddy

echo "Hosted ingress configured: $SITE_HOSTNAME -> $UPSTREAM"
