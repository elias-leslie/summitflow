#!/usr/bin/env bash
# Install or update GitHub CLI from GitHub's official apt repository.

set -euo pipefail

REPO_URL="https://cli.github.com/packages"
KEYRING_PATH="/etc/apt/keyrings/githubcli-archive-keyring.gpg"
SOURCE_PATH="/etc/apt/sources.list.d/github-cli.list"

as_root() {
    if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

require_command() {
    local command_name="$1"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Missing required command: $command_name" >&2
        exit 1
    fi
}

if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg >/dev/null 2>&1; then
    echo "update-gh.sh currently supports Debian/Ubuntu systems with apt." >&2
    exit 1
fi

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    require_command sudo
fi

arch="$(dpkg --print-architecture)"
tmp_key="$(mktemp)"
tmp_source="$(mktemp)"
trap 'rm -f "$tmp_key" "$tmp_source"' EXIT

echo "Installing GitHub CLI apt repository..."
as_root apt-get update
as_root apt-get install -y ca-certificates curl

curl -fsSL "$REPO_URL/githubcli-archive-keyring.gpg" -o "$tmp_key"
as_root install -D -m 0644 "$tmp_key" "$KEYRING_PATH"

printf 'deb [arch=%s signed-by=%s] %s stable main\n' "$arch" "$KEYRING_PATH" "$REPO_URL" > "$tmp_source"
as_root install -D -m 0644 "$tmp_source" "$SOURCE_PATH"

echo "Installing latest gh..."
as_root apt-get update
as_root apt-get install -y gh

echo ""
gh --version
