#!/bin/bash
#
# Infrastructure Restore Drill
# Validates a real restore into disposable containers
#
# Usage:
#   ./scripts/infra-restore-drill.sh <archive_path>
#
# Output: JSON result on stdout
#   { "ok": bool, "components": [{key, ok, error}], "duration_ms": int }
#
# Disposable containers are cleaned up on exit.

set -eo pipefail

ARCHIVE_PATH="${1:?Usage: infra-restore-drill.sh <archive_path>}"
DRILL_DIR="/tmp/infra-drill-$$"
DRILL_PG_CONTAINER="sf-drill-pg-$$"
DRILL_REDIS_CONTAINER="sf-drill-redis-$$"
START_TIME=$(date +%s%3N 2>/dev/null || echo "0")

cleanup() {
    docker rm -f "$DRILL_PG_CONTAINER" "$DRILL_REDIS_CONTAINER" 2>/dev/null || true
    [ -d "$DRILL_DIR" ] && rm -rf "$DRILL_DIR"
}
trap cleanup EXIT

results=()

add_result() {
    local key="$1" ok="$2" error="${3:-null}"
    if [ "$error" = "null" ]; then
        results+=("{\"key\":\"$key\",\"ok\":$ok,\"error\":null}")
    else
        error=$(echo "$error" | sed 's/"/\\"/g' | head -c 200)
        results+=("{\"key\":\"$key\",\"ok\":$ok,\"error\":\"$error\"}")
    fi
}

mkdir -p "$DRILL_DIR"
if ! tar xzf "$ARCHIVE_PATH" -C "$DRILL_DIR" 2>/dev/null; then
    echo '{"ok":false,"components":[{"key":"archive","ok":false,"error":"Failed to extract archive"}],"duration_ms":0}'
    exit 0
fi

EXTRACT_ROOT="$DRILL_DIR"
if [ -d "$DRILL_DIR/infrastructure" ]; then
    EXTRACT_ROOT="$DRILL_DIR/infrastructure"
fi

PG_DUMP=$(find "$EXTRACT_ROOT" -name "pgdumpall.sql.gz" -type f 2>/dev/null | head -1)
if [ -n "$PG_DUMP" ]; then
    docker run -d --name "$DRILL_PG_CONTAINER" \
        -e POSTGRES_PASSWORD=drill_test \
        -e POSTGRES_USER=admin \
        postgres:16-alpine >/dev/null 2>&1

    for i in $(seq 1 30); do
        if docker exec "$DRILL_PG_CONTAINER" pg_isready -U admin >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    if gunzip -c "$PG_DUMP" | docker exec -i "$DRILL_PG_CONTAINER" psql -U admin -d postgres >/dev/null 2>&1; then
        db_count=$(docker exec "$DRILL_PG_CONTAINER" psql -U admin -d postgres -tAc \
            "SELECT count(*) FROM pg_database WHERE datistemplate = false AND datname != 'postgres'" 2>/dev/null || echo "0")
        db_count=$(echo "$db_count" | tr -d '[:space:]')
        if [ "${db_count:-0}" -gt 0 ]; then
            add_result "postgres_dump" "true"
        else
            add_result "postgres_dump" "false" "Dump loaded but no user databases found"
        fi
    else
        add_result "postgres_dump" "false" "Failed to load pg_dumpall into disposable container"
    fi
else
    add_result "postgres_dump" "false" "pgdumpall.sql.gz not found in archive"
fi

REDIS_RDB=$(find "$EXTRACT_ROOT" -name "redis-dump.rdb" -type f 2>/dev/null | head -1)
if [ -n "$REDIS_RDB" ]; then
    HEADER=$(head -c 5 "$REDIS_RDB" 2>/dev/null || true)
    if [ "$HEADER" = "REDIS" ]; then
        docker run -d --name "$DRILL_REDIS_CONTAINER" \
            -v "$REDIS_RDB:/data/dump.rdb:ro" \
            redis:7-alpine redis-server --appendonly no >/dev/null 2>&1

        for i in $(seq 1 15); do
            if docker exec "$DRILL_REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -q PONG; then
                break
            fi
            sleep 1
        done

        key_count=$(docker exec "$DRILL_REDIS_CONTAINER" redis-cli dbsize 2>/dev/null | grep -oP '\d+' || echo "0")
        if [ "${key_count:-0}" -ge 0 ]; then
            add_result "redis_state" "true"
        else
            add_result "redis_state" "false" "Redis started but dbsize check failed"
        fi
    else
        add_result "redis_state" "false" "Invalid RDB header (expected REDIS magic bytes)"
    fi
else
    add_result "redis_state" "false" "redis-dump.rdb not found in archive"
fi

HATCHET_DIR=$(find "$EXTRACT_ROOT" -type d -name "hatchet-config" 2>/dev/null | head -1)
if [ -n "$HATCHET_DIR" ] && [ -d "$HATCHET_DIR" ]; then
    hatchet_files=$(find "$HATCHET_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
    if [ "${hatchet_files:-0}" -gt 0 ]; then
        if [ -f "$HATCHET_DIR/server.yaml" ] || find "$HATCHET_DIR" -name "*.yaml" -o -name "*.yml" 2>/dev/null | grep -q .; then
            add_result "hatchet_config" "true"
        else
            add_result "hatchet_config" "false" "Hatchet config dir exists but no YAML files found"
        fi
    else
        add_result "hatchet_config" "false" "Hatchet config dir is empty"
    fi
else
    add_result "hatchet_config" "false" "hatchet-config directory not found in archive"
fi

CONFIG_DIR=$(find "$EXTRACT_ROOT" -type d -name "configs" 2>/dev/null | head -1)

if [ -n "$CONFIG_DIR" ]; then
    if [ -f "$CONFIG_DIR/env.local" ]; then
        if grep -qE '(DATABASE_URL|DB_URL|PASSWORD)' "$CONFIG_DIR/env.local" 2>/dev/null; then
            add_result "env_local" "true"
        else
            add_result "env_local" "false" "env.local present but missing expected credential keys"
        fi
    else
        add_result "env_local" "false" "env.local not found in configs"
    fi

    if [ -f "$CONFIG_DIR/compose-env" ]; then
        add_result "compose_env" "true"
    else
        add_result "compose_env" "false" "compose-env not found in configs"
    fi

    if [ -f "$CONFIG_DIR/smbcredentials" ]; then
        add_result "smb_credentials" "true"
    else
        add_result "smb_credentials" "false" "smbcredentials not found in configs"
    fi
else
    add_result "env_local" "false" "configs directory not found"
    add_result "compose_env" "false" "configs directory not found"
    add_result "smb_credentials" "false" "configs directory not found"
fi

END_TIME=$(date +%s%3N 2>/dev/null || echo "0")
DURATION_MS=$((END_TIME - START_TIME))

overall_ok=true
for r in "${results[@]}"; do
    if echo "$r" | grep -q '"ok":false'; then
        overall_ok=false
        break
    fi
done

components_json=$(IFS=,; echo "${results[*]}")
echo "{\"ok\":$overall_ok,\"components\":[${components_json}],\"duration_ms\":$DURATION_MS}"
