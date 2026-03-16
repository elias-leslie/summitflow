#!/usr/bin/env bash
# proxmox-vm.sh — Proxmox VM lifecycle management for test infrastructure
#
# Usage:
#   proxmox-vm.sh list                          # List all VMs
#   proxmox-vm.sh snapshot <vmid> [name]        # Create snapshot
#   proxmox-vm.sh rollback <vmid> <snapshot>    # Rollback to snapshot
#   proxmox-vm.sh snapshots <vmid>              # List snapshots
#   proxmox-vm.sh clone <template> <newid> [name]  # Clone from template
#   proxmox-vm.sh start|stop|status <vmid>      # VM power control
#   proxmox-vm.sh destroy <vmid>                # Destroy VM (with confirmation)
#   proxmox-vm.sh ip <vmid>                     # Get VM IP via guest agent

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load credentials
ENV_FILE="${PROJECT_DIR}/docker/compose/.env"
if [[ -f "$ENV_FILE" ]]; then
    eval "$(grep -E '^(PROXMOX_|TEST_VM_)' "$ENV_FILE" | sed 's/^/export /')"
fi

PVE_HOST="${PROXMOX_API_URL:-https://192.168.8.233:8006}"
PVE_TOKEN="${PROXMOX_TOKEN_ID:-root@pam!automation}"
PVE_SECRET="${PROXMOX_TOKEN_SECRET:-}"
PVE_NODE="davion-gem"

# ─── API helper ──────────────────────────────────────────────────
pve() {
    local method="$1" path="$2"
    shift 2
    curl -sfk -X "$method" \
        -H "Authorization: PVEAPIToken=${PVE_TOKEN}=${PVE_SECRET}" \
        "${PVE_HOST}/api2/json${path}" "$@"
}

wait_task() {
    local upid="$1" timeout="${2:-120}"
    local start=$SECONDS
    while (( SECONDS - start < timeout )); do
        local s
        s=$(pve GET "/nodes/${PVE_NODE}/tasks/${upid}/status" | jq -r '.data.status')
        [[ "$s" == "stopped" ]] && return 0
        sleep 2
    done
    echo "TIMEOUT" >&2; return 1
}

# ─── Commands ────────────────────────────────────────────────────
cmd_list() {
    printf "%-6s %-25s %-10s %-8s %-8s\n" "VMID" "NAME" "STATUS" "RAM" "DISK"
    printf "%-6s %-25s %-10s %-8s %-8s\n" "----" "----" "------" "---" "----"
    pve GET "/nodes/${PVE_NODE}/qemu" | jq -r '.data | sort_by(.vmid)[] | [.vmid, .name, .status, (.maxmem/1024/1024|floor|tostring)+"MB", (.maxdisk/1024/1024/1024|floor|tostring)+"GB"] | @tsv' \
        | while IFS=$'\t' read -r vmid name status ram disk; do
            printf "%-6s %-25s %-10s %-8s %-8s\n" "$vmid" "$name" "$status" "$ram" "$disk"
        done
}

cmd_snapshot() {
    local vmid="$1" name="${2:-snap-$(date +%Y%m%d-%H%M%S)}"
    echo "Creating snapshot '${name}' on VM ${vmid}..."
    local upid
    upid=$(pve POST "/nodes/${PVE_NODE}/qemu/${vmid}/snapshot" \
        --data-urlencode "snapname=${name}" \
        --data-urlencode "description=Auto-snapshot $(date)" \
        | jq -r '.data')
    wait_task "$upid" 120
    echo "Done: ${name}"
}

cmd_rollback() {
    local vmid="$1" snap="$2"
    echo "Rolling back VM ${vmid} to snapshot '${snap}'..."
    local upid
    upid=$(pve POST "/nodes/${PVE_NODE}/qemu/${vmid}/snapshot/${snap}/rollback" | jq -r '.data')
    wait_task "$upid" 120
    echo "Done"
}

cmd_snapshots() {
    local vmid="$1"
    printf "%-30s %-40s %-25s\n" "NAME" "DESCRIPTION" "CREATED"
    printf "%-30s %-40s %-25s\n" "----" "-----------" "-------"
    pve GET "/nodes/${PVE_NODE}/qemu/${vmid}/snapshot" \
        | jq -r '.data[] | select(.name != "current") | [.name, .description // "-", (.snaptime // 0 | todate)] | @tsv' \
        | while IFS=$'\t' read -r name desc created; do
            printf "%-30s %-40s %-25s\n" "$name" "$desc" "$created"
        done
}

cmd_clone() {
    local template="$1" newid="$2" name="${3:-test-$(date +%Y%m%d-%H%M%S)}"
    echo "Cloning template ${template} → VM ${newid} (${name})..."
    local upid
    upid=$(pve POST "/nodes/${PVE_NODE}/qemu/${template}/clone" \
        --data-urlencode "newid=${newid}" \
        --data-urlencode "name=${name}" \
        --data-urlencode "full=1" \
        | jq -r '.data')
    wait_task "$upid" 300
    echo "Done: VM ${newid}"
}

cmd_start() {
    local vmid="$1"
    pve POST "/nodes/${PVE_NODE}/qemu/${vmid}/status/start" >/dev/null
    echo "VM ${vmid} starting"
}

cmd_stop() {
    local vmid="$1"
    pve POST "/nodes/${PVE_NODE}/qemu/${vmid}/status/stop" >/dev/null
    echo "VM ${vmid} stopping"
}

cmd_status() {
    local vmid="$1"
    pve GET "/nodes/${PVE_NODE}/qemu/${vmid}/status/current" \
        | jq -r '.data | "VM \(.vmid) (\(.name)): \(.status) | CPU: \(.cpu|.*100|floor)% | RAM: \(.mem/1024/1024|floor)MB/\(.maxmem/1024/1024|floor)MB | Uptime: \(.uptime)s"'
}

cmd_destroy() {
    local vmid="$1"
    # Safety: never destroy templates
    if [[ "$vmid" == "9000" ]]; then
        echo "ERROR: Cannot destroy template VM 9000" >&2
        exit 1
    fi
    read -rp "Destroy VM ${vmid}? This cannot be undone. [y/N] " confirm
    [[ "$confirm" =~ ^[yY]$ ]] || { echo "Aborted"; exit 0; }
    pve POST "/nodes/${PVE_NODE}/qemu/${vmid}/status/stop" &>/dev/null || true
    sleep 5
    pve DELETE "/nodes/${PVE_NODE}/qemu/${vmid}" --data-urlencode "purge=1" >/dev/null
    echo "VM ${vmid} destroyed"
}

cmd_ip() {
    local vmid="$1"
    pve GET "/nodes/${PVE_NODE}/qemu/${vmid}/agent/network-get-interfaces" \
        | jq -r '.data.result[] | select(.name != "lo") | .["ip-addresses"][] | select(.["ip-address-type"] == "ipv4") | .["ip-address"]'
}

# ─── Dispatch ────────────────────────────────────────────────────
case "${1:-help}" in
    list)       cmd_list ;;
    snapshot)   cmd_snapshot "${2:?VM ID required}" "${3:-}" ;;
    rollback)   cmd_rollback "${2:?VM ID required}" "${3:?Snapshot name required}" ;;
    snapshots)  cmd_snapshots "${2:?VM ID required}" ;;
    clone)      cmd_clone "${2:?Template ID required}" "${3:?New VM ID required}" "${4:-}" ;;
    start)      cmd_start "${2:?VM ID required}" ;;
    stop)       cmd_stop "${2:?VM ID required}" ;;
    status)     cmd_status "${2:?VM ID required}" ;;
    destroy)    cmd_destroy "${2:?VM ID required}" ;;
    ip)         cmd_ip "${2:?VM ID required}" ;;
    help|*)
        echo "Usage: proxmox-vm.sh <command> [args]"
        echo ""
        echo "Commands:"
        echo "  list                          List all VMs"
        echo "  snapshot <vmid> [name]        Create snapshot"
        echo "  rollback <vmid> <snapshot>    Rollback to snapshot"
        echo "  snapshots <vmid>              List snapshots"
        echo "  clone <tmpl> <newid> [name]   Clone from template"
        echo "  start|stop|status <vmid>      VM power control"
        echo "  destroy <vmid>                Destroy VM (with confirm)"
        echo "  ip <vmid>                     Get VM IP"
        ;;
esac
