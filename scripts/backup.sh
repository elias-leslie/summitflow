#!/bin/bash
#
# Universal Backup Script
# Creates compressed backup archive and transfers to SMB share
# Works for any project - auto-detects project from PWD/git root
#
# Usage:
#   ./scripts/backup.sh              # Full backup (SMB only)
#   ./scripts/backup.sh --keep-local # Full backup + keep local copy
#   ./scripts/backup.sh --quick      # Skip DB dump (use existing)
#   ./scripts/backup.sh --local      # Local only (no transfer)
#   ./scripts/backup.sh --status     # Show status only
#
# Destination: //192.168.8.128/davion-gem/project-backups/$PROJECT_NAME/
# Local backups: $PROJECT_DIR/backups/
# Retention: 30 versions (SMB), 5 versions (local)

set -eo pipefail

# Load utilities (which also detects PROJECT_DIR and PROJECT_NAME)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/backup-utils.sh"

# Local configuration - uses PROJECT_NAME from backup-utils.sh
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="${PROJECT_NAME}-${TIMESTAMP}.tar.gz"
STAGING_DIR="/tmp/${PROJECT_NAME}-backup-$$"

# Project-specific overrides (defaults)
BACKUP_TABLES=()           # Empty = full DB dump; set to table names for selective dump
BACKUP_DB_DUMP_NAME="database.sql.gz"  # Filename inside the archive
BACKUP_EXTRA_EXCLUDES=()   # Additional tar exclusions beyond BACKUP_EXCLUDES
QUICK_MODE_ENABLED=true    # Set to false to disable --quick support

# Load project-specific config if it exists
# Projects can override: BACKUP_TABLES, BACKUP_DB_DUMP_NAME,
#   BACKUP_EXTRA_EXCLUDES, QUICK_MODE_ENABLED, DB_NAME, DB_USER
if [ -f "$PROJECT_DIR/scripts/lib/backup-project.sh" ]; then
    source "$PROJECT_DIR/scripts/lib/backup-project.sh"
fi

# Parse arguments
QUICK_MODE=false
LOCAL_ONLY=false
STATUS_ONLY=false
KEEP_LOCAL=false
LOCAL_RETENTION=5
CUSTOM_RETENTION=""

while [ $# -gt 0 ]; do
    case $1 in
        --quick) QUICK_MODE=true ;;
        --local) LOCAL_ONLY=true ;;
        --keep-local) KEEP_LOCAL=true ;;
        --status) STATUS_ONLY=true ;;
        --retention-days)
            shift
            CUSTOM_RETENTION="$1"
            ;;
        --help|-h)
            echo "Usage: $0 [--quick] [--local] [--keep-local] [--retention-days N] [--status]"
            echo ""
            echo "Options:"
            if [ "$QUICK_MODE_ENABLED" = true ]; then
                echo "  --quick            Skip fresh DB dump, use existing backup"
            fi
            echo "  --local            Create archive locally only, skip SMB transfer"
            echo "  --keep-local       Upload to SMB AND keep local copy (for fast restore)"
            echo "  --retention-days N Override SMB retention days (default: $RETENTION_DAYS)"
            echo "  --status           Show backup status only"
            echo ""
            echo "Destination: //$SMB_HOST/$SMB_SHARE/$SMB_PATH"
            echo "Local backups: $PROJECT_DIR/backups/"
            echo "Retention: $RETENTION_DAYS days (SMB), $LOCAL_RETENTION copies (local)"
            if [ ${#BACKUP_TABLES[@]} -gt 0 ]; then
                echo ""
                echo "Database: Backs up selected tables only:"
                for table in "${BACKUP_TABLES[@]}"; do
                    echo "  - $table"
                done
            fi
            exit 0
            ;;
    esac
    shift
done

# Apply custom retention if provided
if [ -n "$CUSTOM_RETENTION" ]; then
    export RETENTION_DAYS="$CUSTOM_RETENTION"
fi

# Cleanup function
cleanup() {
    if [ -d "$STAGING_DIR" ]; then
        rm -rf "$STAGING_DIR"
    fi
}
trap cleanup EXIT

# Show status function
show_status() {
    echo ""
    echo "========================================"
    echo "$PROJECT_NAME Backup Status"
    echo "========================================"
    echo ""
    echo "Project: $PROJECT_NAME ($PROJECT_DIR)"
    echo ""

    if [ -f "$BACKUP_INDEX" ]; then
        local count=$(jq '.backups | length' "$BACKUP_INDEX")
        local latest=$(jq -r '.backups[0].name // "none"' "$BACKUP_INDEX")
        local latest_date=$(jq -r '.backups[0].timestamp // "never"' "$BACKUP_INDEX")
        local latest_size=$(jq -r '.backups[0].size_bytes // 0' "$BACKUP_INDEX")

        echo "Index file: $BACKUP_INDEX"
        echo "Total backups: $count"
        echo "Latest: $latest"
        echo "Date: $latest_date"
        echo "Size: $(numfmt --to=iec $latest_size 2>/dev/null || echo "$latest_size bytes")"
    else
        echo "No backup index found"
    fi

    echo ""

    if [ -f "$CREDENTIALS_FILE" ]; then
        echo "SMB Destination: //$SMB_HOST/$SMB_SHARE/$SMB_PATH"
        if test_smb_connection 2>/dev/null; then
            echo "Connection: OK"
            echo ""
            echo "Remote backups:"
            smb_list_backups | tail -5 | while read backup; do
                echo "  $backup"
            done
        else
            echo "Connection: FAILED"
        fi
    else
        echo "SMB credentials not configured"
        echo "Run backup once to set up credentials"
    fi

    echo ""
}

# Database dump function
# Returns 0 on success, 1 on failure, 2 if skipped (no database)
# Supports selective table dumps via BACKUP_TABLES array
dump_database() {
    local dump_file="$1"

    # Skip if no database credentials configured
    if [ -z "$DB_PASSWORD" ]; then
        log_warn "No database credentials found for $PROJECT_NAME - skipping DB dump"
        log_info "To enable DB backups, add ${PROJECT_NAME^^}_DB_URL to ~/.env.local"
        # Create empty placeholder so archive creation doesn't fail
        echo "-- No database for this project" | gzip > "$dump_file"
        return 2
    fi

    export PGPASSWORD="$DB_PASSWORD"

    # Build table args for selective dump
    local table_args=()
    if [ ${#BACKUP_TABLES[@]} -gt 0 ]; then
        for table in "${BACKUP_TABLES[@]}"; do
            table_args+=(-t "$table")
        done
    fi

    if [ "$QUICK_MODE" = true ] && [ "$QUICK_MODE_ENABLED" = true ]; then
        log "Quick mode: Using existing backup"
        local existing_backup="$PROJECT_DIR/backups/${PROJECT_NAME}_daily.sql.gz"

        if [ -f "$existing_backup" ]; then
            cp "$existing_backup" "$dump_file"
            log_success "Copied existing backup ($(du -h "$dump_file" | cut -f1))"
        else
            log_warn "No existing backup found, creating fresh dump..."
            pg_dump -U "$DB_USER" -h localhost "$DB_NAME" "${table_args[@]}" | gzip > "$dump_file"
        fi
    else
        if [ ${#BACKUP_TABLES[@]} -gt 0 ]; then
            log "Dumping selected tables: ${BACKUP_TABLES[*]}"
        else
            log "Creating fresh PostgreSQL dump..."
        fi
        if pg_dump -U "$DB_USER" -h localhost "$DB_NAME" "${table_args[@]}" | gzip > "$dump_file"; then
            log_success "Database dump created ($(du -h "$dump_file" | cut -f1))"
        else
            log_error "Database dump failed"
            unset PGPASSWORD
            return 1
        fi
    fi

    unset PGPASSWORD
}

# Create archive function
create_archive() {
    local archive_path="$1"
    local db_dump="$2"
    local tar_path="${archive_path%.gz}"

    log "Creating archive..."

    cd "$PROJECT_DIR"

    # Build tar exclusion args (base + project-specific extras)
    local exclude_args=()
    for ex in "${BACKUP_EXCLUDES[@]}"; do
        exclude_args+=(--exclude="$ex")
    done
    for ex in "${BACKUP_EXTRA_EXCLUDES[@]}"; do
        exclude_args+=(--exclude="$ex")
    done

    # Ensure database dump is in staging dir with correct name
    local staging_dump="$STAGING_DIR/$BACKUP_DB_DUMP_NAME"
    if [ "$db_dump" != "$staging_dump" ]; then
        cp "$db_dump" "$staging_dump"
    fi

    # Create archive of entire project (minus exclusions)
    tar --create \
        --file="$tar_path" \
        "${exclude_args[@]}" \
        --transform="s|^|${PROJECT_NAME}/|" \
        . 2>/dev/null || true

    # Add database dump to archive
    tar --append \
        --file="$tar_path" \
        --transform="s|^|${PROJECT_NAME}/|" \
        -C "$STAGING_DIR" "$BACKUP_DB_DUMP_NAME"

    # Add Neo4j memory backups for agent-hub
    if [ "$PROJECT_NAME" = "agent-hub" ] && [ -d "$PROJECT_DIR/backups/memory" ]; then
        local latest_memory_backup
        # Avoid ls | head pipeline — SIGPIPE under set -eo pipefail
        local -a _memory_dirs=()
        mapfile -t _memory_dirs < <(ls -td "$PROJECT_DIR/backups/memory"/*/ 2>/dev/null || true)
        latest_memory_backup="${_memory_dirs[0]:-}"
        if [ -n "$latest_memory_backup" ] && [ -d "$latest_memory_backup" ]; then
            log "Adding Neo4j memory backup to archive..."
            tar --append \
                --file="$tar_path" \
                --transform="s|^|${PROJECT_NAME}/|" \
                -C "$PROJECT_DIR" "backups/memory/$(basename "$latest_memory_backup")"
        fi
    fi

    # Compress
    gzip -f "$tar_path"

    log_success "Archive created: $(du -h "$archive_path" | cut -f1)"
}

# Display verification results
display_verification() {
    local verification="$1"

    local verified
    verified=$(echo "$verification" | jq -r '.verified')

    if [ "$verified" = "true" ]; then
        log_success "Archive integrity verified!"
    else
        log_error "Verification FAILED!"
        echo "$verification" | jq -r '.errors[]' | while read -r err; do
            log_error "  - $err"
        done
    fi

    echo ""
    echo "  Contents by directory:"
    echo "$verification" | jq -r '.tree | to_entries | sort_by(-.value.count) | .[] | "    \(.key): \(.value.count) files"'

    local total_files checksum
    total_files=$(echo "$verification" | jq -r '.total_files')
    checksum=$(echo "$verification" | jq -r '.checksum')
    echo "  ─────────────────────────────────────"
    echo "  Total: $total_files files"
    echo "  Checksum: $checksum"
}

# Main function
main() {
    if [ "$STATUS_ONLY" = true ]; then
        show_status
        exit 0
    fi

    echo ""
    echo "========================================"
    echo "$PROJECT_NAME Backup"
    echo "========================================"
    echo ""
    echo "Project: $PROJECT_NAME ($PROJECT_DIR)"
    if [ ${#BACKUP_TABLES[@]} -gt 0 ]; then
        echo "Tables: ${BACKUP_TABLES[*]}"
    fi
    echo ""

    # Warn if --quick was requested but not supported
    if [ "$QUICK_MODE" = true ] && [ "$QUICK_MODE_ENABLED" != true ]; then
        log_warn "Quick mode not supported for $PROJECT_NAME, running full backup"
    fi

    # Setup
    mkdir -p "$STAGING_DIR"
    local db_dump="$STAGING_DIR/$BACKUP_DB_DUMP_NAME"
    local archive_path="$STAGING_DIR/$ARCHIVE_NAME"

    # Dump database (may be skipped for projects without DB)
    local db_dump_result=0
    dump_database "$db_dump" || db_dump_result=$?

    if [ $db_dump_result -eq 1 ]; then
        log_error "Database dump failed, aborting backup"
        exit 1
    fi

    local db_size
    db_size=$(stat -c%s "$db_dump" 2>/dev/null || stat -f%z "$db_dump" 2>/dev/null || echo "0")

    # Dump Neo4j memory for agent-hub (runs memory backup)
    if [ "$PROJECT_NAME" = "agent-hub" ]; then
        dump_neo4j_memory "backup-$TIMESTAMP" || log_warn "Neo4j backup failed (continuing with PostgreSQL backup)"
    fi

    # Create archive
    log "Creating archive (this may take a moment)..."
    create_archive "$archive_path" "$db_dump"
    local archive_size
    archive_size=$(stat -c%s "$archive_path" 2>/dev/null || stat -f%z "$archive_path" 2>/dev/null || echo "0")

    # Verify archive
    log "Verifying backup..."
    local verification
    verification=$(verify_backup "$archive_path")

    display_verification "$verification"
    echo "Verification: $verification"

    # Local only mode
    if [ "$LOCAL_ONLY" = true ]; then
        local final_path="$PROJECT_DIR/backups/$ARCHIVE_NAME"
        mkdir -p "$PROJECT_DIR/backups"
        cp "$archive_path" "$final_path"
        echo ""
        log_success "Local backup created: $final_path"
        echo ""
        echo "Archive: $final_path"
        echo "Size: $(du -h "$final_path" | cut -f1)"
        return 0
    fi

    # Setup SMB credentials if needed
    ensure_smb_credentials

    # Upload with retry and local fallback
    if upload_with_retry "$archive_path" "$ARCHIVE_NAME" "$PROJECT_NAME"; then
        # Apply retention policy (only if upload succeeded)
        apply_retention

        # Keep local copy if requested
        if [ "$KEEP_LOCAL" = true ]; then
            local local_backup_dir="$PROJECT_DIR/backups"
            mkdir -p "$local_backup_dir"
            cp "$archive_path" "$local_backup_dir/$ARCHIVE_NAME"
            log_success "Local copy saved: $local_backup_dir/$ARCHIVE_NAME"

            # Apply local retention (keep only latest N)
            local local_count=$(ls -1 "$local_backup_dir"/*.tar.gz 2>/dev/null | wc -l)
            if [ "$local_count" -gt "$LOCAL_RETENTION" ]; then
                ls -1t "$local_backup_dir"/*.tar.gz | tail -n +$((LOCAL_RETENTION + 1)) | xargs rm -f
                log "Local retention applied: keeping $LOCAL_RETENTION backups"
            fi
        fi

        # Update backup index
        update_backup_index "$ARCHIVE_NAME" "$archive_size" "$db_size" "ok" "$verification"

        echo ""
        echo "========================================"
        log_success "Backup complete!"
        echo "========================================"
        echo ""
        echo "  Archive: $ARCHIVE_NAME"
        echo "  Size: $(numfmt --to=iec $archive_size 2>/dev/null || echo "$archive_size bytes")"
        echo "  DB Size: $(numfmt --to=iec $db_size 2>/dev/null || echo "$db_size bytes")"
        echo "  Location: //$SMB_HOST/$SMB_SHARE/$SMB_PATH/$ARCHIVE_NAME"
        if [ "$KEEP_LOCAL" = true ]; then
            echo "  Local: $PROJECT_DIR/backups/$ARCHIVE_NAME"
        fi
        echo ""
        echo "  Index updated: $BACKUP_INDEX"
        echo ""
    else
        # Backup saved to pending - update index with pending status
        update_backup_index "$ARCHIVE_NAME" "$archive_size" "$db_size" "pending" "$verification"

        echo ""
        echo "========================================"
        log_warn "Backup saved locally (SMB unavailable)"
        echo "========================================"
        echo ""
        echo "  Archive: $ARCHIVE_NAME"
        echo "  Size: $(numfmt --to=iec $archive_size 2>/dev/null || echo "$archive_size bytes")"
        echo "  DB Size: $(numfmt --to=iec $db_size 2>/dev/null || echo "$db_size bytes")"
        echo "  Pending: $PENDING_BACKUP_DIR/$ARCHIVE_NAME"
        echo ""
        echo "  Will auto-upload when SMB is available"
        echo ""
        # Exit 0 - backup was created successfully, just not uploaded yet
        exit 0
    fi
}

main "$@"
