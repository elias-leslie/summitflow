#!/bin/bash
#
# Storage Backend Integration
# Queries storage_backends table for SMB config when STORAGE_BACKEND_ID is set.
# Exports SMB_HOST, SMB_SHARE, etc. as env vars.
# Falls back to existing env/file-based config if no DB backend.
#

# Only activate if a backend ID is specified
if [ -z "${STORAGE_BACKEND_ID:-}" ]; then
    return 0 2>/dev/null || exit 0
fi

# Need psql to query the DB
if ! command -v psql &>/dev/null; then
    echo "Warning: psql not available, cannot resolve storage backend" >&2
    return 0 2>/dev/null || exit 0
fi

# Resolve DATABASE_URL for psql
_sb_db_url="${DATABASE_URL:-}"
if [ -z "$_sb_db_url" ] && [ -f "$HOME/.env.local" ]; then
    _sb_db_url=$(grep "^DATABASE_URL=" "$HOME/.env.local" 2>/dev/null | cut -d'=' -f2- || true)
fi

if [ -z "$_sb_db_url" ]; then
    echo "Warning: No DATABASE_URL, cannot resolve storage backend" >&2
    return 0 2>/dev/null || exit 0
fi

# Query the storage_backends table
_sb_config=$(psql "$_sb_db_url" -t -A -c "
    SELECT config::text FROM storage_backends
    WHERE id = '$STORAGE_BACKEND_ID' AND enabled = true
    LIMIT 1
" 2>/dev/null)

if [ -z "$_sb_config" ]; then
    echo "Warning: Storage backend '$STORAGE_BACKEND_ID' not found or disabled" >&2
    return 0 2>/dev/null || exit 0
fi

# Parse JSON config and export SMB vars
if command -v jq &>/dev/null; then
    _sb_host=$(echo "$_sb_config" | jq -r '.host // empty')
    _sb_share=$(echo "$_sb_config" | jq -r '.share // empty')
    _sb_path=$(echo "$_sb_config" | jq -r '.path // empty')
    _sb_user=$(echo "$_sb_config" | jq -r '.user // empty')
    _sb_cred=$(echo "$_sb_config" | jq -r '.credentials_file // empty')

    [ -n "$_sb_host" ] && export SMB_HOST="$_sb_host"
    [ -n "$_sb_share" ] && export SMB_SHARE="$_sb_share"
    [ -n "$_sb_path" ] && export SMB_PATH="$_sb_path"
    [ -n "$_sb_user" ] && export SMB_USER="$_sb_user"
    [ -n "$_sb_cred" ] && export CREDENTIALS_FILE="$_sb_cred"
fi

unset _sb_db_url _sb_config _sb_host _sb_share _sb_path _sb_user _sb_cred
