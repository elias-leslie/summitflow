#!/bin/bash
#
# Universal Backup Utilities
# Shared functions for backup and restore scripts
# Works for any project - auto-detects project from PWD/git root
#

# Colors
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export RED='\033[0;31m'
export BLUE='\033[0;34m'
export NC='\033[0m'

# Project Detection - auto-detect from PWD or git root
if [ -z "$PROJECT_DIR" ]; then
    PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
fi
export PROJECT_DIR
export PROJECT_NAME=$(basename "$PROJECT_DIR")

# Storage backend integration — resolve SMB config from DB if STORAGE_BACKEND_ID is set
SCRIPT_DIR_BU="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR_BU/storage-backend.sh" 2>/dev/null || true
source "$SCRIPT_DIR_BU/project-roots.sh" 2>/dev/null || true

default_backup_state_root() {
    if declare -F shared_cache_root >/dev/null 2>&1; then
        local candidate_root
        candidate_root="$(shared_cache_root)"
        if [ -d "$candidate_root" ] && [ -w "$candidate_root" ]; then
            printf '%s\n' "$candidate_root/backup-indexes"
            return 0
        fi
    fi

    local workspaces_cache="${ST_WORKSPACES_ROOT:-$HOME/.local/share/summitflow/workspaces}/cache"
    if [ -d "$workspaces_cache" ] && [ -w "$workspaces_cache" ]; then
        printf '%s\n' "$workspaces_cache/backup-indexes"
        return 0
    fi
    printf '%s\n' "$HOME/.local/share/summitflow/backup-indexes"
}

# SMB configuration - override via environment or ~/.env.local
# Set SMB_HOST and SMB_SHARE in ~/.env.local for your NAS/SMB target
if [ -f "$HOME/.env.local" ] && [ -z "${SMB_HOST:-}" ]; then
    eval "$(grep -E '^(SMB_HOST|SMB_SHARE|SMB_USER)=' "$HOME/.env.local" 2>/dev/null)" || true
fi
export SMB_HOST="${SMB_HOST:-}"
export SMB_SHARE="${SMB_SHARE:-}"
export SMB_PATH="project-backups/$PROJECT_NAME"
export SMB_USER="${SMB_USER:-backup-svc}"
export CREDENTIALS_FILE="$HOME/.smbcredentials"
export BACKUP_STATE_ROOT="${ST_BACKUP_STATE_ROOT:-$(default_backup_state_root)}"
export BACKUP_STATE_DIR="$BACKUP_STATE_ROOT/$PROJECT_NAME"
export LEGACY_BACKUP_INDEX="$PROJECT_DIR/backup-index.json"
export BACKUP_INDEX="$BACKUP_STATE_DIR/backup-index.json"
export RETENTION_DAYS=14
export MIN_BACKUPS=3

# Database config - load from ~/.env.local if available
# Derive env var name from project: portfolio-ai -> PORTFOLIO_AI_DB_URL
_env_var_name=$(echo "${PROJECT_NAME}" | tr '[:lower:]-' '[:upper:]_')_DB_URL
if [ -f "$HOME/.env.local" ]; then
    _db_url=$(grep "^${_env_var_name}=" "$HOME/.env.local" 2>/dev/null | cut -d'=' -f2- | tr -d '"' || true)
    if [ -z "$_db_url" ]; then
        # Fallback: look for DATABASE_URL that contains project name
        _db_url=$(grep "^DATABASE_URL=.*${PROJECT_NAME}" "$HOME/.env.local" 2>/dev/null | cut -d'=' -f2- | tr -d '"' || true)
    fi
    if [ -n "$_db_url" ]; then
        _db_userpass=$(echo "$_db_url" | sed -n 's|postgresql://\([^@]*\)@.*|\1|p')
        export DB_USER=$(echo "$_db_userpass" | cut -d':' -f1)
        export DB_PASSWORD=$(echo "$_db_userpass" | cut -d':' -f2)
        export DB_NAME=$(echo "$_db_url" | sed -n 's|.*/\([^?]*\).*|\1|p')
    fi
fi

# Fallback defaults - derived from project name (portfolio-ai -> portfolio_ai)
_db_default=$(echo "$PROJECT_NAME" | tr '-' '_')
export DB_NAME="${DB_NAME:-$_db_default}"
export DB_USER="${DB_USER:-${_db_default}_app}"
export DB_PASSWORD="${DB_PASSWORD:-}"

# Exclusions - things that should NEVER be backed up
BACKUP_EXCLUDES=(
    # Virtual environments
    "backend/.venv"

    # Frontend build artifacts
    "frontend/node_modules"
    "frontend/.next"

    # Git (already version controlled)
    ".git"

    # Python caches
    ".mypy_cache"
    "backend/.mypy_cache"
    "__pycache__"
    "*.pyc"
    "*.pyo"
    "backend/.ruff_cache"
    ".ruff_cache"
    "backend/.pytest_cache"
    ".pytest_cache"

    # Redundant backups
    "./backups"

    # Scratch/tmp artifacts (large, local-only, regenerable)
    ".tmp"
    ".tmp-*"

    # Claude transient data
    ".claude/backups"
    ".claude/plans"

    # Evidence/artifacts (regenerable)
    "data/artifacts"
    "data/evidence"

    # Node modules (anywhere)
    "node_modules"

    # Hatchet container-generated config (root-owned, regenerated on startup)
    "docker/compose/hatchet-config"
)

# Load .backupignore if present (per-repo exclusions, like .gitignore for backups)
if [ -f "$PROJECT_DIR/.backupignore" ]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip comments and blank lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        # Strip trailing slashes for directory patterns
        line="${line%/}"
        BACKUP_EXCLUDES+=("$line")
    done < "$PROJECT_DIR/.backupignore"
fi

# Logging functions
log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log_success() {
    printf "${GREEN}[%s] ✓ %s${NC}\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log_warn() {
    printf "${YELLOW}[%s] ⚠ %s${NC}\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log_error() {
    printf "${RED}[%s] ✗ %s${NC}\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log_info() {
    printf "${BLUE}[%s] ℹ %s${NC}\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

ensure_backup_state_dir() {
    mkdir -p "$BACKUP_STATE_DIR"
}

backup_expects_database() {
    case "${BACKUP_EXPECTS_DATABASE:-auto}" in
        true)
            return 0
            ;;
        false)
            return 1
            ;;
        *)
            # Check if credentials were loaded successfully
            [ -n "${DB_PASSWORD:-}" ] && return 0
            # Also check if .env.local has a DB URL for this project (may have failed to parse)
            if [ -f "$HOME/.env.local" ]; then
                grep -qE "^${_env_var_name}=.*postgresql://" "$HOME/.env.local" 2>/dev/null && return 0
                grep -qE "^DATABASE_URL=.*${PROJECT_NAME}" "$HOME/.env.local" 2>/dev/null && return 0
            fi
            return 1
            ;;
    esac
}

# Check if SMB credentials file exists, create if needed
ensure_smb_credentials() {
    if [ ! -f "$CREDENTIALS_FILE" ]; then
        log_warn "SMB credentials file not found at $CREDENTIALS_FILE"
        log "Creating credentials file..."

        read -s -p "Enter SMB password for $SMB_USER@$SMB_HOST: " smb_password
        echo

        cat > "$CREDENTIALS_FILE" << EOF
username=$SMB_USER
password=$smb_password
domain=WORKGROUP
EOF
        chmod 600 "$CREDENTIALS_FILE"
        log_success "Credentials file created"
    fi
}

# Probe the stable parent directory for this source's backup path.
# Some SMB shares deny listing the share root, while new per-project directories
# under project-backups/ are created lazily during upload.
smb_probe_dir() {
    local probe_dir="${SMB_PATH%/*}"
    if [ -z "$probe_dir" ] || [ "$probe_dir" = "$SMB_PATH" ]; then
        printf '.\n'
        return 0
    fi
    printf '%s\n' "$probe_dir"
}

# Test SMB share connectivity.
# Check the parent directory, not the project-specific path: new project
# directories are created lazily during upload, so a missing $SMB_PATH should
# not be treated as an unavailable SMB destination.
test_smb_connection() {
    log "Testing SMB connection to //$SMB_HOST/$SMB_SHARE..."

    local probe_dir
    probe_dir="$(smb_probe_dir)"
    if smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" -c "cd $probe_dir; ls" &>/dev/null; then
        log_success "SMB connection OK"
        return 0
    else
        log_error "SMB connection failed"
        return 1
    fi
}

# Test SMB share connectivity (quiet version - no logging)
test_smb_connection_quiet() {
    local probe_dir
    probe_dir="$(smb_probe_dir)"
    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" -c "cd $probe_dir; ls" &>/dev/null
}

# Pending backups directory
export PENDING_BACKUP_DIR="$HOME/.local/share/backup-pending"

# Upload with retry and local fallback
# Returns 0 on success, 1 on failure (but backup is saved locally)
upload_with_retry() {
    local archive_path="$1"
    local archive_name="$2"
    local project_name="${3:-$PROJECT_NAME}"
    local max_retries="${SMB_MAX_RETRIES:-5}"
    local initial_delay="${SMB_RETRY_DELAY:-5}"

    local delay=$initial_delay
    local attempt=1

    while [ $attempt -le $max_retries ]; do
        if test_smb_connection_quiet; then
            log "SMB available, uploading..."
            if smb_upload "$archive_path" "$SMB_PATH" "$archive_name"; then
                return 0
            else
                log_error "Upload failed despite connection"
            fi
        fi

        if [ $attempt -lt $max_retries ]; then
            log_warn "SMB unavailable (attempt $attempt/$max_retries), retrying in ${delay}s..."
            sleep $delay
            delay=$((delay * 2))  # Exponential backoff
            [ $delay -gt 60 ] && delay=60  # Cap at 60 seconds
        fi

        ((attempt++))
    done

    # All retries exhausted - save locally
    log_error "SMB unavailable after $max_retries attempts"
    save_to_pending "$archive_path" "$archive_name" "$project_name"
    return 1
}

# Save backup to pending directory for later upload
save_to_pending() {
    local archive_path="$1"
    local archive_name="$2"
    local project_name="${3:-$PROJECT_NAME}"

    mkdir -p "$PENDING_BACKUP_DIR"

    local pending_path="$PENDING_BACKUP_DIR/$archive_name"

    if cp "$archive_path" "$pending_path"; then
        # Create metadata file
        cat > "${pending_path}.meta" << EOF
{
    "project": "$project_name",
    "archive": "$archive_name",
    "created_at": "$(date -Iseconds)",
    "smb_host": "$SMB_HOST",
    "smb_share": "$SMB_SHARE",
    "smb_path": "$SMB_PATH",
    "retry_count": 0
}
EOF
        log_warn "Backup saved to pending: $pending_path"
        log_info "Run 'backup-pending-upload.sh' when SMB is available"
        return 0
    else
        log_error "Failed to save backup to pending directory"
        return 1
    fi
}

# Upload pending backups (called by separate service)
upload_pending_backups() {
    if [ ! -d "$PENDING_BACKUP_DIR" ]; then
        return 0
    fi

    local pending_files=$(find "$PENDING_BACKUP_DIR" -name "*.tar.gz" 2>/dev/null)

    if [ -z "$pending_files" ]; then
        log "No pending backups to upload"
        return 0
    fi

    # First check if SMB is available at all
    if ! test_smb_connection_quiet; then
        log_warn "SMB still unavailable, will retry later"
        return 0
    fi

    local uploaded=0
    local failed=0

    for archive in $pending_files; do
        local archive_name=$(basename "$archive")
        local meta_file="${archive}.meta"

        if [ -f "$meta_file" ]; then
            local project=$(jq -r '.project' "$meta_file")
            local smb_path=$(jq -r '.smb_path' "$meta_file")

            log "Uploading pending backup: $archive_name ($project)"

            if smb_upload "$archive" "$smb_path" "$archive_name"; then
                log_success "Uploaded: $archive_name"
                rm -f "$archive" "$meta_file"
                uploaded=$((uploaded + 1))
            else
                # Update retry count
                local retry_count=$(jq -r '.retry_count' "$meta_file")
                retry_count=$((retry_count + 1))
                jq --argjson rc "$retry_count" '.retry_count = $rc | .last_retry = "'"$(date -Iseconds)"'"' \
                    "$meta_file" > "${meta_file}.tmp" && mv "${meta_file}.tmp" "$meta_file"
                log_error "Failed to upload: $archive_name (retry $retry_count)"
                failed=$((failed + 1))
            fi
        else
            log_warn "No metadata for $archive_name, skipping"
        fi
    done

    if [ $uploaded -gt 0 ]; then
        log_success "Uploaded $uploaded pending backup(s)"
    fi
    if [ $failed -gt 0 ]; then
        log_warn "$failed backup(s) still pending"
    fi

    return 0
}

# Upload file via smbclient
smb_upload() {
    local local_file="$1"
    local remote_dir="$2"
    local remote_name="${3:-$(basename "$local_file")}"

    log "Uploading $(basename "$local_file") to //$SMB_HOST/$SMB_SHARE/$remote_dir..."

    # Ensure remote directory exists (ignore "already exists" errors)
    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
        -c "mkdir $remote_dir" 2>/dev/null || true

    # Upload file — exit code is the sole success/failure indicator
    if ! smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
        -c "cd $remote_dir; put $local_file $remote_name" 2>/dev/null; then
        log_error "Upload failed (put returned non-zero)"
        return 1
    fi

    # Post-upload verification: confirm the file landed on the server
    if ! smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
        -c "cd $remote_dir; ls $remote_name" 2>/dev/null | grep -q "$remote_name"; then
        log_error "Upload verification failed — file not found on server"
        return 1
    fi

    log_success "Upload complete (verified)"
    return 0
}

# List remote backups
smb_list_backups() {
    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
        -c "cd $SMB_PATH; ls ${PROJECT_NAME}-*.tar.gz" 2>/dev/null | \
        grep "${PROJECT_NAME}-" | awk '{print $1}' | sort
}

# Download file via smbclient
smb_download() {
    local remote_file="$1"
    local local_path="$2"

    log "Downloading $remote_file..."

    if smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
        -c "cd $SMB_PATH; get $remote_file $local_path" 2>/dev/null; then
        log_success "Download complete"
        return 0
    else
        log_error "Download failed"
        return 1
    fi
}

# Delete remote file
smb_delete() {
    local remote_file="$1"

    log "Deleting remote file: $remote_file"

    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
        -c "cd $SMB_PATH; rm $remote_file" 2>/dev/null
}

# Update backup index JSON
update_backup_index() {
    local backup_name="$1"
    local backup_size="$2"
    local db_size="$3"
    local status="${4:-ok}"
    local verification_json="${5:-null}"
    local timestamp=$(date -Iseconds)

    log "Updating backup index..."

    if [ ! -f "$BACKUP_INDEX" ]; then
        cat > "$BACKUP_INDEX" << EOF
{
  "version": 2,
  "retention_days": $RETENTION_DAYS,
  "destination": "//$SMB_HOST/$SMB_SHARE/$SMB_PATH",
  "backups": [],
  "last_updated": "$timestamp"
}
EOF
    fi

    local temp_file=$(mktemp)
    if [ "$verification_json" != "null" ] && [ -n "$verification_json" ]; then
        jq --arg name "$backup_name" \
           --arg ts "$timestamp" \
           --argjson size "$backup_size" \
           --argjson dbsize "$db_size" \
           --arg status "$status" \
           --argjson verification "$verification_json" \
           '.version = 2 | .backups = [{"name": $name, "timestamp": $ts, "size_bytes": $size, "db_size_bytes": $dbsize, "status": $status, "verification": $verification}] + .backups | .last_updated = $ts' \
           "$BACKUP_INDEX" > "$temp_file"
    else
        jq --arg name "$backup_name" \
           --arg ts "$timestamp" \
           --argjson size "$backup_size" \
           --argjson dbsize "$db_size" \
           --arg status "$status" \
           '.version = 2 | .backups = [{"name": $name, "timestamp": $ts, "size_bytes": $size, "db_size_bytes": $dbsize, "status": $status}] + .backups | .last_updated = $ts' \
           "$BACKUP_INDEX" > "$temp_file"
    fi

    mv "$temp_file" "$BACKUP_INDEX"
    log_success "Backup index updated"
}

# Apply retention policy (time-based: delete files older than RETENTION_DAYS, keep MIN_BACKUPS)
apply_retention() {
    log "Applying retention policy (delete older than ${RETENTION_DAYS} days, keep min ${MIN_BACKUPS})..."

    local backups=($(smb_list_backups))
    local count=${#backups[@]}

    if [ "$count" -le "$MIN_BACKUPS" ]; then
        log_success "Retention OK: $count backups (at or below minimum $MIN_BACKUPS)"
        return 0
    fi

    local cutoff_epoch
    cutoff_epoch=$(date -d "-${RETENTION_DAYS} days" +%s 2>/dev/null || date -v-${RETENTION_DAYS}d +%s 2>/dev/null)
    local deleted=0

    # Iterate oldest-first (list is sorted ascending); stop when we'd go below MIN_BACKUPS
    for ((i=0; i<count; i++)); do
        local remaining=$((count - deleted))
        if [ "$remaining" -le "$MIN_BACKUPS" ]; then
            break
        fi

        local backup="${backups[$i]}"
        # Parse timestamp from filename: {project}-YYYYMMDD-HHMMSS.tar.gz
        local ts_part
        ts_part=$(echo "$backup" | sed -n 's/.*-\([0-9]\{8\}\)-\([0-9]\{6\}\)\.tar\.gz/\1\2/p')
        if [ -z "$ts_part" ]; then
            continue
        fi

        local year=${ts_part:0:4}
        local month=${ts_part:4:2}
        local day=${ts_part:6:2}
        local hour=${ts_part:8:2}
        local min=${ts_part:10:2}
        local sec=${ts_part:12:2}

        local file_epoch
        file_epoch=$(date -d "${year}-${month}-${day} ${hour}:${min}:${sec}" +%s 2>/dev/null || \
                     date -j -f "%Y-%m-%d %H:%M:%S" "${year}-${month}-${day} ${hour}:${min}:${sec}" +%s 2>/dev/null)

        if [ -n "$file_epoch" ] && [ "$file_epoch" -lt "$cutoff_epoch" ]; then
            if smb_delete "$backup"; then
                deleted=$((deleted + 1))
            else
                log_warn "Failed to delete $backup, skipping"
            fi
        fi
    done

    if [ "$deleted" -gt 0 ]; then
        log_success "Retention applied: deleted $deleted old backup(s), $((count - deleted)) remain"
    else
        log_success "Retention OK: no backups older than $RETENTION_DAYS days"
    fi
}

# Verify backup archive
verify_backup() {
    local archive_path="$1"

    if ! tar -tzf "$archive_path" > /dev/null 2>&1; then
        echo '{"verified":false,"verified_at":"'"$(date -Iseconds)"'","errors":["Archive integrity check failed"],"tree":{}}'
        return 1
    fi

    local tree_json
    tree_json=$(tar -tzf "$archive_path" 2>/dev/null | \
        sed "s|^${PROJECT_NAME}/\./||;s|^${PROJECT_NAME}/||" | \
        grep -v '/$' | grep -v '^$' | \
        awk -F'/' '
        {
            if (NF == 1) {
                files[$1] = 1
            } else {
                dirs[$1]++
            }
        }
        END {
            printf "{"
            first = 1
            for (d in dirs) {
                if (!first) printf ","
                printf "\"%s\":{\"count\":%d}", d, dirs[d]
                first = 0
            }
            for (f in files) {
                if (!first) printf ","
                printf "\"%s\":{\"count\":1}", f
                first = 0
            }
            printf "}"
        }')

    local total_files checksum has_db expects_db has_db_json
    local db_dump_name="${BACKUP_DB_DUMP_NAME:-database.sql.gz}"
    total_files=$(tar -tzf "$archive_path" | grep -v '/$' | wc -l | tr -d ' ')
    checksum=$(sha256sum "$archive_path" | cut -d' ' -f1)
    has_db=$(tar -tzf "$archive_path" | grep -Ec "$db_dump_name" || true)
    has_db="${has_db:-0}"
    if backup_expects_database; then
        expects_db="true"
    else
        expects_db="false"
    fi
    if [ "$has_db" -gt 0 ]; then
        has_db_json="true"
    else
        has_db_json="false"
    fi

    local verified="true"
    local errors="[]"
    if [ "$has_db" -eq 0 ] && [ "$expects_db" = "true" ]; then
        verified="false"
        errors="[\"Critical: $db_dump_name missing\"]"
    fi

    echo "{\"verified\":$verified,\"verified_at\":\"$(date -Iseconds)\",\"errors\":$errors,\"tree\":$tree_json,\"total_files\":$total_files,\"checksum\":\"sha256:$checksum\",\"has_db\":$has_db_json,\"expects_db\":$expects_db}"
}

# Get backup count from index
get_backup_count() {
    if [ -f "$BACKUP_INDEX" ]; then
        jq '.backups | length' "$BACKUP_INDEX"
    else
        echo "0"
    fi
}

# Remove oldest backup entry from index
remove_oldest_from_index() {
    local temp_file=$(mktemp)
    jq 'del(.backups[-1])' "$BACKUP_INDEX" > "$temp_file"
    mv "$temp_file" "$BACKUP_INDEX"
}

# Build manifest by scanning entire project (dynamic discovery)
build_backup_manifest() {
    local manifest_file="$1"

    cd "$PROJECT_DIR"

    # Build find exclusion args
    local exclude_args=()
    for ex in "${BACKUP_EXCLUDES[@]}"; do
        if [[ "$ex" == *"*"* ]]; then
            # Glob pattern (e.g., *.pyc)
            exclude_args+=(-not -name "$ex")
        else
            # Directory/path pattern
            exclude_args+=(-not -path "./$ex" -not -path "./$ex/*")
        fi
    done

    # Discover all files (excluding above)
    local all_files
    all_files=$(find . -type f "${exclude_args[@]}" 2>/dev/null | sed 's|^\./||' | sort)

    # Build tree: group by top-level directory
    local manifest_json
    manifest_json=$(cat <<EOF
{"generated_at":"$(date -Iseconds)","total_files":0,"total_size":0,"tree":{}}
EOF
)

    # Get unique top-level paths (first component of each path)
    local top_levels
    top_levels=$(echo "$all_files" | cut -d'/' -f1 | sort -u)

    for path in $top_levels; do
        local count size
        if [ -d "$path" ]; then
            count=$(echo "$all_files" | grep -c "^$path/" || echo 0)
            # Calculate size excluding the exclusions
            size=$(find "$path" -type f "${exclude_args[@]}" -exec stat -c%s {} + 2>/dev/null | awk '{s+=$1}END{print s+0}')
        else
            count=1
            size=$(stat -c%s "$path" 2>/dev/null || echo 0)
        fi

        manifest_json=$(echo "$manifest_json" | jq --arg p "$path" \
            --argjson c "$count" --argjson s "${size:-0}" \
            '.tree[$p] = {"file_count": $c, "size_bytes": $s}')
    done

    # Add totals
    local total_count total_size
    total_count=$(echo "$all_files" | wc -l)
    total_size=$(echo "$all_files" | tr '\n' '\0' | xargs -0 stat -c%s 2>/dev/null | awk '{s+=$1}END{print s+0}')

    manifest_json=$(echo "$manifest_json" | jq \
        --argjson tc "$total_count" --argjson ts "${total_size:-0}" \
        '.total_files = $tc | .total_size = $ts')

    echo "$manifest_json" > "$manifest_file"
}

# Pre-backup checkpoint hook for use by other commands
backup_checkpoint() {
    local description="${1:-pre-operation}"

    log_info "Creating backup checkpoint: $description"

    if st backup create --source "$PROJECT_NAME" --note "$description" 2>&1 | tail -5; then
        log_success "Checkpoint created"
        return 0
    else
        log_warn "Checkpoint failed, continuing anyway"
        return 1
    fi
}

# Validate that index file is valid JSON with expected structure
validate_index() {
    local index_file="${1:-$BACKUP_INDEX}"

    if [ ! -f "$index_file" ]; then
        return 1
    fi

    # Check file is not empty
    if [ ! -s "$index_file" ]; then
        log_error "Index file is empty"
        return 1
    fi

    # Validate JSON structure
    if ! jq -e '.backups and (.retention or .retention_days)' "$index_file" &>/dev/null; then
        log_error "Index file has invalid JSON structure"
        return 1
    fi

    return 0
}

migrate_legacy_backup_index() {
    ensure_backup_state_dir

    if [ ! -f "$LEGACY_BACKUP_INDEX" ]; then
        return 0
    fi

    if [ -f "$BACKUP_INDEX" ]; then
        if cmp -s "$LEGACY_BACKUP_INDEX" "$BACKUP_INDEX" 2>/dev/null; then
            rm -f "$LEGACY_BACKUP_INDEX"
        fi
        return 0
    fi

    if ! validate_index "$LEGACY_BACKUP_INDEX" >/dev/null 2>&1; then
        log_warn "Legacy backup index is invalid, leaving it in place: $LEGACY_BACKUP_INDEX"
        return 1
    fi

    mv "$LEGACY_BACKUP_INDEX" "$BACKUP_INDEX"
    log_success "Moved backup index to shared state: $BACKUP_INDEX"
    return 0
}

# Sync local index with SMB - self-healing function
# Adds missing backups, removes orphans, preserves existing verification data
# Usage: sync_index_from_smb [--verify-missing]
#   --verify-missing: Download and verify backups that lack verification data
sync_index_from_smb() {
    local verify_missing=false
    if [ "$1" = "--verify-missing" ]; then
        verify_missing=true
    fi

    ensure_backup_state_dir
    migrate_legacy_backup_index >/dev/null 2>&1 || true
    log "Syncing backup index with SMB..."

    # Ensure index exists and is valid
    if [ ! -f "$BACKUP_INDEX" ] || ! validate_index; then
        log "Creating fresh index..."
        cat > "$BACKUP_INDEX" << EOF
{
  "version": 2,
  "retention_days": $RETENTION_DAYS,
  "destination": "//$SMB_HOST/$SMB_SHARE/$SMB_PATH",
  "backups": [],
  "last_updated": "$(date -Iseconds)"
}
EOF
    fi

    # Get list from SMB
    local smb_backups
    smb_backups=$(smb_list_backups)
    if [ -z "$smb_backups" ]; then
        log_warn "No backups found on SMB or connection failed"
        return 1
    fi

    # Get list from index
    local index_backups
    index_backups=$(jq -r '.backups[].name' "$BACKUP_INDEX" 2>/dev/null)

    local added=0
    local removed=0

    # Add missing backups (on SMB but not in index)
    for backup in $smb_backups; do
        if ! echo "$index_backups" | grep -q "^${backup}$"; then
            log "Adding missing backup: $backup"

            # Extract timestamp from filename (PROJECT_NAME-YYYYMMDD-HHMMSS.tar.gz)
            local ts_part=$(echo "$backup" | sed -n "s/${PROJECT_NAME}-\([0-9]*\)-\([0-9]*\)\.tar\.gz/\1-\2/p")
            local year=${ts_part:0:4}
            local month=${ts_part:4:2}
            local day=${ts_part:6:2}
            local hour=${ts_part:9:2}
            local min=${ts_part:11:2}
            local sec=${ts_part:13:2}
            local timestamp="${year}-${month}-${day}T${hour}:${min}:${sec}-05:00"

            # Get file size from SMB
            local size
            size=$(smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
                -c "cd $SMB_PATH; ls $backup" 2>/dev/null | grep "$backup" | awk '{print $3}')
            size=${size:-0}

            # Add to index (will be sorted later) - atomic write
            local temp_file=$(mktemp)
            if jq --arg name "$backup" \
               --arg ts "$timestamp" \
               --argjson size "$size" \
               '.backups += [{"name": $name, "timestamp": $ts, "size_bytes": $size, "db_size_bytes": 0, "status": "ok", "verification": null}]' \
               "$BACKUP_INDEX" > "$temp_file" && validate_index "$temp_file"; then
                mv "$temp_file" "$BACKUP_INDEX"
                added=$((added + 1))
            else
                log_error "Failed to add $backup to index"
                rm -f "$temp_file"
            fi
        fi
    done

    # Remove orphaned entries (in index but not on SMB)
    for backup in $index_backups; do
        if ! echo "$smb_backups" | grep -q "^${backup}$"; then
            log "Removing orphaned entry: $backup"
            local temp_file=$(mktemp)
            if jq --arg name "$backup" '.backups = [.backups[] | select(.name != $name)]' \
               "$BACKUP_INDEX" > "$temp_file" && validate_index "$temp_file"; then
                mv "$temp_file" "$BACKUP_INDEX"
                removed=$((removed + 1))
            else
                log_error "Failed to remove orphan $backup"
                rm -f "$temp_file"
            fi
        fi
    done

    # Sort by timestamp (newest first) and update last_updated - atomic write
    local temp_file=$(mktemp)
    local now_ts=$(date -Iseconds)
    if jq --arg ts "$now_ts" '.backups = (.backups | sort_by(.timestamp) | reverse) | .last_updated = $ts' \
       "$BACKUP_INDEX" > "$temp_file" && validate_index "$temp_file"; then
        mv "$temp_file" "$BACKUP_INDEX"
    else
        log_error "Failed to sort/update index"
        rm -f "$temp_file"
    fi

    if [ $added -gt 0 ] || [ $removed -gt 0 ]; then
        log_success "Index synced: +$added added, -$removed removed"
    else
        log_success "Index already in sync"
    fi

    # Optionally verify backups missing verification data
    if [ "$verify_missing" = true ]; then
        log "Checking for backups missing verification..."

        # Get current time and calculate 5-minute threshold
        local now_epoch=$(date +%s)
        local threshold=$((now_epoch - 300))  # 5 minutes ago

        # Find backups missing verification that are older than 5 minutes
        # This avoids race conditions with backups still being created
        local missing_verification
        missing_verification=$(jq -r --argjson threshold "$threshold" '
            .backups[] |
            select(.verification == null or .verification.total_files == null) |
            select((.timestamp | sub("\\.[0-9]+"; "") | strptime("%Y-%m-%dT%H:%M:%S%z") | mktime) < $threshold) |
            .name
        ' "$BACKUP_INDEX" 2>/dev/null)

        if [ -n "$missing_verification" ]; then
            local verified=0
            for backup in $missing_verification; do
                log "Verifying: $backup"
                local temp_file="/tmp/$backup"

                # Download
                if smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" \
                   -c "cd $SMB_PATH; get $backup $temp_file" &>/dev/null; then

                    # Verify
                    local verification
                    verification=$(verify_backup "$temp_file")

                    # Update index
                    local index_temp=$(mktemp)
                    if jq --arg name "$backup" --argjson v "$verification" \
                       '(.backups[] | select(.name == $name)).verification = $v' \
                       "$BACKUP_INDEX" > "$index_temp" && validate_index "$index_temp"; then
                        mv "$index_temp" "$BACKUP_INDEX"
                        verified=$((verified + 1))
                        log_success "Verified: $backup ($(echo "$verification" | jq -r '.total_files') files)"
                    else
                        rm -f "$index_temp"
                        log_error "Failed to update verification for $backup"
                    fi

                    rm -f "$temp_file"
                else
                    log_error "Failed to download $backup for verification"
                fi
            done

            if [ $verified -gt 0 ]; then
                log_success "Verified $verified backup(s)"
            fi
        else
            log_success "All backups have verification data"
        fi
    fi
}

# Export functions for subshells
export -f log log_success log_warn log_error log_info
export -f backup_expects_database smb_probe_dir
export -f ensure_smb_credentials test_smb_connection test_smb_connection_quiet
export -f smb_upload smb_download smb_delete smb_list_backups
export -f upload_with_retry save_to_pending upload_pending_backups
export -f update_backup_index get_backup_count remove_oldest_from_index
export -f apply_retention backup_checkpoint
export -f build_backup_manifest verify_backup
export -f ensure_backup_state_dir validate_index migrate_legacy_backup_index sync_index_from_smb

ensure_backup_state_dir
migrate_legacy_backup_index >/dev/null 2>&1 || true
