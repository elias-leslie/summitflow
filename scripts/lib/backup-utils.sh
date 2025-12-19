#!/bin/bash
#
# SummitFlow Backup Utilities
# Shared functions for backup and restore scripts
#

# Colors
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export RED='\033[0;31m'
export BLUE='\033[0;34m'
export NC='\033[0m'

# Configuration
export PROJECT_DIR="${PROJECT_DIR:-$HOME/summitflow}"
export SMB_HOST="192.168.8.128"
export SMB_SHARE="davion-gem"
export SMB_PATH="project-backups/summitflow"
export SMB_USER="${SMB_USER:-backup-svc}"
export CREDENTIALS_FILE="$HOME/.smbcredentials"
export BACKUP_INDEX="$PROJECT_DIR/backup-index.json"
export MAX_BACKUPS=30

# Database config - load from ~/.env.local if available
# Look for SUMMITFLOW_DB_URL first, then fallback to DATABASE_URL with summitflow in it
if [ -f "$HOME/.env.local" ]; then
    _db_url=$(grep "^SUMMITFLOW_DB_URL=" "$HOME/.env.local" 2>/dev/null | cut -d'=' -f2- || true)
    if [ -z "$_db_url" ]; then
        # Fallback: look for DATABASE_URL that contains summitflow
        _db_url=$(grep "^DATABASE_URL=.*summitflow" "$HOME/.env.local" 2>/dev/null | cut -d'=' -f2- || true)
    fi
    if [ -n "$_db_url" ]; then
        _db_userpass=$(echo "$_db_url" | sed -n 's|postgresql://\([^@]*\)@.*|\1|p')
        export DB_USER=$(echo "$_db_userpass" | cut -d':' -f1)
        export DB_PASSWORD=$(echo "$_db_userpass" | cut -d':' -f2)
        export DB_NAME=$(echo "$_db_url" | sed -n 's|.*/\([^?]*\).*|\1|p')
    fi
fi

# Fallback defaults
export DB_NAME="${DB_NAME:-summitflow}"
export DB_USER="${DB_USER:-summitflow_app}"
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

    # Claude transient data
    ".claude/backups"
    ".claude/plans"

    # Evidence/artifacts (regenerable)
    "data/artifacts"
    "data/evidence"
)

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

# Test SMB connectivity
test_smb_connection() {
    log "Testing SMB connection to //$SMB_HOST/$SMB_SHARE..."

    if smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" -c "ls $SMB_PATH" &>/dev/null; then
        log_success "SMB connection OK"
        return 0
    else
        log_error "SMB connection failed"
        return 1
    fi
}

# Upload file via smbclient
smb_upload() {
    local local_file="$1"
    local remote_dir="$2"
    local remote_name="${3:-$(basename "$local_file")}"

    log "Uploading $(basename "$local_file") to //$SMB_HOST/$SMB_SHARE/$remote_dir..."

    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" << EOF
mkdir $remote_dir
cd $remote_dir
put $local_file $remote_name
EOF

    if [ $? -eq 0 ]; then
        log_success "Upload complete"
        return 0
    else
        log_error "Upload failed"
        return 1
    fi
}

# List remote backups
smb_list_backups() {
    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" -c "cd $SMB_PATH; ls summitflow-*.tar.gz" 2>/dev/null | \
        grep "summitflow-" | awk '{print $1}' | sort
}

# Download file via smbclient
smb_download() {
    local remote_file="$1"
    local local_path="$2"

    log "Downloading $remote_file..."

    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" << EOF
cd $SMB_PATH
get $remote_file $local_path
EOF

    if [ $? -eq 0 ]; then
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

    smbclient "//$SMB_HOST/$SMB_SHARE" -A "$CREDENTIALS_FILE" << EOF
cd $SMB_PATH
rm $remote_file
EOF
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
  "retention": $MAX_BACKUPS,
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

# Apply retention policy
apply_retention() {
    log "Applying retention policy (keep newest $MAX_BACKUPS)..."

    local backups=($(smb_list_backups))
    local count=${#backups[@]}

    if [ "$count" -le "$MAX_BACKUPS" ]; then
        log_success "Retention OK: $count/$MAX_BACKUPS backups"
        return 0
    fi

    local to_delete=$((count - MAX_BACKUPS))
    log "Deleting $to_delete old backup(s)..."

    for ((i=0; i<to_delete; i++)); do
        local old_backup="${backups[$i]}"
        smb_delete "$old_backup"
    done

    log_success "Retention applied: now $MAX_BACKUPS backups"
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
        sed 's|^summitflow/\./||;s|^summitflow/||' | \
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

    local total_files checksum has_db
    total_files=$(tar -tzf "$archive_path" | grep -v '/$' | wc -l | tr -d ' ')
    checksum=$(sha256sum "$archive_path" | cut -d' ' -f1)
    has_db=$(tar -tzf "$archive_path" | grep -c "database.sql.gz" || echo "0")

    local verified="true"
    local errors="[]"
    if [ "$has_db" -eq 0 ]; then
        verified="false"
        errors='["Critical: database.sql.gz missing"]'
    fi

    echo "{\"verified\":$verified,\"verified_at\":\"$(date -Iseconds)\",\"errors\":$errors,\"tree\":$tree_json,\"total_files\":$total_files,\"checksum\":\"sha256:$checksum\"}"
}

# Export functions
export -f log log_success log_warn log_error log_info
export -f ensure_smb_credentials test_smb_connection
export -f smb_upload smb_download smb_delete smb_list_backups
export -f update_backup_index apply_retention verify_backup
