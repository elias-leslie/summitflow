#!/usr/bin/env bash
# commit.sh - Unified commit and sync for all managed repos
# Version: 1.0.0
# Usage: commit.sh [OPTIONS]
#
# Commits current repo by default. Use --all for multi-repo orchestration.
# Discovers repos from SummitFlow API + config repos, with static fallback.
#
# Flags:
#   --current       Only commit current repo (DEFAULT)
#   --all           Commit all managed repos
#   --push          Push after commit (default: false)
#   --no-push       Don't push (explicit)
#   --force         Use --force-with-lease when pushing
#   --skip-checks   Skip dt quality gates
#   --msg "..."     Custom commit message
#   --json          Output JSON instead of TOON
#   --sync-only     Pull all repos without committing
#   --task ID       Tag commit with task ID
#   --help          Show help

set -uo pipefail

SUMMITFLOW_API="http://localhost:8001/api/projects"
CONFIG_REPOS=("$HOME/.claude")
FALLBACK_FILE="$HOME/.claude/config/managed-repos.txt"
MAIN_BRANCHES=("main" "master")

PUSH=false
FORCE=false
SKIP_CHECKS=false
SYNC_ONLY=false
CURRENT_ONLY=true
CUSTOM_MSG=""
JSON_OUTPUT=false
TASK_ID=""
LAST_STATUS=""
JSON_RESULTS=()

show_help() {
    sed -n '2,/^$/p' "$0" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h) show_help ;;
        --sync-only) SYNC_ONLY=true; shift ;;
        --current) CURRENT_ONLY=true; shift ;;
        --all) CURRENT_ONLY=false; shift ;;
        --push) PUSH=true; shift ;;
        --no-push) PUSH=false; shift ;;
        --force) FORCE=true; shift ;;
        --skip-checks|--skip-tests) SKIP_CHECKS=true; shift ;;
        --msg) CUSTOM_MSG="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --task) TASK_ID="$2"; shift 2 ;;
        *) echo "ERROR:unknown_option:$1"; exit 1 ;;
    esac
done

is_main_branch() {
    local branch=$1
    for main in "${MAIN_BRANCHES[@]}"; do
        [[ "$branch" == "$main" ]] && return 0
    done
    return 1
}

is_dirty() {
    [[ -n "$(git status --porcelain 2>/dev/null)" ]]
}

is_project_repo() {
    local repo=$1
    [[ -d "$repo/backend" ]] || [[ -f "$repo/pyproject.toml" ]] || [[ -d "$repo/frontend" ]]
}

safe_pull() {
    local repo_name=$1
    local branch=$2
    local upstream="origin/$branch"

    if ! git fetch origin "$branch" >/dev/null 2>&1; then
        return 1
    fi

    local behind
    behind=$(git rev-list --count "HEAD..$upstream" 2>/dev/null || echo "0")
    [[ "$behind" -eq 0 ]] && return 0

    local original_head
    original_head=$(git rev-parse HEAD)

    if ! git rebase "$upstream" >/dev/null 2>&1; then
        git rebase --abort >/dev/null 2>&1 || true
        local current_head
        current_head=$(git rev-parse HEAD)
        if [[ "$original_head" != "$current_head" ]]; then
            git reset --hard "$original_head" >/dev/null 2>&1 || true
        fi
        return 1
    fi

    return 0
}

detect_layers() {
    local files
    files=$(git diff --cached --name-only 2>/dev/null; git diff --name-only 2>/dev/null)

    local backend=false frontend=false
    while IFS= read -r f; do
        [[ "$f" =~ ^backend/ ]] && backend=true
        [[ "$f" =~ ^frontend/ ]] && frontend=true
    done <<< "$files"

    if $backend && $frontend; then
        echo "both"
    elif $backend; then
        echo "backend"
    elif $frontend; then
        echo "frontend"
    else
        echo "other"
    fi
}

detect_type() {
    local staged
    staged=$(git diff --cached --name-only 2>/dev/null || true)

    if echo "$staged" | grep -qE "^.*/test.*\.py$|^.*_test\.py$|^.*\.test\.(ts|tsx|js)$"; then
        echo "test"
    elif echo "$staged" | grep -qE "requirements.*\.txt$|package.*\.json$|pyproject\.toml$"; then
        echo "deps"
    elif echo "$staged" | grep -qE "\.md$|docs/"; then
        echo "docs"
    elif git diff --cached --summary | grep -q "create mode"; then
        echo "feat"
    else
        echo "chore"
    fi
}

generate_simple_message() {
    local changed
    changed=$(git diff --cached --name-only 2>/dev/null || git diff --name-only)
    local file_count
    file_count=$(echo "$changed" | grep -c . || echo "0")

    local type="chore"
    local scope=""
    local repo_name
    repo_name=$(basename "$(pwd)")

    if [[ "$repo_name" == ".claude" ]]; then
        if echo "$changed" | grep -q "^skills/"; then
            scope="skills"
        elif echo "$changed" | grep -q "^commands/"; then
            scope="commands"
        elif echo "$changed" | grep -q "^rules/"; then
            scope="rules"
        elif echo "$changed" | grep -q "^hooks/"; then
            scope="hooks"
        elif echo "$changed" | grep -q "^scripts/"; then
            scope="scripts"
        else
            scope="config"
        fi
    fi

    local summary
    if [[ $file_count -eq 1 ]]; then
        summary=$(basename "$(echo "$changed" | head -1)")
    elif [[ $file_count -le 3 ]]; then
        summary=$(echo "$changed" | xargs -I{} basename {} | head -3 | tr '\n' ',' | sed 's/,$//')
    else
        summary="${file_count} files"
    fi

    if [[ -n "$scope" ]]; then
        echo "${type}(${scope}): ${summary}"
    else
        echo "${type}: ${summary}"
    fi
}

generate_ai_message() {
    local layer=$1
    local type=$2

    if command -v st &>/dev/null; then
        local diff
        diff=$(git diff --cached 2>/dev/null)
        if [[ -n "$diff" ]]; then
            local json_out
            json_out=$(st complete --agent git-agent --raw "Generate a conventional commit message for the following diff. Output ONLY the message:\n\n$diff" 2>/dev/null)

            if [[ -n "$json_out" && ! "$json_out" =~ "Error" ]]; then
                local ai_msg=""
                if command -v jq &>/dev/null; then
                    ai_msg=$(echo "$json_out" | jq -r '.content // empty')
                else
                    ai_msg=$(echo "$json_out" | python3 -c "import sys, json; print(json.load(sys.stdin).get('content', ''))")
                fi
                if [[ -n "$ai_msg" ]]; then
                    echo "$ai_msg"
                    return
                fi
            fi
        fi
    fi

    local summary scope=""
    summary=$(git diff --cached --stat | tail -1 | sed 's/^ *//')
    case $layer in
        backend) scope="(backend)" ;;
        frontend) scope="(frontend)" ;;
        both) scope="(fullstack)" ;;
    esac

    if [[ -n "$TASK_ID" ]]; then
        echo "${type}${scope}: ${TASK_ID} - ${summary}"
    else
        echo "${type}${scope}: ${summary}"
    fi
}

cross_layer_check() {
    local warnings=""
    local backend_api
    backend_api=$(git diff --cached --name-only | grep "^backend/app/api/" | grep -v "__init__" | grep -v "deps.py" || true)

    for f in $backend_api; do
        local route
        route=$(basename "$f" .py)
        if ! grep -rq "$route" frontend/ 2>/dev/null; then
            warnings="$warnings|$route:no_frontend_ref"
        fi
    done

    echo "${warnings#|}"
}

run_quality_gates() {
    local dt_cmd
    if command -v dt &>/dev/null; then
        dt_cmd="dt"
    elif [[ -x "$HOME/summitflow/scripts/dev-tools.sh" ]]; then
        dt_cmd="$HOME/summitflow/scripts/dev-tools.sh"
    else
        return 1
    fi

    local output retval=0
    output=$("$dt_cmd" --quick --changed-only 2>&1) || retval=$?

    if echo "$output" | grep -q "CHECK_RESULT:OK"; then
        return 0
    else
        echo "$output"
        return 1
    fi
}

get_managed_repos() {
    local repos=()

    local api_response
    if api_response=$(curl -sf --connect-timeout 2 "$SUMMITFLOW_API" 2>/dev/null); then
        if command -v jq &>/dev/null; then
            while IFS= read -r path; do
                [[ -d "$path/.git" ]] && repos+=("$path")
            done < <(echo "$api_response" | jq -r '.[].root_path // empty')
        else
            while IFS= read -r path; do
                [[ -d "$path/.git" ]] && repos+=("$path")
            done < <(echo "$api_response" | grep -o '"root_path":"[^"]*"' | sed 's/"root_path":"//;s/"$//')
        fi
    else
        if [[ -f "$FALLBACK_FILE" ]]; then
            while IFS= read -r line || [[ -n "$line" ]]; do
                [[ "$line" =~ ^[[:space:]]*# ]] && continue
                [[ -z "${line// }" ]] && continue
                local expanded="${line/#\~/$HOME}"
                [[ -d "$expanded/.git" ]] && repos+=("$expanded")
            done < "$FALLBACK_FILE"
        fi
    fi

    for config_repo in "${CONFIG_REPOS[@]}"; do
        [[ -d "$config_repo/.git" ]] && repos+=("$config_repo")
    done

    local current_repo
    current_repo=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
    if [[ -n "$current_repo" ]]; then
        local found=false
        for r in "${repos[@]}"; do
            [[ "$r" == "$current_repo" ]] && found=true && break
        done
        $found || repos+=("$current_repo")
    fi

    printf '%s\n' "${repos[@]}" | awk '!seen[$0]++'
}

# Escape a string for safe JSON embedding
json_escape() {
    local s=$1
    s=${s//\\/\\\\}
    s=${s//\"/\\\"}
    s=${s//$'\n'/\\n}
    s=${s//$'\r'/\\r}
    s=${s//$'\t'/\\t}
    printf '%s' "$s"
}

# Emit result in TOON or JSON. Sets LAST_STATUS for counting.
# Args: status name sha message pushed gates reason
emit_result() {
    local status=$1 name=$2 sha=$3 message=$4 pushed=$5 gates=$6 reason=$7
    LAST_STATUS="$status"

    if $JSON_OUTPUT; then
        local json_entry
        json_entry=$(printf '{"name":"%s","status":"%s","sha":"%s","message":"%s","pushed":%s,"gates":"%s","reason":"%s"}' \
            "$(json_escape "$name")" "$status" "$sha" "$(json_escape "$message")" "$pushed" "$(json_escape "$gates")" "$(json_escape "$reason")")
        JSON_RESULTS+=("$json_entry")
    else
        case "$status" in
            SUCCESS)
                echo "  SUCCESS:${name}:${sha}:${message}:pushed=${pushed}"
                ;;
            SKIP)
                echo "  SKIP:${name}:${reason}"
                ;;
            BLOCKED)
                echo "  BLOCKED:${name}:quality_gates_failed"
                ;;
            PARTIAL)
                echo "  WARN:${name}:${sha}:committed_not_pushed:${reason}"
                ;;
            ERROR)
                local detail="${reason:-$gates}"
                echo "  ERROR:${name}:${detail}"
                ;;
        esac
    fi
}

emit_json_summary() {
    local ok=$1 skip=$2 err=$3 blocked=$4
    local overall="SUCCESS"
    [[ $blocked -gt 0 ]] && overall="BLOCKED"
    [[ $err -gt 0 ]] && overall="FAILED"
    [[ $ok -eq 0 && $err -eq 0 && $blocked -eq 0 ]] && overall="SKIP"

    echo "{"
    echo "  \"status\": \"$overall\","
    echo "  \"repos\": ["
    local first=true
    for entry in "${JSON_RESULTS[@]}"; do
        if $first; then
            first=false
        else
            echo ","
        fi
        printf "    %s" "$entry"
    done
    echo ""
    echo "  ],"
    printf '  "summary": {"ok": %d, "skip": %d, "err": %d, "blocked": %d}\n' "$ok" "$skip" "$err" "$blocked"
    echo "}"
}

commit_project_repo() {
    local repo=$1
    local repo_name
    repo_name=$(basename "$repo")

    cd "$repo" || return 1

    local branch file_count
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    file_count=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

    if [[ "$file_count" -eq 0 ]]; then
        handle_push_only "$repo_name" "$branch"
        return $?
    fi

    if ! git symbolic-ref -q HEAD &>/dev/null; then
        emit_result "SKIP" "$repo_name" "" "" "false" "" "detached_head"
        return 0
    fi

    local layer type
    layer=$(detect_layers)
    type=$(detect_type)

    git add -A >/dev/null 2>&1

    local gates=""
    if ! $SKIP_CHECKS; then
        local gates_out gates_status=0
        gates_out=$(run_quality_gates 2>&1) || gates_status=$?

        if [[ $gates_status -ne 0 ]]; then
            emit_result "BLOCKED" "$repo_name" "" "" "false" "checks:FAIL" ""
            if ! $JSON_OUTPUT; then
                echo "$gates_out" | head -10 | sed 's/^/  /'
            fi
            return 1
        fi
        gates="checks:PASS"
    else
        gates="checks:SKIP"
    fi

    local message
    if [[ -n "$CUSTOM_MSG" ]]; then
        message="$CUSTOM_MSG"
    else
        message=$(generate_ai_message "$layer" "$type")
    fi

    local commit_out commit_status=0
    commit_out=$(git commit -m "$message" 2>&1) || commit_status=$?

    if [[ $commit_status -ne 0 ]]; then
        if [[ -n "$(git status --porcelain)" ]]; then
            git add -A >/dev/null 2>&1
            commit_out=$(git commit -m "$message" 2>&1) || commit_status=$?
        fi
        if [[ $commit_status -ne 0 ]]; then
            emit_result "ERROR" "$repo_name" "" "$message" "false" "$gates|hooks:FAIL" ""
            return 1
        fi
    fi

    gates="$gates|hooks:PASS"
    local sha
    sha=$(git rev-parse --short HEAD)

    if [[ -n "$(git status --porcelain)" ]]; then
        git add -A >/dev/null 2>&1
        local followup_status=0
        git commit -m "style: auto-format from pre-commit hooks" >/dev/null 2>&1 || followup_status=$?
        if [[ $followup_status -eq 0 ]]; then
            sha=$(git rev-parse --short HEAD)
            gates="$gates|followup:PASS"
        fi
    fi

    local cross_warn
    cross_warn=$(cross_layer_check)
    [[ -n "$cross_warn" ]] && gates="$gates|cross:WARN($cross_warn)"

    local pushed="false"
    if $PUSH; then
        if is_main_branch "$branch" && ! $FORCE; then
            if ! safe_pull "$repo_name" "$branch"; then
                emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "$gates" "pull_conflict"
                return 1
            fi
            sha=$(git rev-parse --short HEAD)
        fi

        local push_args=""
        $FORCE && push_args="--force-with-lease"

        # shellcheck disable=SC2086
        if git push $push_args >/dev/null 2>&1; then
            pushed="true"
        else
            emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "$gates" "push_failed"
            return 1
        fi
    fi

    emit_result "SUCCESS" "$repo_name" "$sha" "$message" "$pushed" "$gates" ""
    return 0
}

commit_config_repo() {
    local repo=$1
    local repo_name
    repo_name=$(basename "$repo")

    cd "$repo" || return 1

    local branch file_count
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    file_count=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

    if [[ "$file_count" -eq 0 ]]; then
        handle_push_only "$repo_name" "$branch"
        return $?
    fi

    if ! git symbolic-ref -q HEAD &>/dev/null; then
        emit_result "SKIP" "$repo_name" "" "" "false" "" "detached_head"
        return 0
    fi

    git add -A >/dev/null 2>&1

    local message
    message="${CUSTOM_MSG:-$(generate_simple_message)}"

    local commit_out commit_status=0
    commit_out=$(git commit -m "$message" 2>&1) || commit_status=$?

    if [[ $commit_status -ne 0 ]]; then
        if [[ -n "$(git status --porcelain)" ]]; then
            git add -A >/dev/null 2>&1
            commit_out=$(git commit -m "$message" 2>&1) || commit_status=$?
        fi
        if [[ $commit_status -ne 0 ]]; then
            emit_result "ERROR" "$repo_name" "" "$message" "false" "" ""
            return 1
        fi
    fi

    local sha pushed="false"
    sha=$(git rev-parse --short HEAD)

    if $PUSH; then
        if is_main_branch "$branch" && ! $FORCE; then
            if ! safe_pull "$repo_name" "$branch"; then
                emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "" "pull_conflict"
                return 1
            fi
            sha=$(git rev-parse --short HEAD)
        fi

        local push_args=""
        $FORCE && push_args="--force-with-lease"

        # shellcheck disable=SC2086
        if git push $push_args >/dev/null 2>&1; then
            pushed="true"
        else
            emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "" "push_failed"
            return 1
        fi
    fi

    emit_result "SUCCESS" "$repo_name" "$sha" "$message" "$pushed" "" ""
    return 0
}

handle_push_only() {
    local repo_name=$1
    local branch=$2

    if $PUSH; then
        local upstream ahead
        upstream="origin/$branch"
        if git rev-parse "$upstream" &>/dev/null; then
            ahead=$(git rev-list --count "$upstream..HEAD" 2>/dev/null || echo "0")
            if [[ "$ahead" -gt 0 ]]; then
                if is_main_branch "$branch" && ! $FORCE; then
                    if ! safe_pull "$repo_name" "$branch"; then
                        emit_result "ERROR" "$repo_name" "" "" "false" "" "pull_conflict"
                        return 1
                    fi
                fi

                local push_args=""
                $FORCE && push_args="--force-with-lease"

                # shellcheck disable=SC2086
                if git push $push_args >/dev/null 2>&1; then
                    emit_result "SUCCESS" "$repo_name" "$(git rev-parse --short HEAD)" "pushed_${ahead}_commits" "true" "" ""
                    return 0
                fi
                emit_result "ERROR" "$repo_name" "" "" "false" "" "push_failed"
                return 1
            fi
        fi
    fi

    emit_result "SKIP" "$repo_name" "" "" "false" "" "clean"
    return 0
}

sync_repo() {
    local repo=$1
    local repo_name
    repo_name=$(basename "$repo")

    cd "$repo" || { emit_result "ERROR" "$repo_name" "" "" "false" "" "cd_failed"; return 1; }

    if is_dirty; then
        emit_result "SKIP" "$repo_name" "" "" "false" "" "dirty"
        return 0
    fi

    local branch
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    [[ -z "$branch" ]] && { emit_result "SKIP" "$repo_name" "" "" "false" "" "no_branch"; return 0; }

    if ! is_main_branch "$branch"; then
        emit_result "SKIP" "$repo_name" "" "" "false" "" "feature_branch:${branch}"
        return 0
    fi

    if safe_pull "$repo_name" "$branch"; then
        emit_result "SUCCESS" "$repo_name" "$(git rev-parse --short HEAD)" "synced" "false" "" ""
        return 0
    else
        emit_result "ERROR" "$repo_name" "" "" "false" "" "conflict"
        return 1
    fi
}

count_result() {
    case "$LAST_STATUS" in
        SUCCESS) ((++success_count)) || true ;;
        SKIP) ((++skip_count)) || true ;;
        BLOCKED) ((++blocked_count)) || true ;;
        *) ((++error_count)) || true ;;
    esac
}

main() {
    local repos

    if $CURRENT_ONLY; then
        local current_repo
        current_repo=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
        if [[ -z "$current_repo" ]]; then
            if $JSON_OUTPUT; then
                echo '{"status":"ERROR","repos":[],"summary":{"ok":0,"skip":0,"err":1,"blocked":0}}'
            else
                echo "ERROR:not_in_git_repo"
            fi
            exit 1
        fi
        repos=("$current_repo")
    else
        mapfile -t repos < <(get_managed_repos)
    fi

    if [[ ${#repos[@]} -eq 0 ]]; then
        if $JSON_OUTPUT; then
            echo '{"status":"ERROR","repos":[],"summary":{"ok":0,"skip":0,"err":1,"blocked":0}}'
        else
            echo "ERROR:no_repos_found"
        fi
        exit 1
    fi

    local success_count=0 error_count=0 skip_count=0 blocked_count=0

    if $SYNC_ONLY; then
        for repo in "${repos[@]}"; do
            sync_repo "$repo" || true
            count_result
        done
    else
        for repo in "${repos[@]}"; do
            if is_project_repo "$repo"; then
                commit_project_repo "$repo" || true
            else
                commit_config_repo "$repo" || true
            fi
            count_result
        done
    fi

    if $JSON_OUTPUT; then
        emit_json_summary "$success_count" "$skip_count" "$error_count" "$blocked_count"
    else
        local total=$((success_count + error_count + skip_count + blocked_count))
        local status="SUCCESS"
        [[ $blocked_count -gt 0 ]] && status="BLOCKED"
        [[ $error_count -gt 0 ]] && status="FAILED"
        [[ $success_count -eq 0 && $error_count -eq 0 && $blocked_count -eq 0 ]] && status="SKIP"

        echo ""
        local label="COMMIT"
        $SYNC_ONLY && label="SYNC"
        echo "${label}[${total}]:ok=${success_count}|skip=${skip_count}|err=${error_count}|blocked=${blocked_count}:${status}"
    fi

    [[ $error_count -gt 0 || $blocked_count -gt 0 ]] && exit 1
    exit 0
}

main "$@"
