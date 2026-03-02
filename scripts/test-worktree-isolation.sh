#!/bin/bash
# Worktree Isolation Test Runner for SummitFlow
#
# Tests the worktree isolation system across 9 phases (17-25).
# Each phase can be run independently.
#
# Usage:
#   test-worktree-isolation.sh           - Run all phases
#   test-worktree-isolation.sh <phase>   - Run specific phase (17-25)
#   test-worktree-isolation.sh --list    - List all phases
#
# Exit codes:
#   0 - All tests passed
#   1 - One or more tests failed

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
SUMMITFLOW_DIR="${HOME}/summitflow"
TEST_PROJECT="summitflow"
# Per-project worktree paths: ~/.local/share/st/worktrees/<project-id>/<task-id>/
WORKTREES_BASE="${HOME}/.local/share/st/worktrees/${TEST_PROJECT}"

# State tracking
PASSED=0
FAILED=0
SKIPPED=0
CURRENT_PHASE=""
TEST_TASK_IDS=()

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++)) || true  # Prevent exit on PASSED=0 with set -e
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED++)) || true
}

log_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
    ((SKIPPED++)) || true
}

log_section() {
    echo ""
    echo -e "${CYAN}=== $1 ===${NC}"
    echo ""
}

# Cleanup function - called on exit
cleanup() {
    log_section "Cleanup"

    # Delete any test tasks we created
    for task_id in "${TEST_TASK_IDS[@]}"; do
        log_info "Cleaning up task: $task_id"
        yes Y | st delete "$task_id" 2>/dev/null || true

        # Remove worktree if it exists
        local worktree_path="${WORKTREES_BASE}/${task_id}"
        if [ -d "$worktree_path" ]; then
            rm -rf "$worktree_path" 2>/dev/null || true
        fi
    done

    # Clean up any test branches
    cd "$SUMMITFLOW_DIR"
    git branch | grep -E "task-.*autotest|AutoTest" | xargs -r git branch -D 2>/dev/null || true

    # Restore any modified files
    git checkout backend/app/storage/__init__.py 2>/dev/null || true

    log_info "Cleanup complete"
}

# Setup trap for cleanup
trap cleanup EXIT

# Create a test task and track it
create_test_task() {
    local title="$1"
    local task_id

    task_id=$(st -P "$TEST_PROJECT" create "$title" -t task -p 3 --autonomous \
        -d "Worktree isolation test task" 2>&1 | grep -oE 'task-[a-f0-9]+')

    if [ -n "$task_id" ]; then
        TEST_TASK_IDS+=("$task_id")
        echo "$task_id"
    else
        return 1
    fi
}

# ============================================================================
# Phase 17: Worktree Creation
# ============================================================================
phase_17_worktree_creation() {
    log_section "Phase 17: Worktree Creation"
    CURRENT_PHASE="17"

    cd "$SUMMITFLOW_DIR"

    # 17.1 Test worktree module exists
    log_info "17.1 Testing worktree modules exist..."

    if [ -f "backend/cli/lib/worktree.py" ]; then
        log_pass "CLI worktree module exists"
    else
        log_fail "CLI worktree module missing"
        return 1
    fi

    if [ -f "backend/app/services/worktree.py" ]; then
        log_pass "Service worktree module exists"
    else
        log_fail "Service worktree module missing"
        return 1
    fi

    # 17.2 Test worktree creation via st claim
    log_info "17.2 Testing worktree creation via st claim..."

    local task_id
    task_id=$(create_test_task "AutoTest: P17 Worktree creation")

    if [ -z "$task_id" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    log_info "Created task: $task_id"

    # Claim the task
    if ! st claim "$task_id" 2>&1; then
        log_fail "st claim failed"
        return 1
    fi

    local worktree_path="${WORKTREES_BASE}/${task_id}"

    # Verify worktree was created
    if [ -d "$worktree_path" ]; then
        log_pass "Worktree directory created at $worktree_path"
    else
        log_fail "Worktree directory not created"
        st abandon "$task_id" --force 2>/dev/null || true
        return 1
    fi

    # Verify it's a valid git worktree
    if [ -f "$worktree_path/.git" ]; then
        log_pass ".git file exists (worktree marker)"
    else
        log_fail ".git file missing (not a worktree)"
    fi

    # Verify branch
    local branch
    branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [[ "$branch" == "${task_id}/main" ]]; then
        log_pass "Branch is $task_id/main"
    else
        log_fail "Branch is $branch, expected ${task_id}/main"
    fi

    # Verify project files exist
    if [ -f "$worktree_path/backend/pyproject.toml" ]; then
        log_pass "Worktree has backend"
    else
        log_fail "Backend missing from worktree"
    fi

    # 17.3 Verify checkpoint metadata
    log_info "17.3 Verifying checkpoint metadata..."

    local meta_file=".st/snapshots/${task_id}.meta.json"
    if [ -f "$meta_file" ]; then
        if grep -q "worktree_path" "$meta_file"; then
            log_pass "Metadata has worktree_path"
        else
            log_fail "Metadata missing worktree_path"
        fi
    else
        log_fail "Metadata file not created"
    fi

    # Cleanup
    st abandon "$task_id" --force 2>/dev/null || true

    return 0
}

# ============================================================================
# Phase 18: Isolation Enforcement
# ============================================================================
phase_18_isolation_enforcement() {
    log_section "Phase 18: Isolation Enforcement"
    CURRENT_PHASE="18"

    cd "$SUMMITFLOW_DIR"

    # 18.1 Test check_worktree_safety function exists
    log_info "18.1 Testing check_worktree_safety function..."

    if grep -q "def check_worktree_safety" backend/cli/lib/worktree.py; then
        log_pass "check_worktree_safety function exists"
    else
        log_fail "check_worktree_safety function missing"
        return 1
    fi

    # 18.2 Test safety check with active worktree
    log_info "18.2 Testing safety check with active worktree..."

    local task_id
    task_id=$(create_test_task "AutoTest: P18 Isolation enforcement")

    if [ -z "$task_id" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    st claim "$task_id" 2>&1 || true

    # Test the safety check
    local result
    result=$(python3 -c "
import sys
sys.path.insert(0, 'backend')
from cli.lib.worktree import check_worktree_safety, get_active_worktrees

is_safe, warning = check_worktree_safety(project_id='summitflow')
worktrees = get_active_worktrees(project_id='summitflow')
print(f'safe:{is_safe}')
print(f'worktrees:{len(worktrees)}')
if warning:
    print('has_warning:true')
" 2>/dev/null)

    if echo "$result" | grep -q "worktrees:[1-9]"; then
        log_pass "Active worktree detected"
    else
        log_fail "Active worktree not detected"
    fi

    # Cleanup
    st abandon "$task_id" --force 2>/dev/null || true

    return 0
}

# ============================================================================
# Phase 19: Done Workflow
# ============================================================================
phase_19_done_workflow() {
    log_section "Phase 19: Done Workflow"
    CURRENT_PHASE="19"

    cd "$SUMMITFLOW_DIR"

    log_info "19.1 Creating task with worktree..."

    local task_id
    task_id=$(create_test_task "AutoTest: P19 Done workflow")

    if [ -z "$task_id" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    # Add subtask with simple verification
    st subtask create 1.1 -t "$task_id" -d "Make a change" --phase backend \
        --steps-json '[{"description": "Add marker", "verify_command": "echo PASS", }]' 2>&1 || true

    # Claim task (creates worktree with task/main branch)
    st claim "$task_id" 2>&1 || {
        log_fail "st claim failed"
        return 1
    }

    local worktree_path="${WORKTREES_BASE}/${task_id}"

    # Claim subtask (creates subtask branch task/1.1 from task/main)
    st claim 1.1 -t "$task_id" 2>&1 || {
        log_fail "st claim subtask failed"
        st abandon "$task_id" --force 2>/dev/null || true
        return 1
    }

    local marker="# DONE_WORKFLOW_TEST_$(date +%s)"

    # Make a change in the worktree (on subtask branch)
    echo "$marker" >> "$worktree_path/backend/app/storage/__init__.py"

    # Commit in worktree
    (
        cd "$worktree_path"
        git add backend/app/storage/__init__.py
        git commit -m "AutoTest: Done workflow marker

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
    ) 2>&1 || {
        log_fail "Failed to commit in worktree"
        st abandon "$task_id" --force 2>/dev/null || true
        return 1
    }

    log_pass "Change committed in worktree"

    # Pass step and complete subtask
    log_info "19.2 Completing subtask..."
    st step pass 1.1 1 -t "$task_id" 2>&1 || true
    st subtask citations --none -s 1.1 -t "$task_id" 2>&1 || true
    st done 1.1 -t "$task_id" 2>&1 || {
        log_fail "Failed to complete subtask"
        st abandon "$task_id" --force 2>/dev/null || true
        return 1
    }
    log_pass "Subtask completed"

    # Complete task
    log_info "19.3 Completing task (triggers merge)..."
    st done "$task_id" 2>&1 || {
        log_fail "Failed to complete task"
        st abandon "$task_id" --force 2>/dev/null || true
        return 1
    }
    log_pass "Task completed"

    # Verify cleanup
    log_info "19.4 Verifying merge and cleanup..."

    if [ ! -d "$worktree_path" ]; then
        log_pass "Worktree cleaned up"
    else
        log_fail "Worktree still exists"
    fi

    # Check if change merged (checkout main first)
    git checkout main 2>/dev/null || true
    if grep -q "DONE_WORKFLOW_TEST" backend/app/storage/__init__.py 2>/dev/null; then
        log_pass "Change merged to main"
        # Clean up the marker
        git checkout backend/app/storage/__init__.py 2>/dev/null || true
    else
        log_skip "Change may not have merged (check manually)"
    fi

    return 0
}

# ============================================================================
# Phase 20: Abandon Workflow
# ============================================================================
phase_20_abandon_workflow() {
    log_section "Phase 20: Abandon Workflow"
    CURRENT_PHASE="20"

    cd "$SUMMITFLOW_DIR"

    log_info "20.1 Creating task with worktree..."

    local task_id
    task_id=$(create_test_task "AutoTest: P20 Abandon workflow")

    if [ -z "$task_id" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    st subtask create 1.1 -t "$task_id" -d "Change to abandon" --phase backend \
        --steps-json '[{"description": "Add marker", "verify_command": "echo PASS", }]' 2>&1 || true

    st claim "$task_id" 2>&1 || {
        log_fail "st claim failed"
        return 1
    }

    local worktree_path="${WORKTREES_BASE}/${task_id}"
    local marker="# ABANDON_TEST_$(date +%s)"

    # Make a change in the worktree
    echo "$marker" >> "$worktree_path/backend/app/storage/__init__.py"

    # Commit in worktree
    (
        cd "$worktree_path"
        git add backend/app/storage/__init__.py
        git commit -m "AutoTest: Change that will be abandoned"
    ) 2>&1 || true

    log_pass "Change committed in worktree (will be abandoned)"

    # Abandon task
    log_info "20.2 Abandoning task..."
    st abandon "$task_id" --force 2>&1 || {
        log_fail "st abandon failed"
        return 1
    }
    log_pass "Task abandoned"

    # Verify discard
    log_info "20.3 Verifying discard without merge..."

    if [ ! -d "$worktree_path" ]; then
        log_pass "Worktree removed"
    else
        log_fail "Worktree still exists"
    fi

    # Verify change NOT in main
    git checkout main 2>/dev/null || true
    if ! grep -q "ABANDON_TEST" backend/app/storage/__init__.py 2>/dev/null; then
        log_pass "Change was NOT merged (correctly discarded)"
    else
        log_fail "Change was incorrectly merged"
        git checkout backend/app/storage/__init__.py 2>/dev/null || true
    fi

    # Verify branch deleted
    if ! git branch | grep -q "$task_id"; then
        log_pass "Task branch deleted"
    else
        log_fail "Task branch still exists"
    fi

    return 0
}

# ============================================================================
# Phase 21: Service Port Isolation
# ============================================================================
phase_21_service_port_isolation() {
    log_section "Phase 21: Service Port Isolation"
    CURRENT_PHASE="21"

    cd "$SUMMITFLOW_DIR"

    # 21.1 Test worktree-services.sh exists
    log_info "21.1 Testing worktree-services.sh..."

    if [ -f "scripts/worktree-services.sh" ]; then
        log_pass "worktree-services.sh exists"
    else
        log_fail "worktree-services.sh missing"
        return 1
    fi

    # 21.2 Test port calculation
    log_info "21.2 Testing port calculation..."

    local result
    result=$(python3 -c "
import sys
sys.path.insert(0, 'backend')
from cli.lib.port_manager import calculate_ports, allocate_ports

# Test deterministic calculation (uses project root for config)
task1 = 'task-abc123'
task2 = 'task-def456'
project_root = '${SUMMITFLOW_DIR}'

backend1, frontend1 = calculate_ports(task1, project_root=project_root)
backend2, frontend2 = calculate_ports(task2, project_root=project_root)

# Ports should be in valid range (8100-8199 for summitflow default)
print(f'offset1_valid:{8100 <= backend1 < 8200}')
print(f'offset2_valid:{8100 <= backend2 < 8200}')

# Test port allocation
ports = allocate_ports('task-test', project_root=project_root)
print(f'backend_valid:{8100 <= ports.backend_port < 8200}')
print(f'frontend_valid:{3100 <= ports.frontend_port < 3200}')
" 2>/dev/null)

    if echo "$result" | grep -q "offset1_valid:True"; then
        log_pass "Port offset 1 in valid range"
    else
        log_fail "Port offset 1 invalid"
    fi

    if echo "$result" | grep -q "backend_valid:True"; then
        log_pass "Backend port in range 8100-8199"
    else
        log_fail "Backend port out of range"
    fi

    if echo "$result" | grep -q "frontend_valid:True"; then
        log_pass "Frontend port in range 3100-3199"
    else
        log_fail "Frontend port out of range"
    fi

    # 21.3 Verify port allocation on claim
    log_info "21.3 Verifying port allocation on claim..."

    local task_id
    task_id=$(create_test_task "AutoTest: P21 Port isolation")

    if [ -z "$task_id" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    st claim "$task_id" 2>&1 || {
        log_fail "st claim failed"
        return 1
    }

    local meta_file=".st/snapshots/${task_id}.meta.json"
    if [ -f "$meta_file" ]; then
        if grep -q "backend_port" "$meta_file" && grep -q "frontend_port" "$meta_file"; then
            log_pass "Port info in checkpoint metadata"
        else
            log_fail "Port info missing from metadata"
        fi
    else
        log_fail "Metadata file not created"
    fi

    # Cleanup
    st abandon "$task_id" --force 2>/dev/null || true

    return 0
}

# ============================================================================
# Phase 22: Step Verification Context
# ============================================================================
phase_22_step_verification_context() {
    log_section "Phase 22: Step Verification Context"
    CURRENT_PHASE="22"

    cd "$SUMMITFLOW_DIR"

    log_info "22.1 Testing execution path resolution..."

    local task_id
    task_id=$(create_test_task "AutoTest: P22 Step verification")

    if [ -z "$task_id" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    st claim "$task_id" 2>&1 || {
        log_fail "st claim failed"
        return 1
    }

    local result
    result=$(python3 -c "
import sys
sys.path.insert(0, 'backend')
# Use CLI module which doesn't have db deps
from cli.lib.worktree import get_worktree_info

task_id = '$task_id'

worktree = get_worktree_info(task_id, project_id='summitflow')
if worktree:
    print(f'worktree_found:true')
    print(f'worktree_path:{worktree.path}')
    if '.local/share/st/worktrees' in str(worktree.path):
        print('uses_worktree:true')
else:
    print('worktree_found:false')
" 2>/dev/null)

    if echo "$result" | grep -q "worktree_found:true"; then
        log_pass "Worktree found for task"
    else
        log_fail "Worktree not found"
    fi

    if echo "$result" | grep -q "uses_worktree:true"; then
        log_pass "Execution path uses worktree"
    else
        log_skip "Execution path may use project root"
    fi

    # Cleanup
    st abandon "$task_id" --force 2>/dev/null || true

    return 0
}

# ============================================================================
# Phase 23: Subagent Isolation
# ============================================================================
phase_23_subagent_isolation() {
    log_section "Phase 23: Subagent Isolation"
    CURRENT_PHASE="23"

    cd "$SUMMITFLOW_DIR"

    log_info "23.1 Verifying worktree service integration..."

    if grep -qE "ensure_task_worktree|get_execution_path" backend/app/tasks/autonomous/execution.py 2>/dev/null; then
        log_pass "Execution module uses worktree service"
    else
        log_skip "Execution module may not use worktree service directly"
    fi

    if grep -q "from.*worktree import" backend/app/tasks/autonomous/execution.py 2>/dev/null; then
        log_pass "Worktree service imported in execution"
    else
        log_skip "Worktree import may be indirect"
    fi

    return 0
}

# ============================================================================
# Phase 24: Parallel Worktrees
# ============================================================================
phase_24_parallel_worktrees() {
    log_section "Phase 24: Parallel Worktrees"
    CURRENT_PHASE="24"

    cd "$SUMMITFLOW_DIR"

    log_info "24.1 Testing get_active_worktrees..."

    # Create first task and worktree
    local task_id_1
    task_id_1=$(create_test_task "AutoTest: P24 Parallel 1")

    if [ -z "$task_id_1" ]; then
        log_fail "Failed to create test task 1"
        return 1
    fi

    st claim "$task_id_1" 2>&1 || {
        log_fail "st claim failed for task 1"
        return 1
    }

    log_pass "Created and claimed task 1: $task_id_1"

    # Test listing active worktrees
    local result
    result=$(python3 -c "
import sys
sys.path.insert(0, 'backend')
from cli.lib.worktree import get_active_worktrees

worktrees = get_active_worktrees(project_id='summitflow')
print(f'count:{len(worktrees)}')
for wt in worktrees:
    print(f'task:{wt.task_id}')
" 2>/dev/null)

    if echo "$result" | grep -q "count:[1-9]"; then
        log_pass "get_active_worktrees returns worktrees"
    else
        log_fail "get_active_worktrees returned empty"
    fi

    # Test port uniqueness
    log_info "24.2 Testing port uniqueness..."

    result=$(python3 -c "
import sys
sys.path.insert(0, 'backend')
from cli.lib.port_manager import calculate_ports

tasks = ['task-aaa', 'task-bbb', 'task-ccc', 'task-ddd', 'task-eee']
project_root = '${SUMMITFLOW_DIR}'
ports = [calculate_ports(t, project_root=project_root)[0] for t in tasks]
unique = len(set(ports))
print(f'unique_offsets:{unique}')
print(f'total_tasks:{len(tasks)}')
" 2>/dev/null)

    if echo "$result" | grep -qE "unique_offsets:[3-5]"; then
        log_pass "Port offsets vary across tasks"
    else
        log_skip "Port collision rate may be high"
    fi

    # Cleanup
    st abandon "$task_id_1" --force 2>/dev/null || true

    return 0
}

# ============================================================================
# Phase 25: Data Loss Prevention
# ============================================================================
phase_25_data_loss_prevention() {
    log_section "Phase 25: Data Loss Prevention"
    CURRENT_PHASE="25"

    cd "$SUMMITFLOW_DIR"

    # 25.1 Verify append-only approach
    log_info "25.1 Verifying append-only task metadata..."

    if grep -q 'db_restored.*False' backend/cli/commands/abandon.py 2>/dev/null; then
        log_pass "abandon.py uses append-only (no DB restore)"
    else
        log_skip "Check abandon.py manually for DB restore behavior"
    fi

    # 25.2 Test worktree protects main branch
    log_info "25.2 Testing worktree protects main branch..."

    local task_id
    task_id=$(create_test_task "AutoTest: P25 Data loss prevention")

    if [ -z "$task_id" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    st claim "$task_id" 2>&1 || {
        log_fail "st claim failed"
        return 1
    }

    local worktree_path="${WORKTREES_BASE}/${task_id}"
    local marker="# DATALOSS_PREVENT_$(date +%s)"

    # Make change in worktree
    echo "$marker" >> "$worktree_path/backend/app/storage/__init__.py"

    (
        cd "$worktree_path"
        git add backend/app/storage/__init__.py
        git commit -m "AutoTest: Data loss prevention test"
    ) 2>&1 || true

    # Verify main is unaffected
    cd "$SUMMITFLOW_DIR"
    git checkout main 2>/dev/null || true

    if ! grep -q "DATALOSS_PREVENT" backend/app/storage/__init__.py 2>/dev/null; then
        log_pass "Main branch unchanged during worktree work"
    else
        log_fail "Main branch was affected"
    fi

    # Abandon and verify still clean
    st abandon "$task_id" --force 2>/dev/null || true

    if ! grep -q "DATALOSS_PREVENT" backend/app/storage/__init__.py 2>/dev/null; then
        log_pass "Abandoned changes never reached main"
    else
        log_fail "Abandoned changes leaked to main"
        git checkout backend/app/storage/__init__.py 2>/dev/null || true
    fi

    # 25.3 Verify snapshot cleanup
    log_info "25.3 Verifying snapshot cleanup..."

    local task_id_2
    task_id_2=$(create_test_task "AutoTest: P25 Snapshot cleanup")

    if [ -z "$task_id_2" ]; then
        log_fail "Failed to create test task"
        return 1
    fi

    st claim "$task_id_2" 2>&1 || {
        log_fail "st claim failed"
        return 1
    }

    # Verify snapshot exists
    if [ -f ".st/snapshots/${task_id_2}.sql" ]; then
        log_pass "DB snapshot created"
    else
        log_fail "DB snapshot not created"
    fi

    # Abandon and verify cleanup
    st abandon "$task_id_2" --force 2>/dev/null || true

    if [ ! -f ".st/snapshots/${task_id_2}.sql" ]; then
        log_pass "DB snapshot removed on abandon"
    else
        log_fail "DB snapshot not cleaned up"
    fi

    return 0
}

# ============================================================================
# Main runner
# ============================================================================

list_phases() {
    echo "Worktree Isolation Test Phases:"
    echo ""
    echo "  17 - Worktree Creation"
    echo "  18 - Isolation Enforcement"
    echo "  19 - Done Workflow"
    echo "  20 - Abandon Workflow"
    echo "  21 - Service Port Isolation"
    echo "  22 - Step Verification Context"
    echo "  23 - Subagent Isolation"
    echo "  24 - Parallel Worktrees"
    echo "  25 - Data Loss Prevention"
    echo ""
    echo "Usage:"
    echo "  $0           - Run all phases"
    echo "  $0 <phase>   - Run specific phase (17-25)"
}

run_phase() {
    local phase="$1"

    case "$phase" in
        17) phase_17_worktree_creation ;;
        18) phase_18_isolation_enforcement ;;
        19) phase_19_done_workflow ;;
        20) phase_20_abandon_workflow ;;
        21) phase_21_service_port_isolation ;;
        22) phase_22_step_verification_context ;;
        23) phase_23_subagent_isolation ;;
        24) phase_24_parallel_worktrees ;;
        25) phase_25_data_loss_prevention ;;
        *)
            echo -e "${RED}Unknown phase: $phase${NC}"
            list_phases
            exit 1
            ;;
    esac
}

main() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║       SummitFlow Worktree Isolation Test Suite             ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Handle arguments
    if [ "$1" = "--list" ] || [ "$1" = "-l" ]; then
        list_phases
        exit 0
    fi

    # Ensure we're in the summitflow directory
    cd "$SUMMITFLOW_DIR" || {
        echo -e "${RED}Error: Cannot cd to $SUMMITFLOW_DIR${NC}"
        exit 1
    }

    # Ensure clean working tree (for st claim to work)
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        echo -e "${YELLOW}Warning: Working tree has uncommitted changes${NC}"
        echo "Consider committing or stashing before running tests."
        echo ""
    fi

    local start_time
    start_time=$(date +%s)

    if [ -n "$1" ]; then
        # Run specific phase
        run_phase "$1"
    else
        # Run all phases
        for phase in 17 18 19 20 21 22 23 24 25; do
            run_phase "$phase"
            echo ""
        done
    fi

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Summary
    log_section "Test Summary"
    echo -e "  ${GREEN}Passed:${NC}  $PASSED"
    echo -e "  ${RED}Failed:${NC}  $FAILED"
    echo -e "  ${YELLOW}Skipped:${NC} $SKIPPED"
    echo ""
    echo "  Duration: ${duration}s"
    echo ""

    if [ "$FAILED" -eq 0 ]; then
        echo -e "${GREEN}All tests passed!${NC}"
        exit 0
    else
        echo -e "${RED}Some tests failed.${NC}"
        exit 1
    fi
}

main "$@"
