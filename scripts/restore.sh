#!/bin/bash
#
# Universal Restore Script
# Restores code and/or database from backup archives
# Works for any project - auto-detects project from PWD/git root
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
#   1. Local: $PROJECT_DIR/backups/
#   2. Pending: ~/.local/share/backup-pending/
#   3. SMB: //$SMB_HOST/$SMB_SHARE/project-backups/$PROJECT_NAME/

set -eo pipefail

# Load utilities (which also detects PROJECT_DIR and PROJECT_NAME)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/backup-utils.sh"

# Configuration - uses PROJECT_NAME from backup-utils.sh
LOCAL_BACKUP_DIR="$PROJECT_DIR/backups"
RESTORE_STAGING="/tmp/${PROJECT_NAME}-restore-$$"
BACKUP_DB_DUMP_NAME="database.sql.gz"

# Load project-specific config if it exists
if [ -f "$PROJECT_DIR/scripts/lib/backup-project.sh" ]; then
    source "$PROJECT_DIR/scripts/lib/backup-project.sh"
fi

# Parse arguments
RESTORE_MODE=""
TARGET_FILE=""
TARGET_NAME=""
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
        --name)
            RESTORE_MODE="name"
            TARGET_NAME="$2"
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
            echo "  --name <file>  Restore a specific archive name from local, pending, or SMB"
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

# ─── Docker detection ─────────────────────────────────────────
COMPOSE_PROJECT="summitflow-stack"
USE_DOCKER=false

if [ -S /var/run/docker.sock ] && docker compose -p "$COMPOSE_PROJECT" ps --status running -q 2>/dev/null | grep -q .; then
    USE_DOCKER=true
fi

_docker_psql() {
    docker compose -p "$COMPOSE_PROJECT" exec -T postgres psql -U admin "$@"
}

# Cleanup function
cleanup() {
    if [ -d "$RESTORE_STAGING" ]; then
        rm -rf "$RESTORE_STAGING"
    fi
}
trap cleanup EXIT

print_archive_preview() {
    local archive="$1"
    local skip_pattern="${2:-}"
    local limit="${3:-20}"
    local entry=""
    local shown=0
    local omitted=0

    while IFS= read -r entry; do
        if [ -n "$skip_pattern" ] && [[ "$entry" == *"$skip_pattern" ]]; then
            continue
        fi

        if [ "$shown" -lt "$limit" ]; then
            echo "$entry"
            shown=$((shown + 1))
        else
            omitted=$((omitted + 1))
        fi
    done < <(tar -tzf "$archive")

    if [ "$omitted" -gt 0 ]; then
        echo "  ... (truncated $omitted more entries)"
    fi
}

list_local_backup_paths() {
    if [ ! -d "$LOCAL_BACKUP_DIR" ]; then
        return 0
    fi
    find "$LOCAL_BACKUP_DIR" -maxdepth 1 -type f -name "${PROJECT_NAME}-*.tar.gz" 2>/dev/null | sort
}

list_pending_backup_paths() {
    if [ ! -d "$PENDING_BACKUP_DIR" ]; then
        return 0
    fi
    find "$PENDING_BACKUP_DIR" -maxdepth 1 -type f -name "${PROJECT_NAME}-*.tar.gz" 2>/dev/null | sort
}

download_remote_backup() {
    local backup_name="$1"
    local local_path="$RESTORE_STAGING/$backup_name"

    mkdir -p "$RESTORE_STAGING"

    if smb_download "$backup_name" "$local_path" >&2; then
        echo "$local_path"
        return 0
    fi

    return 1
}

resolve_backup_by_name() {
    local backup_name="$1"
    local local_path="$LOCAL_BACKUP_DIR/$backup_name"
    local pending_path="$PENDING_BACKUP_DIR/$backup_name"

    if [ -f "$local_path" ]; then
        echo "$local_path"
        return 0
    fi

    if [ -f "$pending_path" ]; then
        echo "$pending_path"
        return 0
    fi

    if [ -f "$CREDENTIALS_FILE" ] && test_smb_connection_quiet; then
        if smb_list_backups | grep -Fxq "$backup_name"; then
            download_remote_backup "$backup_name"
            return $?
        fi
    fi

    return 1
}

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
        local local_backups
        local_backups=$(list_local_backup_paths || true)
        if [ -n "$local_backups" ]; then
            echo "$local_backups" | while read f; do
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

    # Pending backups
    echo "PENDING ($PENDING_BACKUP_DIR/):"
    if [ -d "$PENDING_BACKUP_DIR" ]; then
        local pending_backups
        pending_backups=$(list_pending_backup_paths || true)
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
    local local_latest pending_latest smb_latest latest_name

    read -r local_latest < <(list_local_backup_paths | sed 's|.*/||' | tail -1) || true
    read -r pending_latest < <(list_pending_backup_paths | sed 's|.*/||' | tail -1) || true

    if [ -f "$CREDENTIALS_FILE" ] && test_smb_connection_quiet; then
        read -r smb_latest < <(smb_list_backups | tail -1) || true
    fi

    latest_name=$(printf '%s\n%s\n%s\n' "$local_latest" "$pending_latest" "$smb_latest" | grep -v '^$' | sort | tail -1)
    if [ -z "$latest_name" ]; then
        return 0
    fi

    resolve_backup_by_name "$latest_name"
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
    local has_db
    local has_project_files
    has_db=$(tar -tzf "$archive" | grep -c "$BACKUP_DB_DUMP_NAME" || true)
    has_project_files=$(tar -tzf "$archive" | grep -vcE "/$|${BACKUP_DB_DUMP_NAME}$" || true)

    echo "  Database dump: $([ "$has_db" -gt 0 ] && echo "✓" || echo "✗")"
    echo "  Project files: $([ "$has_project_files" -gt 0 ] && echo "✓" || echo "✗")"

    if [ "$has_db" -eq 0 ] && [ "$DB_ONLY" = true ]; then
        log_error "Archive does not contain a database dump — cannot use --db-only"
        return 1
    fi

    # If the source does not expect a database, force files-only mode
    # regardless of what the archive contains (catches old placeholder dumps)
    if ! backup_expects_database; then
        if [ "$DB_ONLY" = true ]; then
            log_error "Source '$PROJECT_NAME' does not use a database — cannot use --db-only"
            return 1
        fi
        if [ "$FILES_ONLY" != true ]; then
            log_info "Source '$PROJECT_NAME' does not use a database — using files-only restore"
            FILES_ONLY=true
        fi
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

    if [ "$USE_DOCKER" = true ]; then
        _restore_database_docker "$db_dump"
    else
        _restore_database_native "$db_dump"
    fi
}

_restore_database_docker() {
    local db_dump="$1"

    # Stop app services (leave postgres running)
    log "Stopping app services (Docker)..."
    local api_svc="${PROJECT_NAME}-api"
    local worker_svc="${PROJECT_NAME}-worker"
    docker compose -p "$COMPOSE_PROJECT" stop "$api_svc" "$worker_svc" 2>/dev/null || true

    log "Dropping existing database..."
    _docker_psql -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_restore;" 2>/dev/null || true
    _docker_psql -d postgres -c "CREATE DATABASE ${DB_NAME}_restore;" 2>/dev/null

    log "Restoring from dump..."
    if gunzip -c "$db_dump" | _docker_psql -d "${DB_NAME}_restore" >/dev/null 2>&1; then
        log "Swapping databases..."
        _docker_psql -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_old;" 2>/dev/null || true
        _docker_psql -d postgres -c "ALTER DATABASE $DB_NAME RENAME TO ${DB_NAME}_old;" 2>/dev/null || true
        _docker_psql -d postgres -c "ALTER DATABASE ${DB_NAME}_restore RENAME TO $DB_NAME;" 2>/dev/null

        log_success "Database restored successfully"

        _docker_psql -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_old;" 2>/dev/null || true
    else
        log_error "Database restore failed"
        _docker_psql -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME}_restore;" 2>/dev/null || true
        return 1
    fi

    # Restart app services
    log "Restarting app services (Docker)..."
    docker compose -p "$COMPOSE_PROJECT" start "$api_svc" "$worker_svc" 2>/dev/null || true

    return 0
}

_restore_database_native() {
    local db_dump="$1"

    # Stop services that use the database
    log "Stopping services..."
    systemctl --user stop ${PROJECT_NAME}-backend 2>/dev/null || true

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
    systemctl --user start ${PROJECT_NAME}-backend 2>/dev/null || true

    return 0
}

# Restore files
restore_files() {
    local archive="$1"
    local staging="$2"
    local restore_root="$staging/${PROJECT_NAME}"

    log "Restoring files..."

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would restore files from: $archive"
        log_info "[DRY RUN] Files to restore:"
        print_archive_preview "$archive" "$BACKUP_DB_DUMP_NAME" 20
        return 0
    fi

    # Extract to staging
    log "Extracting archive..."
    tar -xzf "$archive" -C "$staging"

    if [ ! -d "$restore_root" ]; then
        log_error "Archive does not contain project files for $PROJECT_NAME"
        return 1
    fi

    # Stop services
    log "Stopping services..."
    if [ "$USE_DOCKER" = true ]; then
        docker compose -p "$COMPOSE_PROJECT" stop "${PROJECT_NAME}-api" "${PROJECT_NAME}-web" "${PROJECT_NAME}-worker" 2>/dev/null || true
    else
        systemctl --user stop ${PROJECT_NAME}-backend ${PROJECT_NAME}-frontend 2>/dev/null || true
    fi

    # Backup current state (just in case)
    local pre_restore_backup="$PROJECT_DIR/backups/.pre-restore-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$pre_restore_backup"

    log "Restoring project files..."
    rsync -a --delete \
        --exclude='.git' \
        --exclude='backups' \
        --exclude='.venv' \
        --exclude='backend/.venv' \
        --exclude='frontend/node_modules' \
        --exclude='frontend/.next' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='.mypy_cache' \
        --exclude='.ruff_cache' \
        "$restore_root/" "$PROJECT_DIR/"

    log_success "Files restored successfully"

    # Restart services
    log "Restarting services..."
    if [ "$USE_DOCKER" = true ]; then
        docker compose -p "$COMPOSE_PROJECT" start "${PROJECT_NAME}-api" "${PROJECT_NAME}-web" "${PROJECT_NAME}-worker" 2>/dev/null || true
    else
        bash "$PROJECT_DIR/scripts/restart.sh" 2>/dev/null || true
    fi

    return 0
}

# Main restore function
do_restore() {
    local archive="$1"

    echo ""
    echo "========================================"
    echo "$PROJECT_NAME Restore"
    echo "========================================"
    echo ""
    echo "Project: $PROJECT_NAME ($PROJECT_DIR)"
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
        tar -xzf "$archive" -C "$RESTORE_STAGING" --wildcards "*/$BACKUP_DB_DUMP_NAME" 2>/dev/null || true

        local db_dump
        db_dump=$(find "$RESTORE_STAGING" -name "$BACKUP_DB_DUMP_NAME" | head -1)
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
        echo "    bash $PROJECT_DIR/scripts/status.sh"
        echo "    cd $PROJECT_DIR/backend && .venv/bin/pytest tests/ -x"
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
            echo "Run backup first: cd $PROJECT_DIR && bash $SCRIPT_DIR/backup.sh --keep-local"
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
    name)
        if [ -z "$TARGET_NAME" ]; then
            log_error "No archive name specified"
            exit 1
        fi
        archive=$(resolve_backup_by_name "$TARGET_NAME")
        if [ -z "$archive" ]; then
            log_error "Backup not found: $TARGET_NAME"
            exit 1
        fi
        log "Resolved backup: $archive"
        do_restore "$archive"
        ;;
    *)
        echo "Usage: $0 --list | --latest | --file <archive> | --name <archive-name>"
        echo ""
        echo "Run '$0 --help' for more options"
        exit 1
        ;;
esac
