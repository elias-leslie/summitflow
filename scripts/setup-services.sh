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
    local terminal_root
    terminal_root="$(resolve_project_root terminal 2>/dev/null || true)"
    local escaped_terminal_root
    escaped_terminal_root=$(escape_sed_replacement "$terminal_root")
    sed \
        -e "s|__SUMMITFLOW_ROOT__|$escaped_root|g" \
        -e "s|__PROJECT_ROOT__|$escaped_project_root|g" \
        -e "s|__TERMINAL_ROOT__|$escaped_terminal_root|g" \
        "$src" > "$dest"
}

declare -a RENDERED_UNITS=()

render_unit_tree() {
    local source_root="$1"
    local project_root="${2:-}"
    local unit_file unit_name
    [ -d "$source_root" ] || return 0
    for unit_file in "$source_root"/*.{service,timer}; do
        [ -f "$unit_file" ] || continue
        unit_name="$(basename "$unit_file")"
        rm -f "$USER_SYSTEMD_DIR/$unit_name"
        render_unit_file "$unit_file" "$USER_SYSTEMD_DIR/$unit_name" "$project_root"
        echo "    $unit_name"
        RENDERED_UNITS+=("$unit_name")
    done
}

run_user_systemctl() {
    timeout --foreground "$SYSTEMCTL_USER_TIMEOUT" systemctl --user "$@"
}

install_cli_links() {
    local summitflow_st="$SUMMITFLOW_DIR/backend/.venv/bin/st"
    local summitflow_dt="$SUMMITFLOW_DIR/scripts/dev-tools.sh"
    local agent_hub_root=""
    local terminal_root=""
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

    terminal_root="$(resolve_project_root terminal 2>/dev/null || true)"
    if [ -n "$terminal_root" ] && [ -f "$terminal_root/scripts/tcodex" ]; then
        ln -sfnT "$terminal_root/scripts/tcodex" "$BIN_DIR/tcodex"
        echo "  Linked tcodex -> $terminal_root/scripts/tcodex"
    fi
    if [ -n "$terminal_root" ] && [ -f "$terminal_root/scripts/tclaude" ]; then
        ln -sfnT "$terminal_root/scripts/tclaude" "$BIN_DIR/tclaude"
        echo "  Linked tclaude -> $terminal_root/scripts/tclaude"
    fi
    if [ -n "$terminal_root" ] && [ -f "$terminal_root/scripts/tsession" ]; then
        ln -sfnT "$terminal_root/scripts/tsession" "$BIN_DIR/tsession"
        echo "  Linked tsession -> $terminal_root/scripts/tsession"
    fi

    for script_name in rebuild.sh commit.sh start.sh status.sh stop.sh backup.sh backup-all.sh restore.sh setup-services.sh; do
        if [ -f "$SUMMITFLOW_DIR/scripts/$script_name" ]; then
            ln -sfnT "$SUMMITFLOW_DIR/scripts/$script_name" "$BIN_DIR/$script_name"
            echo "  Linked $script_name -> $SUMMITFLOW_DIR/scripts/$script_name"
        fi
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

for external_project in agent-hub portfolio-ai monkey-fight; do
    external_root="$(resolve_project_root "$external_project" 2>/dev/null || true)"
    [ -n "$external_root" ] || continue
    render_unit_tree "$external_root/scripts/systemd" "$external_root"
done

UNITS_LINKED="${#RENDERED_UNITS[@]}"
echo "  Rendered $UNITS_LINKED unit files"

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
