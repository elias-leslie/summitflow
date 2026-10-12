#!/usr/bin/env bash
set -euo pipefail

BROWSER_ROOT="${ST_BROWSER_ROOT:-$HOME/.local/share/st-browser}"
CONFIG_DIR="${ST_BROWSER_CONFIG_DIR:-$HOME/.config/st-browser}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER_SRC="$SCRIPT_DIR/st-browser-chrome-service.sh"
WRAPPER_DST="$BROWSER_ROOT/bin/st-browser-chrome-service.sh"
SESSION_SRC="$SCRIPT_DIR/st-browser-session.sh"
SESSION_DST="$BROWSER_ROOT/bin/st-browser-session"
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
install -m 0755 "$SESSION_SRC" "$SESSION_DST"
mkdir -p "$CONFIG_DIR/sessions"

if [[ ! -f "$ENV_FILE" ]]; then
  cat >"$ENV_FILE" <<EOF
ST_BROWSER_ROOT=$BROWSER_ROOT
ST_BROWSER_CDP_PORT=9222
ST_BROWSER_CHROME_DEBUG_PORT=9212
ST_BROWSER_HOST_RESOLVER_RULES=""
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

# Managed sessions: one Chrome per session (st-browser-session ensure KEY), each
# with its own profile and CDP port from 9300-9339. The session env file
# overrides the shared chrome.env ports and profile.
cat >"$UNIT_DIR/st-browser-session@.service" <<EOF
[Unit]
Description=ST Browser managed session %i
After=network-online.target

[Service]
Type=simple
EnvironmentFile=-$ENV_FILE
EnvironmentFile=$CONFIG_DIR/sessions/%i.env
ExecStart=$WRAPPER_DST
Restart=on-failure
RestartSec=2
EOF

cat >"$UNIT_DIR/st-browser-session-gc.service" <<EOF
[Unit]
Description=Stop ST Browser managed sessions without a CDP client

[Service]
Type=oneshot
ExecStart=$SESSION_DST gc
EOF

cat >"$UNIT_DIR/st-browser-session-gc.timer" <<EOF
[Unit]
Description=Stop idle ST Browser managed sessions

[Timer]
OnCalendar=*:0/10
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now st-browser-chrome.service st-browser-session-gc.timer
systemctl --user --no-pager --full status st-browser-chrome.service
