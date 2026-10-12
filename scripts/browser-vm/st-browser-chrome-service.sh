#!/usr/bin/env bash
set -euo pipefail

BROWSER_ROOT="${ST_BROWSER_ROOT:-$HOME/.local/share/st-browser}"
CHROME_BIN="${ST_BROWSER_CHROME_BIN:-}"
CDP_PORT="${ST_BROWSER_CDP_PORT:-9222}"
CHROME_DEBUG_PORT="${ST_BROWSER_CHROME_DEBUG_PORT:-9212}"
PROFILE_DIR="${ST_BROWSER_CHROME_PROFILE:-$BROWSER_ROOT/profiles/chrome}"
HOST_RESOLVER_RULES="${ST_BROWSER_HOST_RESOLVER_RULES:-}"
# CDP is full browser control: forward it only to the operator workstation.
# The PVE VM firewall applies the same allowlist in front of the guest.
CDP_ALLOW="${ST_BROWSER_CDP_ALLOW:-192.168.86.128/32}"
# Only browser pages send Origin; CDP clients (agent-browser, Playwright) do not.
# The one page origin allowed is this port's own bundled DevTools frontend, which
# `st browser watch` opens on the workstation as the live view.
if [[ -z "${ST_BROWSER_REMOTE_ALLOW_ORIGINS+set}" ]]; then
  vm_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
  ST_BROWSER_REMOTE_ALLOW_ORIGINS="${vm_ip:+http://$vm_ip:$CDP_PORT}"
fi
REMOTE_ALLOW_ORIGINS="$ST_BROWSER_REMOTE_ALLOW_ORIGINS"
LOG_DIR="$BROWSER_ROOT/logs"
LOG_NAME="${ST_BROWSER_LOG_NAME:-chrome}"

if [[ -z "$CHROME_BIN" ]]; then
  CHROME_BIN="$(find "$BROWSER_ROOT/chrome" -type f -path '*/chrome-linux64/chrome' 2>/dev/null | sort | tail -1)"
fi

if [[ -z "$CHROME_BIN" || ! -x "$CHROME_BIN" ]]; then
  echo "Chrome for Testing binary not found under $BROWSER_ROOT/chrome" >&2
  exit 127
fi

if ! command -v socat >/dev/null 2>&1; then
  echo "socat is required because Chrome binds remote debugging to localhost" >&2
  exit 127
fi

mkdir -p "$PROFILE_DIR" "$LOG_DIR"

# A profile copied or renamed from another host keeps that host's Singleton
# locks, and Chrome then refuses the profile. Nothing else uses this profile,
# because systemd runs one instance of this service.
owner="$(readlink "$PROFILE_DIR/SingletonLock" 2>/dev/null || true)"
if [[ -n "$owner" && "$owner" != "$(hostname)-"* ]]; then
  rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonSocket" "$PROFILE_DIR/SingletonCookie"
fi

chrome_pid=""
proxy_pid=""

cleanup() {
  if [[ -n "$proxy_pid" ]]; then
    kill "$proxy_pid" 2>/dev/null || true
  fi
  if [[ -n "$chrome_pid" ]]; then
    kill "$chrome_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$CHROME_BIN" \
  --headless=new \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --no-first-run \
  --no-default-browser-check \
  "--user-data-dir=$PROFILE_DIR" \
  "--remote-debugging-port=$CHROME_DEBUG_PORT" \
  ${REMOTE_ALLOW_ORIGINS:+"--remote-allow-origins=$REMOTE_ALLOW_ORIGINS"} \
  "--host-resolver-rules=$HOST_RESOLVER_RULES" \
  about:blank \
  >>"$LOG_DIR/$LOG_NAME.log" 2>&1 &
chrome_pid=$!

for _ in $(seq 1 80); do
  if curl -fsS "http://127.0.0.1:$CHROME_DEBUG_PORT/json/version" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$chrome_pid" 2>/dev/null; then
    wait "$chrome_pid"
  fi
  sleep 0.25
done

if ! curl -fsS "http://127.0.0.1:$CHROME_DEBUG_PORT/json/version" >/dev/null 2>&1; then
  echo "Chrome CDP did not become healthy on 127.0.0.1:$CHROME_DEBUG_PORT" >&2
  exit 1
fi

socat "TCP4-LISTEN:$CDP_PORT,fork,reuseaddr,range=$CDP_ALLOW" "TCP:127.0.0.1:$CHROME_DEBUG_PORT" \
  >>"$LOG_DIR/$LOG_NAME-cdp-proxy.log" 2>&1 &
proxy_pid=$!

wait -n "$chrome_pid" "$proxy_pid"
exit 1
