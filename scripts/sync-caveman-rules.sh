#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULES_FILE="${CAVEMAN_RULES_FILE:-$REPO_ROOT/config/caveman/session-rules.md}"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
CLAUDE_HOME_DIR="${CLAUDE_HOME:-$HOME/.claude}"
CODEX_AGENTS_MD="$CODEX_HOME_DIR/AGENTS.md"
CLAUDE_MD="$CLAUDE_HOME_DIR/CLAUDE.md"

if [[ ! -f "$RULES_FILE" ]]; then
  echo "Missing rules file: $RULES_FILE" >&2
  exit 1
fi

RULES_CONTENT="$(cat "$RULES_FILE")"

mkdir -p "$CODEX_HOME_DIR" "$CLAUDE_HOME_DIR"

cat >"$CODEX_AGENTS_MD" <<EOF
# Codex Config Notes

$RULES_CONTENT
- Treat \`AGENTS.override.md\` as generated startup context. Never edit or commit it.
- Keep durable Codex automation in \`memories/\` and \`session-integrations/\`.
- Keep secrets, auth state, logs, and transcripts out of git.
EOF

cat >"$CLAUDE_MD" <<EOF
# Claude Config Notes

$RULES_CONTENT
- Project context comes from Agent Hub memory via \`~/.claude/hooks/SessionStart.sh\`.
EOF

st prompt update caveman-output-directive \
  --file "$RULES_FILE" \
  --change-reason "sync shared Caveman rules"
