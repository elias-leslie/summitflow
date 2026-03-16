#!/usr/bin/env bash
# test-install.sh — Automated install.sh validation on Proxmox test VM
# Clones from template, runs install, verifies health, optionally destroys
#
# Usage:
#   test-install.sh                    # Full cycle: clone → install → verify → destroy
#   test-install.sh --keep             # Keep VM after test (for debugging)
#   test-install.sh --vm-id 101        # Use specific VM ID
#   test-install.sh --existing         # Test on existing VM 100 (no clone/destroy)

set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load credentials from .env
ENV_FILE="${PROJECT_DIR}/docker/compose/.env"
if [[ -f "$ENV_FILE" ]]; then
    eval "$(grep -E '^(PROXMOX_|TEST_VM_)' "$ENV_FILE" | sed 's/^/export /')"
fi

PVE_HOST="${PROXMOX_API_URL:-https://192.168.8.233:8006}"
PVE_TOKEN="${PROXMOX_TOKEN_ID:-root@pam!automation}"
PVE_SECRET="${PROXMOX_TOKEN_SECRET:-}"
PVE_NODE="davion-gem"
TEMPLATE_ID="${PROXMOX_TEST_TEMPLATE:-9000}"
DEFAULT_VM_ID=101
VM_NAME="install-test-$(date +%Y%m%d-%H%M%S)"
KEEP=false
EXISTING=false
VM_ID=""

# ─── Parse args ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep) KEEP=true; shift ;;
        --vm-id) VM_ID="$2"; shift 2 ;;
        --existing) EXISTING=true; VM_ID="${PROXMOX_TEST_VM:-100}"; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

[[ -z "$VM_ID" ]] && VM_ID="$DEFAULT_VM_ID"

# ─── Proxmox API helper ─────────────────────────────────────────
pve_api() {
    local method="$1" path="$2"
    shift 2
    curl -sfk -X "$method" \
        -H "Authorization: PVEAPIToken=${PVE_TOKEN}=${PVE_SECRET}" \
        "${PVE_HOST}/api2/json${path}" "$@"
}

wait_for_task() {
    local upid="$1" timeout="${2:-120}"
    local start=$SECONDS
    while (( SECONDS - start < timeout )); do
        local status
        status=$(pve_api GET "/nodes/${PVE_NODE}/tasks/${upid}/status" | jq -r '.data.status')
        [[ "$status" == "stopped" ]] && return 0
        sleep 2
    done
    echo "  TIMEOUT waiting for task $upid" >&2
    return 1
}

wait_for_ssh() {
    local host="$1" timeout="${2:-180}"
    local start=$SECONDS
    echo -n "  Waiting for SSH on ${host}..."
    while (( SECONDS - start < timeout )); do
        if ssh -o ConnectTimeout=3 -o BatchMode=yes -o StrictHostKeyChecking=no \
            "kasadis@${host}" 'echo ok' &>/dev/null; then
            echo " ready ($(( SECONDS - start ))s)"
            return 0
        fi
        sleep 3
    done
    echo " TIMEOUT"
    return 1
}

# ─── Cleanup handler ────────────────────────────────────────────
cleanup() {
    if [[ "$EXISTING" == true ]] || [[ "$KEEP" == true ]]; then
        return
    fi
    if [[ -n "$VM_ID" ]]; then
        echo "Cleaning up VM ${VM_ID}..."
        pve_api POST "/nodes/${PVE_NODE}/qemu/${VM_ID}/status/stop" &>/dev/null || true
        sleep 5
        pve_api DELETE "/nodes/${PVE_NODE}/qemu/${VM_ID}" --data-urlencode "purge=1" &>/dev/null || true
        echo "  VM ${VM_ID} destroyed"
    fi
}

# ─── Main ────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════"
echo "  install.sh Validation Test"
echo "  $(date)"
echo "═══════════════════════════════════════════════════════"
echo ""

if [[ "$EXISTING" == true ]]; then
    echo "Using existing VM ${VM_ID}"
    VM_IP="${TEST_VM_HOST:-192.168.8.234}"
else
    # Clone from template
    echo "Cloning template ${TEMPLATE_ID} → VM ${VM_ID} (${VM_NAME})..."
    UPID=$(pve_api POST "/nodes/${PVE_NODE}/qemu/${TEMPLATE_ID}/clone" \
        --data-urlencode "newid=${VM_ID}" \
        --data-urlencode "name=${VM_NAME}" \
        --data-urlencode "full=1" \
        | jq -r '.data')
    echo "  Clone task: ${UPID}"
    wait_for_task "$UPID" 300

    # Start VM
    echo "Starting VM ${VM_ID}..."
    pve_api POST "/nodes/${PVE_NODE}/qemu/${VM_ID}/status/start" >/dev/null
    sleep 10

    # Discover IP via QEMU guest agent
    echo "Discovering VM IP..."
    for i in $(seq 1 30); do
        VM_IP=$(pve_api GET "/nodes/${PVE_NODE}/qemu/${VM_ID}/agent/network-get-interfaces" 2>/dev/null \
            | jq -r '.data.result[]? | select(.name != "lo") | .["ip-addresses"][]? | select(.["ip-address-type"] == "ipv4") | .["ip-address"]' \
            | head -1 || true)
        [[ -n "$VM_IP" ]] && break
        sleep 5
    done

    if [[ -z "$VM_IP" ]]; then
        echo "  ERROR: Could not discover VM IP. Using DHCP fallback."
        echo "  Check Proxmox console for the VM."
        trap cleanup EXIT
        exit 1
    fi
    echo "  VM IP: ${VM_IP}"

    trap cleanup EXIT
fi

# Wait for SSH
wait_for_ssh "$VM_IP" 180

echo ""
echo "─── Phase 1: Pre-install state ─────────────────────"
ssh "kasadis@${VM_IP}" 'echo "OS: $(lsb_release -ds 2>/dev/null || cat /etc/os-release | head -1)"; echo "Docker: $(docker --version 2>/dev/null || echo not installed)"; echo "Disk: $(df -h / | tail -1 | awk "{print \$4}") free"'

echo ""
echo "─── Phase 2: Running install.sh ────────────────────"
INSTALL_START=$SECONDS

# Get the install script from this repo (not from remote URL)
scp "${PROJECT_DIR}/docker/install.sh" "kasadis@${VM_IP}:/tmp/install.sh"
ssh "kasadis@${VM_IP}" 'chmod +x /tmp/install.sh && cd /tmp && bash install.sh 2>&1' | tee /tmp/install-test-output.log

INSTALL_ELAPSED=$(( SECONDS - INSTALL_START ))
echo ""
echo "  Install completed in ${INSTALL_ELAPSED}s"

echo ""
echo "─── Phase 3: Health verification ───────────────────"
PASS=0
FAIL=0

REMOTE_INSTALL_DIR="${INSTALL_DIR:-\$HOME/summitflow-docker}"

check_service() {
    local name="$1" url="$2"
    local status
    status=$(ssh "kasadis@${VM_IP}" "curl -sf -o /dev/null -w '%{http_code}' '${url}' 2>/dev/null" || echo "000")
    if [[ "$status" =~ ^(200|301|302)$ ]]; then
        printf "  ✓ %-20s %s\n" "$name" "$status"
        ((PASS++))
    else
        printf "  ✗ %-20s %s\n" "$name" "$status"
        ((FAIL++))
    fi
}

# Infrastructure services use native protocol checks, not HTTP
check_infra() {
    local name="$1" cmd="$2"
    local result
    result=$(ssh "kasadis@${VM_IP}" "cd ${REMOTE_INSTALL_DIR} && ${cmd}" 2>/dev/null) || result=""
    if [[ -n "$result" ]]; then
        printf "  ✓ %-20s OK\n" "$name"
        ((PASS++))
    else
        printf "  ✗ %-20s FAIL\n" "$name"
        ((FAIL++))
    fi
}

check_infra "PostgreSQL" "docker compose exec -T postgres pg_isready -U admin"
check_infra "Redis" "docker compose exec -T redis redis-cli -a \$(grep REDIS_PASSWORD .env | cut -d= -f2) ping"
check_service "Hatchet"         "http://localhost:8888"
check_service "SummitFlow API"  "http://localhost:8001/health"
check_service "SummitFlow Web"  "http://localhost:3001"
check_service "Agent Hub API"   "http://localhost:8003/health"
check_service "Agent Hub Web"   "http://localhost:3003"
check_service "Portfolio API"   "http://localhost:8000/health"
check_service "Portfolio Web"   "http://localhost:3000"

# Check docker containers
echo ""
echo "  Docker containers:"
ssh "kasadis@${VM_IP}" "cd ${REMOTE_INSTALL_DIR} && docker compose ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null" | sed 's/^/    /'

echo ""
echo "─── Phase 4: Results ───────────────────────────────"
echo "  Services passed: ${PASS}"
echo "  Services failed: ${FAIL}"
echo "  Install time:    ${INSTALL_ELAPSED}s"
echo "  VM:              ${VM_ID} (${VM_IP})"
[[ "$KEEP" == true ]] && echo "  VM kept alive (--keep)"
[[ "$EXISTING" == true ]] && echo "  Used existing VM (--existing)"

if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "  RESULT: FAIL"
    exit 1
else
    echo ""
    echo "  RESULT: PASS"
fi
