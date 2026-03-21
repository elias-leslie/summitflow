#!/bin/bash
# SummitFlow Service Setup Script
# RUN THIS AS YOUR USER (with sudo prompts when needed)
#
# This script:
# 1. Symlinks systemd user units (.service + .timer)
# 2. Enables long-running services
# 3. Enables and starts timer-managed units

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMITFLOW_DIR="$(dirname "$SCRIPT_DIR")"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
SYSTEMCTL_USER_TIMEOUT="${SYSTEMCTL_USER_TIMEOUT:-20}"
SUMMITFLOW_SCRIPTS_PATH="$SUMMITFLOW_DIR/scripts"

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

render_unit_file() {
    local src="$1"
    local dest="$2"
    local escaped_root
    escaped_root=$(escape_sed_replacement "$SUMMITFLOW_DIR")
    sed "s|__SUMMITFLOW_ROOT__|$escaped_root|g" "$src" > "$dest"
}

run_user_systemctl() {
    timeout --foreground "$SYSTEMCTL_USER_TIMEOUT" systemctl --user "$@"
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
UNITS_LINKED=0
for unit_file in "$SUMMITFLOW_DIR"/scripts/systemd/*.{service,timer}; do
    [ -f "$unit_file" ] || continue
    unit_name="$(basename "$unit_file")"
    rm -f "$USER_SYSTEMD_DIR/$unit_name"
    render_unit_file "$unit_file" "$USER_SYSTEMD_DIR/$unit_name"
    echo "    $unit_name"
    UNITS_LINKED=$((UNITS_LINKED + 1))
done
echo "  Rendered $UNITS_LINKED unit files"

# Step 3: Reload systemd user daemon
echo "  Reloading systemd user daemon..."
if ! run_user_systemctl daemon-reload; then
    echo "  ERROR: systemctl --user daemon-reload failed or timed out" >&2
    exit 1
fi

# Build a set of timer-managed service names so they are enabled via timers, not directly.
declare -A TIMER_MANAGED_SERVICES=()
for timer_file in "$SUMMITFLOW_DIR"/scripts/systemd/*.timer; do
    [ -f "$timer_file" ] || continue
    timer_name="$(basename "$timer_file" .timer)"
    TIMER_MANAGED_SERVICES["$timer_name"]=1
done

# Step 4: Enable long-running services
echo "  Enabling long-running services..."
for svc_file in "$SUMMITFLOW_DIR"/scripts/systemd/*.service; do
    [ -f "$svc_file" ] || continue
    svc_name="$(basename "$svc_file")"
    svc_base="${svc_name%.service}"
    if [[ -n "${TIMER_MANAGED_SERVICES[$svc_base]:-}" ]]; then
        echo "    skipped $svc_name (timer-managed)"
        continue
    fi
    run_user_systemctl enable "$svc_name" 2>/dev/null && echo "    enabled $svc_name" || echo "    skipped $svc_name (may require dependencies)"
done

# Step 5: Enable timers now so observability and maintenance jobs start immediately.
echo "  Enabling timers..."
for timer_file in "$SUMMITFLOW_DIR"/scripts/systemd/*.timer; do
    [ -f "$timer_file" ] || continue
    timer_name="$(basename "$timer_file")"
    run_user_systemctl enable --now "$timer_name" 2>/dev/null && echo "    enabled $timer_name" || echo "    skipped $timer_name (may require dependencies)"
done

echo "  ✓ Systemd units configured"
echo ""

# Step 6: Ensure the installed SummitFlow scripts directory is on PATH
echo "Step 6: Checking PATH setup..."
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
