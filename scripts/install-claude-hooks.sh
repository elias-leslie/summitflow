#!/bin/bash
# Install Claude Code hooks for SummitFlow observation capture
#
# Usage:
#   ./install-claude-hooks.sh [--uninstall]
#
# This script:
# 1. Creates ~/.claude/hooks/ directory if needed
# 2. Symlinks PostToolUse.sh hook from this repository
# 3. Makes hook executable
#
# Hooks capture tool executions and send to SummitFlow API for
# observation extraction and pattern learning.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_SOURCE="$SCRIPT_DIR/claude-hooks"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

uninstall_hooks() {
    log_info "Uninstalling SummitFlow Claude Code hooks..."

    if [ -L "$CLAUDE_HOOKS_DIR/PostToolUse.sh" ]; then
        rm "$CLAUDE_HOOKS_DIR/PostToolUse.sh"
        log_info "Removed PostToolUse.sh hook"
    else
        log_warn "PostToolUse.sh hook not found (already uninstalled?)"
    fi

    log_info "Uninstall complete!"
}

install_hooks() {
    log_info "Installing SummitFlow Claude Code hooks..."

    # Check source files exist
    if [ ! -f "$HOOKS_SOURCE/PostToolUse.sh" ]; then
        log_error "Hook source not found: $HOOKS_SOURCE/PostToolUse.sh"
        exit 1
    fi

    # Create hooks directory
    if [ ! -d "$CLAUDE_HOOKS_DIR" ]; then
        mkdir -p "$CLAUDE_HOOKS_DIR"
        log_info "Created $CLAUDE_HOOKS_DIR"
    fi

    # Install PostToolUse hook (symlink for easy updates)
    if [ -L "$CLAUDE_HOOKS_DIR/PostToolUse.sh" ]; then
        rm "$CLAUDE_HOOKS_DIR/PostToolUse.sh"
        log_info "Removing existing hook symlink"
    elif [ -f "$CLAUDE_HOOKS_DIR/PostToolUse.sh" ]; then
        log_warn "Existing PostToolUse.sh found (not a symlink), backing up..."
        mv "$CLAUDE_HOOKS_DIR/PostToolUse.sh" "$CLAUDE_HOOKS_DIR/PostToolUse.sh.backup"
    fi

    ln -s "$HOOKS_SOURCE/PostToolUse.sh" "$CLAUDE_HOOKS_DIR/PostToolUse.sh"
    log_info "Installed PostToolUse.sh hook"

    # Verify installation
    if [ -x "$CLAUDE_HOOKS_DIR/PostToolUse.sh" ]; then
        log_info "Hook is executable"
    else
        log_warn "Hook may not be executable, fixing..."
        chmod +x "$HOOKS_SOURCE/PostToolUse.sh"
    fi

    echo ""
    log_info "Installation complete!"
    echo ""
    echo "Configuration (environment variables):"
    echo "  SUMMITFLOW_PROJECT_ID  - Override project ID (default: from git/pwd)"
    echo "  SUMMITFLOW_API_URL     - API endpoint (default: http://localhost:8001/api)"
    echo "  SUMMITFLOW_ENABLED     - Set to '0' to disable (default: '1')"
    echo ""
    echo "Logs written to: ~/.claude/hooks/summitflow.log"
}

# Parse arguments
if [ "${1:-}" = "--uninstall" ]; then
    uninstall_hooks
else
    install_hooks
fi
