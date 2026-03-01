#!/usr/bin/env bash
# CodeRabbit daily review helpers for Jenny's scheduled job.
#
# SHA marker file: <project>/.dev-tools/coderabbit-last-reviewed.sha
# Contains one line: the SHA of the last reviewed HEAD.
#
# Usage:
#   source scripts/lib/coderabbit-helpers.sh
#   cr-last-sha /path/to/project        # → prints SHA or "none"
#   cr-update-sha /path/to/project       # → writes current HEAD to marker
#   cr-review-since-last /path/to/project # → runs coderabbit review since last SHA

set -euo pipefail

_CR_MARKER=".dev-tools/coderabbit-last-reviewed.sha"

cr-last-sha() {
    local project_path="${1:?Usage: cr-last-sha <project-path>}"
    local marker="$project_path/$_CR_MARKER"
    if [[ -f "$marker" ]]; then
        cat "$marker"
    else
        echo "none"
    fi
}

cr-update-sha() {
    local project_path="${1:?Usage: cr-update-sha <project-path>}"
    local marker="$project_path/$_CR_MARKER"
    mkdir -p "$(dirname "$marker")"
    git -C "$project_path" rev-parse HEAD > "$marker"
}

cr-review-since-last() {
    local project_path="${1:?Usage: cr-review-since-last <project-path>}"
    local last_sha
    last_sha=$(cr-last-sha "$project_path")

    if [[ "$last_sha" == "none" ]]; then
        # First run — review last 5 commits
        last_sha=$(git -C "$project_path" rev-parse HEAD~5 2>/dev/null || git -C "$project_path" rev-list --max-parents=0 HEAD)
    fi

    echo "Reviewing $project_path since $last_sha..."
    coderabbit review --plain --type committed --base-commit "$last_sha" 2>&1 || true

    # Update marker to current HEAD after review
    cr-update-sha "$project_path"
}
