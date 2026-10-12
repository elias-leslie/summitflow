#!/usr/bin/env bash
# Per-session Chrome pool on the browser VM. The workstation calls this over SSH:
#   st-browser-session ensure KEY   start (or reuse) KEY's Chrome; prints {"key","port"}
#   st-browser-session stop KEY     stop KEY's Chrome; its profile and port are kept
#   st-browser-session status       list instances as JSON lines
#   st-browser-session gc           stop instances with no CDP client for ST_BROWSER_SESSION_IDLE_MIN
# Each KEY runs st-browser-session@KEY.service with its own profile and its own CDP
# port, forwarded only to the operator workstation like the shared 9222 service.
set -euo pipefail

BROWSER_ROOT="${ST_BROWSER_ROOT:-$HOME/.local/share/st-browser}"
CONFIG_DIR="${ST_BROWSER_CONFIG_DIR:-$HOME/.config/st-browser}"
SESSION_DIR="$CONFIG_DIR/sessions"
PORT_FIRST="${ST_BROWSER_SESSION_PORT_FIRST:-9300}"
PORT_LAST="${ST_BROWSER_SESSION_PORT_LAST:-9339}"
# Chrome binds its debug port to loopback; socat forwards PORT to PORT+offset.
DEBUG_OFFSET=100
IDLE_MIN="${ST_BROWSER_SESSION_IDLE_MIN:-30}"

die() { echo "st-browser-session: $*" >&2; exit 2; }

valid_key() { [[ "$1" =~ ^[a-z0-9]{8,32}$ ]] || die "invalid session key"; }

unit() { echo "st-browser-session@$1.service"; }

port_of() { [[ -f "$SESSION_DIR/$1.env" ]] && sed -n 's/^ST_BROWSER_CDP_PORT=//p' "$SESSION_DIR/$1.env" || true; }

allocate() {
  local key="$1" port used
  used="$(sed -n 's/^ST_BROWSER_CDP_PORT=//p' "$SESSION_DIR"/*.env 2>/dev/null | sort -u || true)"
  for ((port = PORT_FIRST; port <= PORT_LAST; port++)); do
    if ! grep -qx "$port" <<<"$used"; then
      cat >"$SESSION_DIR/$key.env" <<EOF
ST_BROWSER_CDP_PORT=$port
ST_BROWSER_CHROME_DEBUG_PORT=$((port + DEBUG_OFFSET))
ST_BROWSER_CHROME_PROFILE=$BROWSER_ROOT/profiles/sessions/$key
ST_BROWSER_LOG_NAME=session-$key
EOF
      echo "$port"
      return
    fi
  done
  die "no free session port in $PORT_FIRST-$PORT_LAST; stop idle sessions first"
}

ready() {
  local port="$1"
  curl -fsS --max-time 1 "http://127.0.0.1:$((port + DEBUG_OFFSET))/json/version" >/dev/null 2>&1 &&
    ss -Hltn "sport = :$port" | grep -q .
}

ensure() {
  local key="$1" port
  valid_key "$key"
  mkdir -p "$SESSION_DIR"
  exec 9>"$SESSION_DIR/.lock"
  flock 9
  port="$(port_of "$key")"
  [[ -n "$port" ]] || port="$(allocate "$key")"
  rm -f "$SESSION_DIR/$key.idle"
  systemctl --user start "$(unit "$key")"
  for _ in $(seq 1 80); do
    ready "$port" && break
    sleep 0.25
  done
  ready "$port" || die "session $key did not become ready on port $port"
  printf '{"key":"%s","port":%s}\n' "$key" "$port"
}

stop() {
  valid_key "$1"
  systemctl --user stop "$(unit "$1")" 2>/dev/null || true
  # The Chrome wrapper exits nonzero when stopped; that is not a failure here.
  systemctl --user reset-failed "$(unit "$1")" 2>/dev/null || true
  rm -f "$SESSION_DIR/$1.idle"
  printf '{"key":"%s","stopped":true}\n' "$1"
}

status() {
  local env key state
  for env in "$SESSION_DIR"/*.env; do
    [[ -e "$env" ]] || continue
    key="$(basename "$env" .env)"
    state="$(systemctl --user is-active "$(unit "$key")" 2>/dev/null || true)"
    printf '{"key":"%s","port":%s,"state":"%s"}\n' "$key" "$(port_of "$key")" "$state"
  done
}

gc() {
  local env key port now since
  now="$(date +%s)"
  for env in "$SESSION_DIR"/*.env; do
    [[ -e "$env" ]] || continue
    key="$(basename "$env" .env)"
    if ! systemctl --user is-active --quiet "$(unit "$key")"; then
      rm -f "$SESSION_DIR/$key.idle"
      continue
    fi
    port="$(port_of "$key")"
    # The workstation daemon holds a CDP connection for as long as the session runs.
    if ss -Htn state established "sport = :$port" | grep -q .; then
      rm -f "$SESSION_DIR/$key.idle"
      continue
    fi
    if [[ ! -f "$SESSION_DIR/$key.idle" ]]; then
      echo "$now" >"$SESSION_DIR/$key.idle"
      continue
    fi
    since="$(cat "$SESSION_DIR/$key.idle")"
    if ((now - since >= IDLE_MIN * 60)); then
      echo "stopping idle session $key (port $port)"
      stop "$key" >/dev/null
    fi
  done
}

case "${1:-}" in
  ensure) [[ $# -eq 2 ]] || die "usage: ensure KEY"; ensure "$2" ;;
  stop) [[ $# -eq 2 ]] || die "usage: stop KEY"; stop "$2" ;;
  status) status ;;
  gc) gc ;;
  *) die "usage: st-browser-session ensure KEY | stop KEY | status | gc" ;;
esac
