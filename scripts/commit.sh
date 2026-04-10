#!/usr/bin/env bash
# commit.sh - Unified commit and sync for all managed repos
# Version: 1.5.0
# Usage: commit.sh [OPTIONS]
#
# Commits current repo by default. Use --all for multi-repo orchestration.
# Discovers repos from SummitFlow API + config repos, with static fallback.
#
# Flags:
#   --current       Only commit current repo (DEFAULT)
#   --all           Commit all managed repos
#   --push          Push after commit (default: true)
#   --no-push       Don't push (explicit)
#   --force         Use --force-with-lease when pushing
#   --skip-checks   Skip dt quality gates
#   --msg "..."     Custom commit message
#   --path <path>   Limit commit to one path (repeatable)
#   --json          Output JSON instead of TOON
#   --sync-only     Pull all repos without committing
#   --task ID       Tag commit with task ID
#   --help          Show help

set -uo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

SUMMITFLOW_API="${ST_API_BASE:-http://localhost:8001/api}/projects"
BACKUP_SOURCES_API="${ST_API_BASE:-http://localhost:8001/api}/backup-sources"
FALLBACK_FILE="$HOME/.claude/config/managed-repos.txt"
MAIN_BRANCHES=("main" "master")
QUALITY_GATE_STATE="${QUALITY_GATE_STATE:-$HOME/.claude/hooks/.quality-gate-state.json}"
SUMMITFLOW_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GUARD_BIN="$SCRIPT_DIR/lib/command-guard"

PUSH=true
FORCE=false
SKIP_CHECKS=false
SYNC_ONLY=false
CURRENT_ONLY=true
CUSTOM_MSG=""
JSON_OUTPUT=false
TASK_ID=""
COMMIT_PATHS=()
LAST_STATUS=""
JSON_RESULTS=()
LAST_PUSH_DETAIL=""
LAST_PULL_DETAIL=""
LAST_WORKFLOW_SUMMARY=""
LAST_WORKFLOW_JSON="[]"
LAST_WORKFLOW_HINT=""
WORKFLOW_SUMMARY_LIMIT="${WORKFLOW_SUMMARY_LIMIT:-3}"
WORKFLOW_DISCOVERY_ATTEMPTS="${WORKFLOW_DISCOVERY_ATTEMPTS:-5}"
WORKFLOW_DISCOVERY_SLEEP="${WORKFLOW_DISCOVERY_SLEEP:-1}"

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
        --path) COMMIT_PATHS+=("$2"); shift 2 ;;
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

has_commit_scope() {
    [[ ${#COMMIT_PATHS[@]} -gt 0 ]]
}

scope_status() {
    if has_commit_scope; then
        git status --porcelain -- "${COMMIT_PATHS[@]}" 2>/dev/null
    else
        git status --porcelain 2>/dev/null
    fi
}

scope_has_changes() {
    [[ -n "$(scope_status)" ]]
}

scope_add_all() {
    if has_commit_scope; then
        git add -A -- "${COMMIT_PATHS[@]}" >/dev/null 2>&1
    else
        git add -A >/dev/null 2>&1
    fi
}

scope_reset_index() {
    if has_commit_scope; then
        git reset -q HEAD -- . >/dev/null 2>&1 || true
    fi
}

is_project_repo() {
    local repo=$1
    [[ -d "$repo/backend" ]] || [[ -f "$repo/pyproject.toml" ]] || [[ -d "$repo/frontend" ]]
}

push_current_branch() {
    local branch=$1
    [[ -z "$branch" ]] && return 1

    LAST_PUSH_DETAIL=""
    local push_args=()
    $FORCE && push_args+=(--force-with-lease)

    local push_out="" push_status=0
    if git rev-parse --abbrev-ref --symbolic-full-name "@{upstream}" >/dev/null 2>&1; then
        push_out=$(git push "${push_args[@]}" 2>&1) || push_status=$?
    else
        push_out=$(git push "${push_args[@]}" --set-upstream origin "$branch" 2>&1) || push_status=$?
    fi

    if [[ $push_status -eq 0 ]]; then
        return 0
    fi

    LAST_PUSH_DETAIL=$(printf '%s\n' "$push_out" | tail -n 20 | awk '
        NF {
            gsub(/[[:space:]]+/, " ")
            sub(/^ /, "")
            sub(/ $/, "")
            printf "%s%s", sep, $0
            sep = " | "
        }
    ')
    return 1
}

resolve_repo_name() {
    local repo=$1
    if [[ "$repo" == *"/worktrees/"* ]]; then
        local derived
        derived=$(echo "$repo" | sed -E 's|.*/worktrees/([^/]+)/.*|\1|')
        if [[ -n "$derived" && "$derived" != "$repo" ]]; then
            echo "$derived"
            return
        fi
    fi
    basename "$repo"
}

safe_pull() {
    local repo_name=$1
    local branch=$2
    local upstream="origin/$branch"

    LAST_PULL_DETAIL=""

    local fetch_out="" fetch_status=0
    fetch_out=$(git fetch origin "$branch" 2>&1) || fetch_status=$?
    if [[ $fetch_status -ne 0 ]]; then
        LAST_PULL_DETAIL=$(printf '%s\n' "$fetch_out" | tail -n 20 | awk '
            NF {
                gsub(/[[:space:]]+/, " ")
                sub(/^ /, "")
                sub(/ $/, "")
                printf "%s%s", sep, $0
                sep = " | "
            }
        ')
        return 1
    fi

    local behind
    behind=$(git rev-list --count "HEAD..$upstream" 2>/dev/null || echo "0")
    [[ "$behind" -eq 0 ]] && return 0

    local original_head
    original_head=$(git rev-parse HEAD)

    local rebase_out="" rebase_status=0
    rebase_out=$(git rebase "$upstream" 2>&1) || rebase_status=$?
    if [[ $rebase_status -ne 0 ]]; then
        git rebase --abort >/dev/null 2>&1 || true
        local current_head
        current_head=$(git rev-parse HEAD)
        if [[ "$original_head" != "$current_head" ]]; then
            git reset --hard "$original_head" >/dev/null 2>&1 || true
        fi
        LAST_PULL_DETAIL=$(printf '%s\n' "$rebase_out" | tail -n 20 | awk '
            NF {
                gsub(/[[:space:]]+/, " ")
                sub(/^ /, "")
                sub(/ $/, "")
                printf "%s%s", sep, $0
                sep = " | "
            }
        ')
        return 1
    fi

    return 0
}

clear_workflow_summary() {
    LAST_WORKFLOW_SUMMARY=""
    LAST_WORKFLOW_JSON="[]"
    LAST_WORKFLOW_HINT=""
}

github_repo_slug() {
    local remote_url
    remote_url=$(git remote get-url origin 2>/dev/null || true)
    [[ -z "$remote_url" ]] && return 1

    case "$remote_url" in
        git@github.com:*)
            remote_url="${remote_url#git@github.com:}"
            ;;
        ssh://git@github.com/*)
            remote_url="${remote_url#ssh://git@github.com/}"
            ;;
        https://github.com/*)
            remote_url="${remote_url#https://github.com/}"
            ;;
        http://github.com/*)
            remote_url="${remote_url#http://github.com/}"
            ;;
        *)
            return 1
            ;;
    esac

    remote_url="${remote_url%.git}"
    [[ -n "$remote_url" ]] || return 1
    printf '%s\n' "$remote_url"
}

workflow_json_has_sha() {
    local workflow_json=$1
    local target_sha=$2

    python3 - "$workflow_json" "$target_sha" <<'PY'
import json
import sys

try:
    runs = json.loads(sys.argv[1] or "[]")
except json.JSONDecodeError:
    print("no")
    raise SystemExit(0)

target_sha = (sys.argv[2] or "").strip()
if not target_sha:
    print("yes")
    raise SystemExit(0)

for run in runs:
    head_sha = (run.get("headSha") or "").strip()
    if head_sha == target_sha:
        print("yes")
        raise SystemExit(0)

print("no")
PY
}

capture_workflow_summary() {
    clear_workflow_summary

    command -v gh >/dev/null 2>&1 || return 0

    local repo_slug
    repo_slug=$(github_repo_slug) || return 0

    local target_sha=${1:-}
    local workflow_json=""
    local attempt
    for ((attempt = 1; attempt <= WORKFLOW_DISCOVERY_ATTEMPTS; attempt++)); do
        workflow_json=$(gh run list \
            --repo "$repo_slug" \
            --limit "$WORKFLOW_SUMMARY_LIMIT" \
            --json status,conclusion,workflowName,headBranch,headSha,number,url,displayTitle,event \
            2>/dev/null || true)
        [[ -z "$workflow_json" ]] && workflow_json="[]"

        if [[ "$(workflow_json_has_sha "$workflow_json" "$target_sha")" == "yes" ]]; then
            break
        fi

        if (( attempt < WORKFLOW_DISCOVERY_ATTEMPTS )); then
            sleep "$WORKFLOW_DISCOVERY_SLEEP"
        fi
    done

    local parsed
    parsed=$(python3 - "$workflow_json" "$WORKFLOW_SUMMARY_LIMIT" <<'PY'
import json
import sys

try:
    runs = json.loads(sys.argv[1] or "[]")
except json.JSONDecodeError:
    runs = []

limit = int(sys.argv[2] or 3)
compact = []
summary_parts = []
watch_number = ""

for run in runs[:limit]:
    workflow = run.get("workflowName") or "workflow"
    state = (run.get("conclusion") or run.get("status") or "unknown").lower().replace(" ", "_")
    ref = run.get("headBranch") or ""
    number = run.get("number")
    url = run.get("url") or ""
    compact.append(
        {
            "workflow": workflow,
            "state": state,
            "ref": ref,
            "number": number,
            "url": url,
        }
    )

    part = f"{workflow}={state}"
    if ref:
        part += f"@{ref}"
    if number:
        part += f"#{number}"
    summary_parts.append(part)

    if not watch_number and state in {"queued", "pending", "waiting", "requested", "in_progress"} and number:
        watch_number = str(number)

print("SUMMARY=" + " | ".join(summary_parts))
print("JSON=" + json.dumps(compact, separators=(",", ":")))
print("WATCH=" + watch_number)
PY
    )

    LAST_WORKFLOW_SUMMARY=$(printf '%s\n' "$parsed" | sed -n 's/^SUMMARY=//p')
    LAST_WORKFLOW_JSON=$(printf '%s\n' "$parsed" | sed -n 's/^JSON=//p')
    local watch_number
    watch_number=$(printf '%s\n' "$parsed" | sed -n 's/^WATCH=//p')
    if [[ -n "$watch_number" ]]; then
        LAST_WORKFLOW_HINT="gh run watch ${watch_number} --repo ${repo_slug} --exit-status"
    fi
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
    file_count=$(echo "$changed" | grep -c . || true)

    local type="chore"
    local scope=""
    local repo_name
    repo_name=$(resolve_repo_name "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

    if [[ "$repo_name" == ".claude" || "$repo_name" == ".codex" ]]; then
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
    elif [[ -x "$SCRIPT_DIR/dev-tools.sh" ]]; then
        dt_cmd="$SCRIPT_DIR/dev-tools.sh"
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

run_destructive_path_guard() {
    local repo_root
    repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

    if [[ ! -x "$GUARD_BIN" ]]; then
        echo "Destructive-path guard unavailable: missing $GUARD_BIN"
        return 1
    fi

    local guard_out="" guard_status=0
    guard_out=$("$GUARD_BIN" --staged-git --cwd "$repo_root" 2>&1) || guard_status=$?

    if [[ $guard_status -eq 0 ]]; then
        return 0
    fi

    echo "$guard_out"
    return "$guard_status"
}

get_managed_repos() {
    local repos=()

    local api_response backup_sources_response
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
    fi

    if backup_sources_response=$(curl -sf --connect-timeout 2 "$BACKUP_SOURCES_API" 2>/dev/null); then
        if command -v jq &>/dev/null; then
            while IFS= read -r path; do
                [[ -d "$path/.git" ]] && repos+=("$path")
            done < <(echo "$backup_sources_response" | jq -r '.[] | select(.source_type == "config" or .source_type == "workspace") | .path // empty')
        else
            while IFS= read -r path; do
                [[ -d "$path/.git" ]] && repos+=("$path")
            done < <(echo "$backup_sources_response" | grep -o '"path":"[^"]*"' | sed 's/"path":"//;s/"$//')
        fi
    fi

    if [[ -f "$FALLBACK_FILE" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${line// }" ]] && continue
            local expanded="${line/#\~/$HOME}"
            [[ -d "$expanded/.git" ]] && repos+=("$expanded")
        done < "$FALLBACK_FILE"
    fi

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
# Args: status name sha message pushed gates reason [detail]
emit_result() {
    local status=$1 name=$2 sha=$3 message=$4 pushed=$5 gates=$6 reason=$7 detail=${8:-}
    LAST_STATUS="$status"
    local workflow_summary="$LAST_WORKFLOW_SUMMARY"
    local workflow_json="$LAST_WORKFLOW_JSON"
    local workflow_hint="$LAST_WORKFLOW_HINT"

    if $JSON_OUTPUT; then
        local json_entry
        json_entry=$(printf '{"name":"%s","status":"%s","sha":"%s","message":"%s","pushed":%s,"gates":"%s","reason":"%s","detail":"%s","workflow_summary":"%s","workflow_hint":"%s","workflow_runs":%s}' \
            "$(json_escape "$name")" "$status" "$sha" "$(json_escape "$message")" "$pushed" "$(json_escape "$gates")" "$(json_escape "$reason")" "$(json_escape "$detail")" "$(json_escape "$workflow_summary")" "$(json_escape "$workflow_hint")" "$workflow_json")
        JSON_RESULTS+=("$json_entry")
    else
        case "$status" in
            SUCCESS)
                echo "  SUCCESS:${name}:${sha}:${message}:pushed=${pushed}"
                [[ -n "$workflow_summary" ]] && echo "    workflows: $workflow_summary"
                [[ -n "$workflow_hint" ]] && echo "    watch: $workflow_hint"
                ;;
            SKIP)
                echo "  SKIP:${name}:${reason}"
                ;;
            BLOCKED)
                echo "  BLOCKED:${name}:quality_gates_failed"
                ;;
            PARTIAL)
                echo "  WARN:${name}:${sha}:committed_not_pushed:${reason}"
                [[ -n "$detail" ]] && echo "    detail: $detail"
                ;;
            ERROR)
                local label="${reason:-$gates}"
                echo "  ERROR:${name}:${label}"
                [[ -n "$detail" ]] && echo "    detail: $detail"
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
    repo_name=$(resolve_repo_name "$repo")

    cd "$repo" || return 1
    clear_workflow_summary

    local branch file_count
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    file_count=$(scope_status | wc -l | tr -d ' ')

    if [[ "$file_count" -eq 0 ]]; then
        if has_commit_scope; then
            emit_result "SKIP" "$repo_name" "" "" "false" "" "no_matching_changes"
            return 0
        fi
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

    scope_add_all

    local guard_out="" guard_status=0
    guard_out=$(run_destructive_path_guard 2>&1) || guard_status=$?
    if [[ $guard_status -ne 0 ]]; then
        emit_result "BLOCKED" "$repo_name" "" "" "false" "destructive_guard:FAIL" "destructive_path_conflict"
        if ! $JSON_OUTPUT; then
            echo "$guard_out" | sed 's/^/  /'
        fi
        return 1
    fi

    local gates=""
    if ! $SKIP_CHECKS; then
        local gates_out gates_status=0
        gates_out=$(run_quality_gates 2>&1) || gates_status=$?

        if [[ $gates_status -ne 0 ]]; then
            echo "{\"timestamp\":$(date +%s),\"repo\":\"$repo_name\"}" > "$QUALITY_GATE_STATE"
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
        scope_reset_index
        if scope_has_changes; then
            scope_add_all
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

    scope_reset_index
    if scope_has_changes; then
        scope_add_all
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
                emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "$gates" "pull_conflict" "$LAST_PULL_DETAIL"
                return 1
            fi
            sha=$(git rev-parse --short HEAD)
        fi

        if push_current_branch "$branch"; then
            pushed="true"
            capture_workflow_summary "$(git rev-parse HEAD 2>/dev/null || echo "")"
        else
            emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "$gates" "push_failed" "$LAST_PUSH_DETAIL"
            return 1
        fi
    fi

    rm -f "$QUALITY_GATE_STATE"
    emit_result "SUCCESS" "$repo_name" "$sha" "$message" "$pushed" "$gates" ""
    return 0
}

commit_config_repo() {
    local repo=$1
    local repo_name
    repo_name=$(resolve_repo_name "$repo")

    cd "$repo" || return 1
    clear_workflow_summary

    local branch file_count
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    file_count=$(scope_status | wc -l | tr -d ' ')

    if [[ "$file_count" -eq 0 ]]; then
        if has_commit_scope; then
            emit_result "SKIP" "$repo_name" "" "" "false" "" "no_matching_changes"
            return 0
        fi
        handle_push_only "$repo_name" "$branch"
        return $?
    fi

    if ! git symbolic-ref -q HEAD &>/dev/null; then
        emit_result "SKIP" "$repo_name" "" "" "false" "" "detached_head"
        return 0
    fi

    scope_add_all

    local guard_out="" guard_status=0
    guard_out=$(run_destructive_path_guard 2>&1) || guard_status=$?
    if [[ $guard_status -ne 0 ]]; then
        emit_result "BLOCKED" "$repo_name" "" "" "false" "destructive_guard:FAIL" "destructive_path_conflict"
        if ! $JSON_OUTPUT; then
            echo "$guard_out" | sed 's/^/  /'
        fi
        return 1
    fi

    local message
    message="${CUSTOM_MSG:-$(generate_simple_message)}"

    local commit_out commit_status=0
    commit_out=$(git commit -m "$message" 2>&1) || commit_status=$?

    if [[ $commit_status -ne 0 ]]; then
        if scope_has_changes; then
            scope_add_all
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
                emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "" "pull_conflict" "$LAST_PULL_DETAIL"
                return 1
            fi
            sha=$(git rev-parse --short HEAD)
        fi

        if push_current_branch "$branch"; then
            pushed="true"
            capture_workflow_summary "$(git rev-parse HEAD 2>/dev/null || echo "")"
        else
            emit_result "PARTIAL" "$repo_name" "$sha" "$message" "false" "" "push_failed" "$LAST_PUSH_DETAIL"
            return 1
        fi
    fi

    emit_result "SUCCESS" "$repo_name" "$sha" "$message" "$pushed" "" ""
    return 0
}

handle_push_only() {
    local repo_name=$1
    local branch=$2
    clear_workflow_summary

    if $PUSH; then
        local upstream ahead
        upstream="origin/$branch"
        if git rev-parse "$upstream" &>/dev/null; then
            ahead=$(git rev-list --count "$upstream..HEAD" 2>/dev/null || echo "0")
            if [[ "$ahead" -gt 0 ]]; then
                if is_main_branch "$branch" && ! $FORCE; then
                    if ! safe_pull "$repo_name" "$branch"; then
                        emit_result "ERROR" "$repo_name" "" "" "false" "" "pull_conflict" "$LAST_PULL_DETAIL"
                        return 1
                    fi
                fi

                if push_current_branch "$branch"; then
                    capture_workflow_summary "$(git rev-parse HEAD 2>/dev/null || echo "")"
                    emit_result "SUCCESS" "$repo_name" "$(git rev-parse --short HEAD)" "pushed_${ahead}_commits" "true" "" ""
                    return 0
                fi
                emit_result "ERROR" "$repo_name" "" "" "false" "" "push_failed" "$LAST_PUSH_DETAIL"
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
    repo_name=$(resolve_repo_name "$repo")

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
        if [[ "$status" == "SUCCESS" && $success_count -gt 0 ]]; then
            echo "💡 Friction or ideas? st feedback search \"keyword\" or st feedback report <component> \"title\"" >&2
        fi
    fi

    [[ $error_count -gt 0 || $blocked_count -gt 0 ]] && exit 1
    exit 0
}

if [[ "${COMMIT_SH_SOURCE_ONLY:-0}" == "1" ]]; then
    return 0 2>/dev/null || exit 0
fi

main "$@"
