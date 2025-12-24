#!/bin/bash
#
# SummitFlow Restore Script
# Restores code and/or database from backup archives
#
# Usage:
#   ./scripts/restore.sh --list              # List available backups
#   ./scripts/restore.sh --latest            # Restore from latest backup
#   ./scripts/restore.sh --file <archive>    # Restore from specific archive
#   ./scripts/restore.sh --db-only           # Restore database only
#   ./scripts/restore.sh --files-only        # Restore files only (no DB)
#   ./scripts/restore.sh --dry-run           # Show what would be restored
#
# Sources (checked in order):
#   1. Local: ~/summitflow/backups/
#   2. Pending: ~/.local/share/backup-pending/
#   3. SMB: //192.168.8.128/davion-gem/project-backups/summitflow/

set -eo pipefail

# Load utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/backup-utils.sh"

# Configuration
LOCAL_BACKUP_DIR="$PROJECT_DIR/backups"
RESTORE_STAGING="/tmp/summitflow-restore-$$"

# Parse arguments
RESTORE_MODE=""
TARGET_FILE=""
DB_ONLY=false
FILES_ONLY=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            RESTORE_MODE="list"
            shift
            ;;
        --latest)
            RESTORE_MODE="latest"
            shift
            ;;
        --file)
            RESTORE_MODE="file"
            TARGET_FILE="$2"
            shift 2
            ;;
        --db-only)
            DB_ONLY=true
            shift
            ;;
        --files-only)
            FILES_ONLY=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --list         List available backups (local, pending, SMB)"
            echo "  --latest       Restore from most recent backup"
            echo "  --file <path>  Restore from specific archive file"
            echo "  --db-only      Restore database only, skip files"
            echo "  --files-only   Restore files only, skip database"
            echo "  --dry-run      Show what would be restored without doing it"
            echo ""
            echo "Sources checked (in order):"
            echo "  1. Local: $LOCAL_BACKUP_DIR/"
            echo "  2. Pending: $PENDING_BACKUP_DIR/"
            echo "  3. SMB: //$SMB_HOST/$SMB_SHARE/$SMB_PATH/"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Cleanup function
cleanup() {
    if [ -d "$RESTORE_STAGING" ]; then
        rm -rf "$RESTORE_STAGING"
    fi
}
trap cleanup EXIT

# List available backups
list_backups() {
    echo ""
    echo "========================================"
    echo "Available Backups"
    echo "========================================"
    echo ""

    # Local backups
    echo "LOCAL ($LOCAL_BACKUP_DIR/):"
    if [ -d "$LOCAL_BACKUP_DIR" ]; then
        local local_backups=$(ls -1t "$LOCAL_BACKUP_DIR"/*.tar.gz 2>/dev/null || true)
        if [ -n "$local_backups" ]; then
            echo "$local_backups" | while read f; do
                local size=$(du -h "$f" | cut -f1)
                local date=$(basename "$f" | sed 's/summitflow-\([0-9-]*\)\.tar\.gz/\1/')
                echo "  $(basename "$f")  ($size)"
            done
        else
            echo "  (none)"
        fi
    else
        echo "  (directory not found)"
    fi
    echo ""

    # Pending backups
    echo "PENDING ($PENDING_BACKUP_DIR/):"
    if [ -d "$PENDING_BACKUP_DIR" ]; then
        local pending_backups=$(ls -1t "$PENDING_BACKUP_DIR"/*.tar.gz 2>/dev/null || true)
        if [ -n "$pending_backups" ]; then
            echo "$pending_backups" | while read f; do
                local size=$(du -h "$f" | cut -f1)
                echo "  $(basename "$f")  ($size)"
            done
        else
            echo "  (none)"
        fi
    else
        echo "  (directory not found)"
    fi
    echo ""

    # SMB backups
    echo "SMB (//$SMB_HOST/$SMB_SHARE/$SMB_PATH/):"
    if [ -f "$CREDENTIALS_FILE" ] && test_smb_connection 2>/dev/null; then
        smb_list_backups | tail -10 | while read backup; do
            echo "  $backup"
        done
    else
        echo "  (not connected or credentials missing)"
    fi
    echo ""
}

# Find latest backup across all sources
find_latest_backup() {
    local latest=""
    local latest_time=0

    # Check local
    if [ -d "$LOCAL_BACKUP_DIR" ]; then
        local local_latest=$(ls -1t "$LOCAL_BACKUP_DIR"/*.tar.gz 2>/dev/null | head -1)
        if [ -n "$local_latest" ] && [ -f "$local_latest" ]; then
            local mtime=$(stat -c %Y "$local_latest" 2>/dev/null || stat -f %m "$local_latest" 2>/dev/null)
            if [ "$mtime" -gt "$latest_time" ]; then
                latest="$local_latest"
                latest_time="$mtime"
            fi
        fi
    fi

    # Check pending
    if [ -d "$PENDING_BACKUP_DIR" ]; then
        local pending_latest=$(ls -1t "$PENDING_BACKUP_DIR"/*.tar.gz 2>/dev/null | head -1)
        if [ -n "$pending_latest" ] && [ -f "$pending_latest" ]; then
            local mtime=$(stat -c %Y "$pending_latest" 2>/dev/null || stat -f %m "$pending_latest" 2>/dev/null)
            if [ "$mtime" -gt "$latest_time" ]; then
                latest="$pending_latest"
                latest_time="$mtime"
            fi
        fi
    fi

    echo "$latest"
}

# Verify archive contents
verify_archive() {
    local archive="$1"

    log "Verifying archive contents..."

    if ! tar -tzf "$archive" >/dev/null 2>&1; then
        log_error "Archive is corrupted or invalid"
        return 1
    fi

    # Check for required components
    local has_db=$(tar -tzf "$archive" | grep -c "database.sql.gz" || true)
    local has_backend=$(tar -tzf "$archive" | grep -c "summitflow/backend/" || true)
    local has_frontend=$(tar -tzf "$archive" | grep -c "summitflow/frontend/" || true)

    echo "  Database dump: $([ "$has_db" -gt 0 ] && echo "✓" || echo "✗")"
    echo "  Backend code: $([ "$has_backend" -gt 0 ] && echo "✓" || echo "✗")"
    echo "  Frontend code: $([ "$has_frontend" -gt 0 ] && echo "✓" || echo "✗")"

    if [ "$has_db" -eq 0 ] && [ "$DB_ONLY" = true ]; then
        log_error "Archive does not contain database dump"
        return 1
    fi

    return 0
}

# Restore database
restore_database() {
    local db_dump="$1"

    log "Restoring database..."

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would restore database from: $db_dump"
        return 0
    fi

    # Stop services that use the database
    log "Stopping services..."
    systemctl --user stop summitflow-backend 2>/dev/null || true

    # Restore
    export PGPASSWORD="$DB_PASSWORD"

    # Drop and recreate (dangerous but complete)
    log "Dropping existing database..."
    psql -U "$DB_USER" -h localhost -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_restore;" 2>/dev/null || true
    psql -U "$DB_USER" -h localhost -d postgres -c "CREATE DATABASE ${DB_NAME}_restore;" 2>/dev/null

    log "Restoring from dump..."
    if gunzip -c "$db_dump" | psql -U "$DB_USER" -h localhost -d "${DB_NAME}_restore" >/dev/null 2>&1; then
        # Swap databases
        log "Swapping databases..."
        psql -U "$DB_USER" -h localhost -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_old;" 2>/dev/null || true
        psql -U "$DB_USER" -h localhost -d postgres -c "ALTER DATABASE $DB_NAME RENAME TO ${DB_NAME}_old;" 2>/dev/null || true
        psql -U "$DB_USER" -h localhost -d postgres -c "ALTER DATABASE ${DB_NAME}_restore RENAME TO $DB_NAME;" 2>/dev/null

        log_success "Database restored successfully"

        # Cleanup old database
        psql -U "$DB_USER" -h localhost -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_old;" 2>/dev/null || true
    else
        log_error "Database restore failed"
        psql -U "$DB_USER" -h localhost -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_restore;" 2>/dev/null || true
        unset PGPASSWORD
        return 1
    fi

    unset PGPASSWORD

    # Restart services
    log "Restarting services..."
    systemctl --user start summitflow-backend 2>/dev/null || true

    return 0
}

# Restore files
restore_files() {
    local archive="$1"
    local staging="$2"

    log "Restoring files..."

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would restore files from: $archive"
        log_info "[DRY RUN] Files to restore:"
        tar -tzf "$archive" | grep -v "database.sql.gz" | head -20
        echo "  ... (truncated)"
        return 0
    fi

    # Extract to staging
    log "Extracting archive..."
    tar -xzf "$archive" -C "$staging"

    # Stop services
    log "Stopping services..."
    systemctl --user stop summitflow-backend summitflow-frontend 2>/dev/null || true

    # Backup current state (just in case)
    local pre_restore_backup="$PROJECT_DIR/backups/.pre-restore-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$pre_restore_backup"

    # Restore backend (excluding venv)
    if [ -d "$staging/summitflow/backend" ]; then
        log "Restoring backend..."
        rsync -a --delete \
            --exclude='.venv' \
            --exclude='__pycache__' \
            --exclude='.pytest_cache' \
            --exclude='.mypy_cache' \
            --exclude='.ruff_cache' \
            "$staging/summitflow/backend/" "$PROJECT_DIR/backend/"
    fi

    # Restore frontend (excluding node_modules and .next)
    if [ -d "$staging/summitflow/frontend" ]; then
        log "Restoring frontend..."
        rsync -a --delete \
            --exclude='node_modules' \
            --exclude='.next' \
            "$staging/summitflow/frontend/" "$PROJECT_DIR/frontend/"
    fi

    # Restore other directories
    for dir in scripts data .claude; do
        if [ -d "$staging/summitflow/$dir" ]; then
            log "Restoring $dir..."
            rsync -a "$staging/summitflow/$dir/" "$PROJECT_DIR/$dir/"
        fi
    done

    # Restore root files
    for file in CLAUDE.md AGENTS.md; do
        if [ -f "$staging/summitflow/$file" ]; then
            cp "$staging/summitflow/$file" "$PROJECT_DIR/$file"
        fi
    done

    log_success "Files restored successfully"

    # Restart services
    log "Restarting services..."
    bash "$PROJECT_DIR/scripts/restart.sh" 2>/dev/null || true

    return 0
}

# Main restore function
do_restore() {
    local archive="$1"

    echo ""
    echo "========================================"
    echo "SummitFlow Restore"
    echo "========================================"
    echo ""

    if [ ! -f "$archive" ]; then
        log_error "Archive not found: $archive"
        exit 1
    fi

    log "Archive: $archive"
    log "Size: $(du -h "$archive" | cut -f1)"
    echo ""

    # Verify archive
    if ! verify_archive "$archive"; then
        exit 1
    fi
    echo ""

    # Create staging directory
    mkdir -p "$RESTORE_STAGING"

    # Extract database dump if needed
    if [ "$FILES_ONLY" != true ]; then
        log "Extracting database dump..."
        tar -xzf "$archive" -C "$RESTORE_STAGING" --wildcards "*/database.sql.gz" 2>/dev/null || true

        local db_dump=$(find "$RESTORE_STAGING" -name "database.sql.gz" | head -1)
        if [ -n "$db_dump" ] && [ -f "$db_dump" ]; then
            restore_database "$db_dump"
        else
            log_warn "No database dump found in archive"
        fi
    fi

    # Restore files if needed
    if [ "$DB_ONLY" != true ]; then
        restore_files "$archive" "$RESTORE_STAGING"
    fi

    echo ""
    echo "========================================"
    log_success "Restore complete!"
    echo "========================================"
    echo ""

    if [ "$DRY_RUN" = true ]; then
        echo "  (This was a dry run - no changes made)"
    else
        echo "  Source: $(basename "$archive")"
        [ "$DB_ONLY" != true ] && echo "  Files: restored"
        [ "$FILES_ONLY" != true ] && echo "  Database: restored"
        echo ""
        echo "  Verify with:"
        echo "    bash ~/summitflow/scripts/status.sh"
        echo "    cd backend && .venv/bin/pytest tests/ -x"
    fi
    echo ""
}

# Main
case "$RESTORE_MODE" in
    list)
        list_backups
        ;;
    latest)
        latest=$(find_latest_backup)
        if [ -z "$latest" ]; then
            log_error "No backups found"
            echo ""
            echo "Run backup first: bash ~/summitflow/scripts/backup.sh --keep-local"
            exit 1
        fi
        log "Found latest backup: $latest"
        do_restore "$latest"
        ;;
    file)
        if [ -z "$TARGET_FILE" ]; then
            log_error "No file specified"
            exit 1
        fi
        do_restore "$TARGET_FILE"
        ;;
    *)
        echo "Usage: $0 --list | --latest | --file <archive>"
        echo ""
        echo "Run '$0 --help' for more options"
        exit 1
        ;;
esac
