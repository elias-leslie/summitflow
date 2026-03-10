#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage:
  git-governance-guard.sh check-main-edit --file <path> [--cwd <path>] [--agent <name>]
  git-governance-guard.sh session-context [--cwd <path>]
EOF
    exit 1
}

count_uncommitted() {
    git -C "$1" status --porcelain 2>/dev/null | wc -l | tr -d ' '
}

count_ahead() {
    local repo_root="$1"
    if ! git -C "$repo_root" rev-parse --verify '@{upstream}' >/dev/null 2>&1; then
        echo 0
        return
    fi
    git -C "$repo_root" rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo 0
}

is_config_target() {
    local target_path="$1"
    [[ "$target_path" == "$HOME/.claude"* ]] || [[ "$target_path" == *"/CLAUDE.md" ]] || [[ "$target_path" == *"/.claude/"* ]]
}

collect_active_worktrees() {
    local project_name="$1"
    local worktrees_dir="$HOME/.local/share/st/worktrees/$project_name"

    if [[ ! -d "$worktrees_dir" ]]; then
        return
    fi

    local task_dir=""
    for task_dir in "$worktrees_dir"/*/; do
        [[ -d "$task_dir" ]] || continue
        if [[ -d "$task_dir/.git" || -f "$task_dir/.git" ]]; then
            printf '%s\n' "${task_dir%/}"
        fi
    done
}

print_main_branch_block() {
    local action_label="$1"
    local target_label="$2"
    local current_branch="$3"
    local current_project="$4"
    shift 4
    local active_worktrees=("$@")

    {
        echo ""
        echo "=============================================================="
        echo "BLOCKED: ${action_label} on '$current_branch' branch ($current_project)"
        echo "=============================================================="
        echo ""
        echo "Target: $target_label"
        echo ""
        echo "Active worktrees for '$current_project':"
        local worktree=""
        for worktree in "${active_worktrees[@]}"; do
            echo "  - $worktree"
        done
        echo ""
        echo "Do not keep working on main while task worktrees exist."
        echo ""
        echo "Instead, do ONE of these:"
        echo "  1. Clean up stale worktrees: git worktree remove <path>"
        echo "  2. If a worktree is active, cd to it and work there"
        echo "  3. Bypass only when you have verified the main-branch edit is intentional: ALLOW_MAIN_EDITS=1"
        echo ""
        echo "=============================================================="
        echo ""
    } >&2
}

print_session_context() {
    local cwd="$1"

    if ! git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1; then
        exit 0
    fi

    local git_root
    git_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || echo "")
    [[ -n "$git_root" ]] || exit 0

    local project_name
    project_name=$(basename "$git_root")
    local current_branch
    current_branch=$(git -C "$git_root" branch --show-current 2>/dev/null || echo "")
    local in_worktree="false"
    if [[ -f "$git_root/.git" ]]; then
        in_worktree="true"
    fi

    local uncommitted
    uncommitted=$(count_uncommitted "$git_root")
    local ahead
    ahead=$(count_ahead "$git_root")

    mapfile -t active_worktrees < <(collect_active_worktrees "$project_name")
    local protected_main="false"
    if [[ "$project_name" != ".claude" && ( "$current_branch" == "main" || "$current_branch" == "master" ) && ${#active_worktrees[@]} -gt 0 ]]; then
        protected_main="true"
    fi

    printf '%s\n' "## Runtime Git Context"
    printf '%s\n' "- Git root: $git_root"
    printf '%s\n' "- Launch cwd: $cwd"
    printf '%s\n' "- Branch: ${current_branch:-unknown}"
    printf '%s\n' "- Worktree checkout: $in_worktree"
    printf '%s\n' "- Uncommitted changes: $uncommitted"
    printf '%s\n' "- Local-only commits ahead of upstream: $ahead"
    printf '%s\n' "- Main branch with active worktrees: $protected_main"

    if [[ ${#active_worktrees[@]} -gt 0 ]]; then
        printf '%s\n' "- Active worktrees:"
        local worktree=""
        for worktree in "${active_worktrees[@]}"; do
            printf '%s\n' "  - $worktree"
        done
    else
        printf '%s\n' "- Active worktrees: none"
    fi
}

handle_check_main_edit() {
    local file_path="$1"
    local cwd="$2"

    if [[ "${ALLOW_MAIN_EDITS:-0}" == "1" ]]; then
        exit 0
    fi

    if [[ -z "$file_path" ]] || is_config_target "$file_path"; then
        exit 0
    fi

    local target_dir
    target_dir=$(dirname "$file_path")
    if [[ ! -d "$target_dir" ]]; then
        target_dir="$cwd"
    fi

    if ! git -C "$target_dir" rev-parse --git-dir >/dev/null 2>&1; then
        exit 0
    fi

    local current_branch
    current_branch=$(git -C "$target_dir" branch --show-current 2>/dev/null || echo "")
    if [[ "$current_branch" != "main" && "$current_branch" != "master" ]]; then
        exit 0
    fi

    local git_root
    git_root=$(git -C "$target_dir" rev-parse --show-toplevel 2>/dev/null || echo "")
    if [[ -z "$git_root" ]]; then
        exit 0
    fi

    local project_name
    project_name=$(basename "$git_root")
    mapfile -t active_worktrees < <(collect_active_worktrees "$project_name")
    if [[ ${#active_worktrees[@]} -eq 0 ]]; then
        exit 0
    fi

    print_main_branch_block "Editing files" "$file_path" "$current_branch" "$project_name" "${active_worktrees[@]}"
    exit 2
}

main() {
    local subcommand="${1:-}"
    [[ -n "$subcommand" ]] || usage
    shift

    local cwd="${PWD}"
    local file_path=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --cwd)
                cwd="$2"
                shift 2
                ;;
            --file)
                file_path="$2"
                shift 2
                ;;
            *)
                usage
                ;;
        esac
    done

    case "$subcommand" in
        check-main-edit)
            handle_check_main_edit "$file_path" "$cwd"
            ;;
        session-context)
            print_session_context "$cwd"
            ;;
        *)
            usage
            ;;
    esac
}

main "$@"
