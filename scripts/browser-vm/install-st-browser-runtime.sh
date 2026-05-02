#!/usr/bin/env bash
set -euo pipefail

BROWSER_ROOT="${ST_BROWSER_ROOT:-$HOME/.local/share/st-browser}"
CONFIG_DIR="${ST_BROWSER_CONFIG_DIR:-$HOME/.config/st-browser}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER_SRC="$SCRIPT_DIR/st-browser-chrome-service.sh"
WRAPPER_DST="$BROWSER_ROOT/bin/st-browser-chrome-service.sh"
ENV_FILE="$CONFIG_DIR/chrome.env"
UNIT_FILE="$UNIT_DIR/st-browser-chrome.service"

mkdir -p "$BROWSER_ROOT/bin" "$CONFIG_DIR" "$UNIT_DIR"

sudo loginctl enable-linger "$USER" >/dev/null 2>&1 || true

if ! command -v socat >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq socat ca-certificates
fi

cd "$BROWSER_ROOT"
npx -y @puppeteer/browsers@latest install chrome@stable --path "$BROWSER_ROOT"

install -m 0755 "$WRAPPER_SRC" "$WRAPPER_DST"

if [[ ! -f "$ENV_FILE" ]]; then
  cat >"$ENV_FILE" <<EOF
ST_BROWSER_ROOT=$BROWSER_ROOT
ST_BROWSER_CDP_PORT=9222
ST_BROWSER_CHROME_DEBUG_PORT=9212
ST_BROWSER_HOST_RESOLVER_RULES="MAP *.summitflow.dev 192.168.8.244"
EOF
fi

cat >"$UNIT_FILE" <<EOF
[Unit]
Description=ST Browser Chrome CDP service
After=network-online.target

[Service]
Type=simple
EnvironmentFile=-$ENV_FILE
ExecStart=$WRAPPER_DST
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now st-browser-chrome.service
systemctl --user --no-pager --full status st-browser-chrome.service
