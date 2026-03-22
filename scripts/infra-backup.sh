#!/bin/bash
#
# Infrastructure Backup Script
# Creates pg_dumpall + config files backup and transfers to SMB
# Designed to be called by backup_infra.py (same pattern as backup.sh)
#
# Usage:
#   ./scripts/infra-backup.sh [--keep-local] [--retention-days N]
#
# Output markers (parsed by Python):
#   Size: <total_size>
#   DB Size: <db_size>
#   Location: <smb_path>
#   Archive: <filename>
#   Pending: <local_path>
#   Verification: <json>

set -eo pipefail

# Load utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Override project detection — this is infrastructure, not a project
export PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
export PROJECT_NAME="infrastructure"
export BACKUP_DB_DUMP_NAME="pgdumpall.sql.gz"
export BACKUP_EXPECTS_DATABASE="true"

source "$SCRIPT_DIR/lib/backup-utils.sh"

# Override SMB path for infrastructure backups
export SMB_PATH="project-backups/infrastructure"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="infrastructure-${TIMESTAMP}.tar.gz"
STAGING_DIR="/tmp/infrastructure-backup-$$"

# Parse arguments
KEEP_LOCAL=false
CUSTOM_RETENTION=""

while [ $# -gt 0 ]; do
    case $1 in
        --keep-local) KEEP_LOCAL=true ;;
        --retention-days)
            shift
            CUSTOM_RETENTION="$1"
            ;;
    esac
    shift
done

if [ -n "$CUSTOM_RETENTION" ]; then
    export RETENTION_DAYS="$CUSTOM_RETENTION"
fi

cleanup() {
    [ -d "$STAGING_DIR" ] && rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

main() {
    echo ""
    echo "========================================"
    echo "Infrastructure Backup"
    echo "========================================"
    echo ""

    mkdir -p "$STAGING_DIR/configs"

    # ── pg_dumpall ──
    local db_dump="$STAGING_DIR/$BACKUP_DB_DUMP_NAME"
    local pg_user="${PGUSER:-admin}"
    local pg_host="${PGHOST:-localhost}"

    log "Creating pg_dumpall..."

    # Try Docker container first — check compose project is running, fall back to direct connection
    local pg_container="${POSTGRES_CONTAINER:-}"
    local use_docker=false

    if [ -S /var/run/docker.sock ]; then
        # Prefer compose project-aware detection
        if docker compose -p summitflow-stack ps --status running -q 2>/dev/null | grep -q .; then
            if [ -z "$pg_container" ]; then
                pg_container=$(docker compose -p summitflow-stack ps --format '{{.Name}}' postgres 2>/dev/null | head -1)
            fi
        fi
        # Fallback to label-based detection
        if [ -z "$pg_container" ]; then
            pg_container=$(docker ps --filter "label=com.docker.compose.service=postgres" --format "{{.Names}}" 2>/dev/null | head -1)
        fi
        [ -n "$pg_container" ] && use_docker=true
    fi

    if [ "$use_docker" = true ]; then
        log "Using Docker container: $pg_container"
        if docker exec "$pg_container" pg_dumpall -U "$pg_user" 2>/dev/null | gzip > "$db_dump"; then
            log_success "pg_dumpall complete ($(du -h "$db_dump" | cut -f1))"
        else
            log_error "pg_dumpall via Docker failed"
            exit 1
        fi
    else
        log "Using direct pg_dumpall (host=$pg_host user=$pg_user)"
        if PGPASSWORD="${PGPASSWORD:-}" pg_dumpall -U "$pg_user" -h "$pg_host" 2>/dev/null | gzip > "$db_dump"; then
            log_success "pg_dumpall complete ($(du -h "$db_dump" | cut -f1))"
        else
            log_error "pg_dumpall failed (check PGUSER/PGPASSWORD/PGHOST)"
            exit 1
        fi
    fi

    local db_size
    db_size=$(stat -c%s "$db_dump" 2>/dev/null || stat -f%z "$db_dump" 2>/dev/null || echo "0")

    # ── Collect config files ──
    log "Collecting configuration files..."

    # .env.local (global secrets)
    [ -f "$HOME/.env.local" ] && cp "$HOME/.env.local" "$STAGING_DIR/configs/env.local"

    # Docker compose env
    local compose_env="$PROJECT_DIR/docker/compose/.env"
    [ -f "$compose_env" ] && cp "$compose_env" "$STAGING_DIR/configs/compose-env"

    # SMB credentials (if present)
    [ -f "$HOME/.smbcredentials" ] && cp "$HOME/.smbcredentials" "$STAGING_DIR/configs/smbcredentials"

    # Hatchet config (small, on-disk, contains signing keys needed for recovery)
    local hatchet_dir="$PROJECT_DIR/docker/compose/hatchet-config"
    if [ -d "$hatchet_dir" ]; then
        cp -r "$hatchet_dir" "$STAGING_DIR/configs/hatchet-config"
        log_success "Hatchet config collected"
    else
        log_warn "Hatchet config dir not found: $hatchet_dir"
    fi

    # ── Redis state ──
    log "Exporting Redis state..."
    local redis_dump="$STAGING_DIR/configs/redis-dump.rdb"
    local redis_host="${REDIS_HOST:-localhost}"
    local redis_port="${REDIS_PORT:-6379}"

    if redis-cli -h "$redis_host" -p "$redis_port" --rdb "$redis_dump" 2>/dev/null; then
        log_success "Redis dump complete ($(du -h "$redis_dump" | cut -f1))"
    else
        log_warn "Redis dump failed or Redis not available — skipping"
    fi

    local config_count
    config_count=$(find "$STAGING_DIR/configs" -type f 2>/dev/null | wc -l | tr -d ' ')
    log_success "Collected $config_count config file(s)"

    # ── Create archive ──
    log "Creating archive..."
    local archive_path="$STAGING_DIR/$ARCHIVE_NAME"
    local tar_path="${archive_path%.gz}"

    cd "$STAGING_DIR"
    if ! tar --create --file="$tar_path" \
        --transform="s|^|infrastructure/|" \
        "$BACKUP_DB_DUMP_NAME" configs/ 2>/dev/null; then
        log_error "Failed to create tar archive"
        exit 1
    fi

    gzip -f "$tar_path"
    log_success "Archive created: $(du -h "$archive_path" | cut -f1)"

    local archive_size
    archive_size=$(stat -c%s "$archive_path" 2>/dev/null || stat -f%z "$archive_path" 2>/dev/null || echo "0")

    # ── Verify ──
    log "Verifying backup..."
    local verification
    verification=$(verify_backup "$archive_path")

    echo "Verification: $verification"

    # ── Upload or local ──
    ensure_smb_credentials

    if upload_with_retry "$archive_path" "$ARCHIVE_NAME" "infrastructure"; then
        apply_retention

        if [ "$KEEP_LOCAL" = true ]; then
            local local_dir="$PROJECT_DIR/backups/infrastructure"
            mkdir -p "$local_dir"
            cp "$archive_path" "$local_dir/$ARCHIVE_NAME"
            log_success "Local copy saved: $local_dir/$ARCHIVE_NAME"
        fi

        echo ""
        echo "========================================"
        log_success "Infrastructure backup complete!"
        echo "========================================"
        echo ""
        echo "  Archive: $ARCHIVE_NAME"
        echo "  Size: $(numfmt --to=iec $archive_size 2>/dev/null || echo "$archive_size bytes")"
        echo "  DB Size: $(numfmt --to=iec $db_size 2>/dev/null || echo "$db_size bytes")"
        echo "  Location: //$SMB_HOST/$SMB_SHARE/$SMB_PATH/$ARCHIVE_NAME"
        echo ""
    else
        echo ""
        echo "========================================"
        log_warn "Infrastructure backup saved locally (SMB unavailable)"
        echo "========================================"
        echo ""
        echo "  Archive: $ARCHIVE_NAME"
        echo "  Size: $(numfmt --to=iec $archive_size 2>/dev/null || echo "$archive_size bytes")"
        echo "  DB Size: $(numfmt --to=iec $db_size 2>/dev/null || echo "$db_size bytes")"
        echo "  Pending: $PENDING_BACKUP_DIR/$ARCHIVE_NAME"
        echo ""
        exit 0
    fi
}

main "$@"
