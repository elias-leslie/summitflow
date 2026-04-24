#!/usr/bin/env bash
# Bootstrap Claude/Codex CLI tooling plus SummitFlow hook/memory integrations.

set -euo pipefail

case "${1:-}" in
  --help|-h|help)
    cat <<'EOF'
Usage: st setup agent-tooling [--dry-run] [--confirm TOKEN]

Install shared Codex/Claude operator tooling. Run through st so
preview/confirmation stays consistent.
EOF
    exit 0
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMITFLOW_DIR="$(dirname "$SCRIPT_DIR")"

CLAUDE_CONFIG_REPO="${CLAUDE_CONFIG_REPO:-git@github.com:elias-leslie/claude-config.git}"
CODEX_CONFIG_REPO="${CODEX_CONFIG_REPO:-git@github.com:elias-leslie/codex-config.git}"
CLAUDE_HOME_DIR="${CLAUDE_HOME_DIR:-$HOME/.claude}"
CODEX_HOME_DIR="${CODEX_HOME_DIR:-$HOME/.codex}"
BIN_DIR="${BIN_DIR:-$HOME/bin}"
CODEX_WRAPPER_SOURCE="${CODEX_WRAPPER_SOURCE:-$CODEX_HOME_DIR/bin/codex}"

INSTALL_CLAUDE_CLI="${INSTALL_CLAUDE_CLI:-1}"
INSTALL_CODEX_CLI="${INSTALL_CODEX_CLI:-1}"
UPDATE_EXISTING_CONFIGS="${UPDATE_EXISTING_CONFIGS:-0}"

ensure_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

ensure_repo() {
  local repo_url="$1"
  local target_dir="$2"

  if [[ -d "$target_dir/.git" ]]; then
    if [[ "$UPDATE_EXISTING_CONFIGS" == "1" ]]; then
      git -C "$target_dir" fetch --all --tags
      git -C "$target_dir" pull --ff-only
      echo "Updated $target_dir"
    else
      echo "Keeping existing repo at $target_dir"
    fi
    return
  fi

  if [[ -e "$target_dir" ]]; then
    echo "Target exists but is not a git repo: $target_dir" >&2
    exit 1
  fi

  git clone "$repo_url" "$target_dir"
  echo "Cloned $repo_url -> $target_dir"
}

install_codex_wrapper() {
  mkdir -p "$BIN_DIR"
  if [[ ! -x "$CODEX_WRAPPER_SOURCE" ]]; then
    echo "Expected Codex wrapper in codex-config repo: $CODEX_WRAPPER_SOURCE" >&2
    exit 1
  fi
  ln -sf "$CODEX_WRAPPER_SOURCE" "$BIN_DIR/codex"
  echo "Installed Codex wrapper at $BIN_DIR/codex"
}

install_cli() {
  local package_name="$1"
  local command_name="$2"

  npm install -g "$package_name"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Installed $package_name but '$command_name' is still not on PATH" >&2
    exit 1
  fi
}

echo "================================"
echo "Agent Tooling Setup"
echo "================================"

ensure_cmd git
ensure_cmd node
ensure_cmd npm
ensure_cmd python3
ensure_cmd curl
ensure_cmd jq
ensure_cmd tmux

ensure_repo "$CLAUDE_CONFIG_REPO" "$CLAUDE_HOME_DIR"
ensure_repo "$CODEX_CONFIG_REPO" "$CODEX_HOME_DIR"
install_codex_wrapper

if [[ "$INSTALL_CLAUDE_CLI" == "1" ]]; then
  install_cli "@anthropic-ai/claude-code" "claude"
fi

if [[ "$INSTALL_CODEX_CLI" == "1" ]]; then
  install_cli "@openai/codex" "codex"
fi

echo "Run 'st setup services' separately for systemd sync; it uses two-pass confirmation."

if ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
  echo "WARNING: $BIN_DIR is not in PATH; add it before using the Codex wrapper." >&2
fi

echo ""
echo "Next steps:"
echo "  1. Authenticate Claude Code by running: claude"
echo "  2. Authenticate Codex CLI by running: codex --login"
echo "  3. Verify coordination sync with: st pulse --project summitflow"
