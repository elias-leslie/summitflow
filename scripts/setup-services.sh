#!/bin/bash
# SummitFlow Service Setup Script
# RUN THIS AS YOUR USER (with sudo prompts when needed)
#
# This script:
# 1. Symlinks systemd user units (.service + .timer)
# 2. Enables long-running services
# 3. Enables and starts timer-managed units

set -e

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
SUMMITFLOW_DIR="$(dirname "$SCRIPT_DIR")"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
MANAGED_UNITS_STATE_DIR="$USER_SYSTEMD_DIR/.managed-unit-manifests"
SYSTEMCTL_USER_TIMEOUT="${SYSTEMCTL_USER_TIMEOUT:-20}"
SUMMITFLOW_SCRIPTS_PATH="$SUMMITFLOW_DIR/scripts"
SUMMITFLOW_ROOT_OVERRIDE="$SUMMITFLOW_DIR"
. "$SCRIPT_DIR/lib/project-roots.sh"
BIN_DIR="${BIN_DIR:-$HOME/bin}"

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

render_unit_file() {
    local src="$1"
    local dest="$2"
    local project_root="${3:-}"
    local escaped_root
    escaped_root=$(escape_sed_replacement "$SUMMITFLOW_DIR")
    local escaped_project_root
    escaped_project_root=$(escape_sed_replacement "$project_root")
    sed \
        -e "s|__SUMMITFLOW_ROOT__|$escaped_root|g" \
        -e "s|__PROJECT_ROOT__|$escaped_project_root|g" \
        "$src" > "$dest"
}

declare -a RENDERED_UNITS=()
declare -a PRUNED_UNITS=()

array_contains() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        [ "$item" = "$needle" ] && return 0
    done
    return 1
}

manifest_path_for_source() {
    local source_root="$1"
    local key
    mkdir -p "$MANAGED_UNITS_STATE_DIR"
    key="$(printf '%s' "$source_root" | sha256sum | awk '{print $1}')"
    printf '%s/%s.units\n' "$MANAGED_UNITS_STATE_DIR" "$key"
}

legacy_units_for_source() {
    local source_root="$1"
    case "$source_root" in
        */agent-hub/scripts/systemd)
            printf '%s\n' "agent-hub-hatchet-worker.service"
            ;;
    esac
}

render_unit_tree() {
    local source_root="$1"
    local project_root="${2:-}"
    local unit_file unit_name manifest_file
    local -a desired_units=()
    local -a previous_units=()
    local legacy_unit
    [ -d "$source_root" ] || return 0

    for unit_file in "$source_root"/*.{service,timer}; do
        [ -f "$unit_file" ] || continue
        desired_units+=("$(basename "$unit_file")")
    done

    manifest_file="$(manifest_path_for_source "$source_root")"
    if [ -f "$manifest_file" ]; then
        mapfile -t previous_units < "$manifest_file"
    fi
    while IFS= read -r legacy_unit; do
        [ -n "$legacy_unit" ] || continue
        if ! array_contains "$legacy_unit" "${previous_units[@]}"; then
            previous_units+=("$legacy_unit")
        fi
    done < <(legacy_units_for_source "$source_root")

    for unit_name in "${previous_units[@]}"; do
        [ -n "$unit_name" ] || continue
        if ! array_contains "$unit_name" "${desired_units[@]}"; then
            run_user_systemctl disable --now "$unit_name" >/dev/null 2>&1 || true
            run_user_systemctl reset-failed "$unit_name" >/dev/null 2>&1 || true
            rm -f "$USER_SYSTEMD_DIR/$unit_name"
            echo "    pruned $unit_name"
            PRUNED_UNITS+=("$unit_name")
        fi
    done

    for unit_file in "$source_root"/*.{service,timer}; do
        [ -f "$unit_file" ] || continue
        unit_name="$(basename "$unit_file")"
        rm -f "$USER_SYSTEMD_DIR/$unit_name"
        render_unit_file "$unit_file" "$USER_SYSTEMD_DIR/$unit_name" "$project_root"
        echo "    $unit_name"
        RENDERED_UNITS+=("$unit_name")
    done

    : > "$manifest_file"
    for unit_name in "${desired_units[@]}"; do
        printf '%s\n' "$unit_name" >> "$manifest_file"
    done
}

run_user_systemctl() {
    timeout --foreground "$SYSTEMCTL_USER_TIMEOUT" systemctl --user "$@"
}

install_cli_links() {
    local summitflow_st="$SUMMITFLOW_DIR/backend/.venv/bin/st"
    local summitflow_dt="$SUMMITFLOW_DIR/scripts/dev-tools.sh"
    local agent_hub_root=""
    local a_term_root=""
    local script_name=""

    mkdir -p "$BIN_DIR"

    if [ -x "$summitflow_st" ]; then
        ln -sfnT "$summitflow_st" "$BIN_DIR/st"
        echo "  Linked st -> $summitflow_st"
    fi

    if [ -f "$summitflow_dt" ]; then
        ln -sfnT "$summitflow_dt" "$BIN_DIR/dt"
        echo "  Linked dt -> $summitflow_dt"
    fi

    agent_hub_root="$(resolve_project_root agent-hub 2>/dev/null || true)"
    if [ -n "$agent_hub_root" ] && [ -f "$agent_hub_root/scripts/db.sh" ]; then
        ln -sfnT "$agent_hub_root/scripts/db.sh" "$BIN_DIR/db"
        echo "  Linked db -> $agent_hub_root/scripts/db.sh"
    fi

    a_term_root="$(resolve_project_root a-term 2>/dev/null || true)"
    if [ -n "$a_term_root" ] && [ -f "$a_term_root/scripts/tcodex" ]; then
        ln -sfnT "$a_term_root/scripts/tcodex" "$BIN_DIR/tcodex"
        echo "  Linked tcodex -> $a_term_root/scripts/tcodex"
    fi
    if [ -n "$a_term_root" ] && [ -f "$a_term_root/scripts/tclaude" ]; then
        ln -sfnT "$a_term_root/scripts/tclaude" "$BIN_DIR/tclaude"
        echo "  Linked tclaude -> $a_term_root/scripts/tclaude"
    fi
    if [ -n "$a_term_root" ] && [ -f "$a_term_root/scripts/tsession" ]; then
        ln -sfnT "$a_term_root/scripts/tsession" "$BIN_DIR/tsession"
        echo "  Linked tsession -> $a_term_root/scripts/tsession"
    fi

    for script_name in rebuild.sh commit.sh start.sh status.sh stop.sh backup.sh backup-all.sh restore.sh setup-services.sh; do
        if [ -f "$SUMMITFLOW_DIR/scripts/$script_name" ]; then
            ln -sfnT "$SUMMITFLOW_DIR/scripts/$script_name" "$BIN_DIR/$script_name"
            echo "  Linked $script_name -> $SUMMITFLOW_DIR/scripts/$script_name"
        fi
    done
}

sync_shared_cache_link() {
    local cache_name="$1"
    local source_dir="$HOME/.cache/$cache_name"
    local target_dir
    target_dir="$(shared_cache_dir "$cache_name")"

    mkdir -p "$HOME/.cache"
    mkdir -p "$(dirname "$target_dir")"
    mkdir -p "$target_dir"

    if [ -L "$source_dir" ] && [ "$(readlink -f "$source_dir")" = "$target_dir" ]; then
        echo "  Cache $cache_name already linked -> $target_dir"
        return 0
    fi

    if [ -d "$source_dir" ] && [ ! -L "$source_dir" ]; then
        if command -v rsync >/dev/null 2>&1; then
            rsync -a "$source_dir"/ "$target_dir"/
        elif find "$source_dir" -mindepth 1 -print -quit >/dev/null 2>&1; then
            cp -a "$source_dir"/. "$target_dir"/
        fi
        rm -rf "$source_dir"
    elif [ -e "$source_dir" ] && [ ! -L "$source_dir" ]; then
        rm -f "$source_dir"
    fi

    ln -sfnT "$target_dir" "$source_dir"
    echo "  Linked cache $cache_name -> $target_dir"
}

sync_shared_caches() {
    local cache_name
    for cache_name in uv pip pnpm; do
        sync_shared_cache_link "$cache_name"
    done
}

echo "================================"
echo "SummitFlow Service Setup"
echo "================================"
echo ""
echo "SummitFlow directory: $SUMMITFLOW_DIR"
echo "User systemd dir: $USER_SYSTEMD_DIR"
echo ""

# Step 1: Create user systemd directory if needed
echo "Step 1: Setting up systemd user services..."
mkdir -p "$USER_SYSTEMD_DIR"

# Step 2: Render unit files with the installed repo root.
echo "  Rendering unit files..."
render_unit_tree "$SUMMITFLOW_DIR/scripts/systemd"

for external_project in a-term agent-hub portfolio-ai monkey-fight vantage test1 test2 test3; do
    external_root="$(resolve_project_root "$external_project" 2>/dev/null || true)"
    [ -n "$external_root" ] || continue
    render_unit_tree "$external_root/scripts/systemd" "$external_root"
done

UNITS_LINKED="${#RENDERED_UNITS[@]}"
echo "  Rendered $UNITS_LINKED unit files"
if [ "${#PRUNED_UNITS[@]}" -gt 0 ]; then
    echo "  Pruned ${#PRUNED_UNITS[@]} stale unit files"
fi

# Step 3: Reload systemd user daemon
echo "  Reloading systemd user daemon..."
if ! run_user_systemctl daemon-reload; then
    echo "  ERROR: systemctl --user daemon-reload failed or timed out" >&2
    exit 1
fi

# Build a set of timer-managed service names so they are enabled via timers, not directly.
declare -A TIMER_MANAGED_SERVICES=()
for unit_name in "${RENDERED_UNITS[@]}"; do
    if [[ "$unit_name" == *.timer ]]; then
        timer_name="${unit_name%.timer}"
        TIMER_MANAGED_SERVICES["$timer_name"]=1
    fi
done

# Step 4: Enable long-running services
echo "  Enabling long-running services..."
for svc_name in "${RENDERED_UNITS[@]}"; do
    [[ "$svc_name" == *.service ]] || continue
    svc_base="${svc_name%.service}"
    if [[ -n "${TIMER_MANAGED_SERVICES[$svc_base]:-}" ]]; then
        echo "    skipped $svc_name (timer-managed)"
        continue
    fi
    run_user_systemctl enable "$svc_name" 2>/dev/null && echo "    enabled $svc_name" || echo "    skipped $svc_name (may require dependencies)"
done

# Step 5: Enable timers now so observability and maintenance jobs start immediately.
echo "  Enabling timers..."
for timer_name in "${RENDERED_UNITS[@]}"; do
    [[ "$timer_name" == *.timer ]] || continue
    run_user_systemctl enable --now "$timer_name" 2>/dev/null && echo "    enabled $timer_name" || echo "    skipped $timer_name (may require dependencies)"
done

echo "  ✓ Systemd units configured"
echo ""

# Step 6: Refresh CLI entrypoints used by humans and timers
echo "Step 6: Refreshing CLI entrypoints..."
install_cli_links
echo "  ✓ CLI entrypoints refreshed"
echo ""

echo "Step 6b: Refreshing managed repo fallback registry..."
write_managed_repo_file
echo "  Updated $PROJECT_ROOTS_MANAGED_REPOS_FILE"
echo "  ✓ Managed repo fallback refreshed"
echo ""

echo "Step 6c: Migrating shared dependency caches onto Btrfs..."
sync_shared_caches
echo "  ✓ Shared caches refreshed"
echo ""

# Step 7: Ensure the installed SummitFlow scripts directory is on PATH
echo "Step 7: Checking PATH setup..."
SHELL_RC="$HOME/.bashrc"
[ -n "$ZSH_VERSION" ] && SHELL_RC="$HOME/.zshrc"
PATH_EXPORT_LINE="export PATH=\"$SUMMITFLOW_SCRIPTS_PATH:\$PATH\""

if ! grep -Fq "$SUMMITFLOW_SCRIPTS_PATH" "$SHELL_RC" 2>/dev/null; then
    if grep -q 'summitflow/scripts' "$SHELL_RC" 2>/dev/null; then
        tmp_rc="$(mktemp)"
        awk -v replacement="$PATH_EXPORT_LINE" '
            BEGIN { replaced = 0 }
            /^# SummitFlow scripts / { next }
            /export PATH=.*summitflow\/scripts/ {
                if (!replaced) {
                    print replacement
                    replaced = 1
                }
                next
            }
            { print }
            END {
                if (!replaced) {
                    print ""
                    print "# SummitFlow scripts (rebuild.sh, sf-browser, etc.)"
                    print replacement
                }
            }
        ' "$SHELL_RC" > "$tmp_rc"
        mv "$tmp_rc" "$SHELL_RC"
        echo "  Updated SummitFlow scripts PATH in $SHELL_RC"
    else
    echo '' >> "$SHELL_RC"
    echo '# SummitFlow scripts (rebuild.sh, sf-browser, etc.)' >> "$SHELL_RC"
        echo "$PATH_EXPORT_LINE" >> "$SHELL_RC"
        echo "  Added $SUMMITFLOW_SCRIPTS_PATH to PATH in $SHELL_RC"
    fi
else
    echo "  $SUMMITFLOW_SCRIPTS_PATH already on PATH"
fi
echo "  ✓ PATH configured"
echo ""

echo "================================"
echo "✓ Setup complete!"
echo "================================"
echo ""
echo "To start SummitFlow services:"
echo "  start.sh"
echo ""
echo "To check status:"
echo "  status.sh"
echo ""
echo "Access URLs:"
echo "  - Local Backend:  http://localhost:8001"
echo "  - Local Frontend: http://localhost:3001"
echo ""
