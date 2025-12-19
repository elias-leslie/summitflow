#!/bin/bash
#
# Backup Pending Upload Script
# Uploads any backups that failed to upload due to SMB unavailability
#
# This script is run periodically by systemd timer to ensure backups
# are uploaded once the SMB destination becomes available.
#
# Usage:
#   ./scripts/backup-pending-upload.sh           # Upload all pending
#   ./scripts/backup-pending-upload.sh --status  # Show pending backups
#

set -eo pipefail

# Load utilities (uses summitflow's backup-utils.sh as the canonical source)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/backup-utils.sh"

# Parse arguments
STATUS_ONLY=false
for arg in "$@"; do
    case $arg in
        --status) STATUS_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--status]"
            echo ""
            echo "Options:"
            echo "  --status  Show pending backups without uploading"
            echo ""
            echo "Pending directory: $PENDING_BACKUP_DIR"
            exit 0
            ;;
    esac
done

# Show status
show_pending_status() {
    echo ""
    echo "========================================"
    echo "Pending Backup Status"
    echo "========================================"
    echo ""

    if [ ! -d "$PENDING_BACKUP_DIR" ]; then
        echo "Pending directory: $PENDING_BACKUP_DIR (not created yet)"
        echo "No pending backups"
        echo ""
        return 0
    fi

    local pending_files=$(find "$PENDING_BACKUP_DIR" -name "*.tar.gz" 2>/dev/null)

    if [ -z "$pending_files" ]; then
        echo "Pending directory: $PENDING_BACKUP_DIR"
        echo "No pending backups"
        echo ""
        return 0
    fi

    echo "Pending directory: $PENDING_BACKUP_DIR"
    echo ""

    local count=0
    local total_size=0

    for archive in $pending_files; do
        local archive_name=$(basename "$archive")
        local meta_file="${archive}.meta"
        local size=$(stat -c%s "$archive" 2>/dev/null || echo "0")
        total_size=$((total_size + size))
        ((count++))

        echo "  $archive_name"
        echo "    Size: $(numfmt --to=iec $size 2>/dev/null || echo "$size bytes")"

        if [ -f "$meta_file" ]; then
            local project=$(jq -r '.project' "$meta_file")
            local created=$(jq -r '.created_at' "$meta_file")
            local retries=$(jq -r '.retry_count' "$meta_file")
            echo "    Project: $project"
            echo "    Created: $created"
            echo "    Retries: $retries"
        fi
        echo ""
    done

    echo "────────────────────────────────────────"
    echo "Total: $count backup(s), $(numfmt --to=iec $total_size 2>/dev/null || echo "$total_size bytes")"
    echo ""

    # Check SMB status
    echo "SMB Status:"
    if test_smb_connection_quiet; then
        echo "  Connection: OK"
        echo "  Run without --status to upload pending backups"
    else
        echo "  Connection: UNAVAILABLE"
        echo "  Backups will be uploaded when SMB becomes available"
    fi
    echo ""
}

# Main
main() {
    if [ "$STATUS_ONLY" = true ]; then
        show_pending_status
        exit 0
    fi

    echo ""
    echo "========================================"
    echo "Uploading Pending Backups"
    echo "========================================"
    echo ""

    # Ensure credentials exist
    if [ ! -f "$CREDENTIALS_FILE" ]; then
        log_error "SMB credentials not configured at $CREDENTIALS_FILE"
        exit 1
    fi

    upload_pending_backups

    echo ""
}

main "$@"
