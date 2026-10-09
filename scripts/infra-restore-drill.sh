#!/bin/bash
#
# Infrastructure Restore Drill
# Validates a real restore into disposable containers
#
# Usage:
#   Called by SummitFlow with a validated private ST_RESTORE_DRILL_ROOT.
#
# Output: JSON result on stdout
#   { "ok": bool, "components": [{key, ok, error}], "duration_ms": int }
#
# Disposable containers are cleaned up on exit.

set -eo pipefail

ARCHIVE_PATH="${1:?Usage: infra-restore-drill.sh <archive_path>}"
if [[ "$ARCHIVE_PATH" == *.age ]]; then
    echo '{"ok":false,"components":[{"key":"archive","ok":false,"error":"Encrypted archives must be materialized by SummitFlow before running the drill"}],"duration_ms":0}'
    exit 0
fi
DRILL_DIR="${ST_RESTORE_DRILL_ROOT:?Run the drill through SummitFlow scratch admission}"
DRILL_ID="${ST_RESTORE_DRILL_ID:?Missing owned drill identifier}"
if [[ "$DRILL_DIR" != /* || -L "$DRILL_DIR" || ! -d "$DRILL_DIR" ]] \
    || [[ "$(realpath "$DRILL_DIR")" != "$DRILL_DIR" ]] \
    || [[ "$(stat -c '%u:%a' "$DRILL_DIR")" != "$(id -u):700" ]] \
    || [[ "$DRILL_ID" != infra-drill-* || "$DRILL_ID" == *[^a-zA-Z0-9_-]* ]]; then
    echo '{"ok":false,"components":[{"key":"scratch","ok":false,"error":"Drill requires a private owned scratch directory"}],"duration_ms":0}'
    exit 1
fi
DRILL_PG_CONTAINER="sf-drill-pg-$DRILL_ID"
DRILL_REDIS_CONTAINER="sf-drill-redis-$DRILL_ID"
START_TIME=$(date +%s%3N 2>/dev/null || echo "0")

cleanup() {
    # Explicit data bind mounts keep database writes off Docker's root volume.
    docker rm -fv "$DRILL_PG_CONTAINER" "$DRILL_REDIS_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

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

umask 077
mkdir "$DRILL_DIR/extracted"
if ! tar xzf "$ARCHIVE_PATH" -C "$DRILL_DIR/extracted" --no-same-owner --no-same-permissions 2>/dev/null; then
    echo '{"ok":false,"components":[{"key":"archive","ok":false,"error":"Failed to extract archive"}],"duration_ms":0}'
    exit 0
fi

EXTRACT_ROOT="$DRILL_DIR/extracted"
if [ -d "$EXTRACT_ROOT/infrastructure" ]; then
    EXTRACT_ROOT="$EXTRACT_ROOT/infrastructure"
fi

PG_DUMP=$(find "$EXTRACT_ROOT" -name "pgdumpall.sql.gz" -type f 2>/dev/null | head -1)
if [ -n "$PG_DUMP" ]; then
    mkdir "$DRILL_DIR/postgres"
    docker run -d --name "$DRILL_PG_CONTAINER" --pull never --network none \
        --user "$(id -u):$(id -g)" \
        --mount "type=bind,source=$DRILL_DIR/postgres,target=/var/lib/postgresql/data" \
        --tmpfs /var/run/postgresql:rw,mode=1777 --tmpfs /tmp:rw,mode=1777 \
        -e POSTGRES_PASSWORD=drill_test \
        pgvector/pgvector:pg16 -c listen_addresses='' >/dev/null 2>&1

    for _ in $(seq 1 30); do
        if docker exec "$DRILL_PG_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    # The disposable postgres image already creates the bootstrap postgres role.
    # pg_dumpall includes that role, so drop only the bootstrap role statements
    # and keep ON_ERROR_STOP for real restore failures.
    if gunzip -c "$PG_DUMP" \
        | sed -e '/^CREATE ROLE postgres;$/d' -e '/^ALTER ROLE postgres /d' \
        | docker exec -i "$DRILL_PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d postgres >/dev/null 2>&1; then
        db_count=$(docker exec "$DRILL_PG_CONTAINER" psql -U postgres -d postgres -tAc \
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
        mkdir "$DRILL_DIR/redis"
        cp "$REDIS_RDB" "$DRILL_DIR/redis/dump.rdb"
        if ! docker run -d --name "$DRILL_REDIS_CONTAINER" --pull never --network none \
            --user "$(id -u):$(id -g)" --entrypoint redis-server \
            --mount "type=bind,source=$DRILL_DIR/redis,target=/data" \
            redis:7-alpine --dir /data --appendonly no --save "" >/dev/null 2>&1; then
            add_result "redis_state" "false" "Failed to start disposable Redis container"
        else
            redis_ready=false
            for _ in $(seq 1 15); do
                if ping_output=$(docker exec "$DRILL_REDIS_CONTAINER" redis-cli --raw ping 2>/dev/null) \
                    && [ "$ping_output" = "PONG" ]; then
                    redis_ready=true
                    break
                fi
                sleep 1
            done

            if [ "$redis_ready" != true ]; then
                add_result "redis_state" "false" "Redis did not become ready with a successful PONG"
            elif key_count=$(docker exec "$DRILL_REDIS_CONTAINER" redis-cli --raw dbsize 2>/dev/null) \
                && [[ "$key_count" =~ ^[0-9]+$ ]]; then
                add_result "redis_state" "true"
            else
                add_result "redis_state" "false" "Redis started but dbsize check failed"
            fi
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
