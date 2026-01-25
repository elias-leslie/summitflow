# Autonomous Execution Engine - E2E Test

## Instructions for Claude

Read this file, then execute the tasks in NEXT SESSION. Update this file with results and issues found. Fix bugs you discover. This is a living document.

## Current State

**Last Session:** 2026-01-25 (late night)
**Status:** Pipeline infrastructure complete. Needs WebSocket streaming, better planning, and QA review.

---

## NEXT SESSION: Complete the Pipeline

### Task 1: Wire Up WebSocket Streaming in execution.py

The execution timeline in the frontend shows nothing because `execution.py` doesn't emit WebSocket events.

**File:** `backend/app/tasks/autonomous/execution.py`

**Required changes:**

1. Import the async helpers:
   ```python
   import asyncio
   from ...api.ws_execution import send_log, send_progress
   ```

2. Create sync wrapper for async calls (Celery tasks are sync):
   ```python
   def _emit(coro):
       """Run async WebSocket emit from sync context."""
       try:
           loop = asyncio.get_event_loop()
           if loop.is_running():
               asyncio.ensure_future(coro)
           else:
               loop.run_until_complete(coro)
       except Exception:
           pass  # Don't fail execution if streaming fails
   ```

3. Add emissions at key points:
   - `start_execution`: emit "Starting execution" log + progress with total subtasks
   - `_execute_subtask` start: emit progress with subtask_id, status="in_progress"
   - `_execute_subtask` end: emit log with result (passed/failed)
   - `_verify_steps`: emit log for each step verification result
   - On error: emit error log

4. Test by:
   - Running execution
   - Watching frontend execution timeline
   - Verifying events appear in real-time

---

### Task 2: Improve Planning verify_commands (TDD-Style)

**The Problem:** Planner creates generic verify_commands that don't match actual code.

**Reference:** `~/.claude/skills/plan_it/SKILL.md` - TDD Check section

**Key principle:** verify_commands should FAIL before implementation, PASS after.

**Update `backend/app/tasks/autonomous/planning.py` prompt to include:**

```
## Verification Requirements

For each step, provide verify_command and expected_output:

1. verify_command must:
   - Return exit 0 when step is complete
   - Use rg (ripgrep) for code searches, NOT grep
   - Escape special chars: parens \( \), brackets \[ \]
   - Use relative paths from project root (backend/, not /home/.../backend/)
   - Include actual code patterns (function names, class names, type annotations)

2. expected_output must:
   - Be a specific string that appears in output
   - NOT be generic like "success" or "found"

## Common verify_command patterns:

Code exists:
  verify_command: "rg -q 'def my_function\\(' backend/app/module.py && echo 'Found'"
  expected_output: "Found"

Type annotation:
  verify_command: "rg 'CONSTANT: int = ' backend/app/constants.py"
  expected_output: "CONSTANT: int = "

Import exists:
  verify_command: "rg '^from.*import.*MyClass' backend/app/module.py && echo 'Import found'"
  expected_output: "Import found"

Tests pass:
  verify_command: "cd backend && .venv/bin/pytest tests/test_module.py -q"
  expected_output: "passed"

## BAD verify_commands (DO NOT USE):
- "cat file | grep something"  # Use rg instead
- "ls /home/user/project/..."  # Absolute paths
- "/path/to/.venv/bin/pytest"  # Absolute venv path
- "grep 'pattern' file"        # Use rg

## Deploy steps (REQUIRED for backend/frontend phases):

Backend:
  verify_command: "./scripts/rebuild.sh --backend 2>&1 | rg -q 'Rebuild complete' && echo 'Rebuild complete'"
  expected_output: "Rebuild complete"

Frontend (needs browser check after):
  verify_command: "./scripts/rebuild.sh --frontend 2>&1 | rg -q 'Rebuild complete' && echo 'Rebuild complete'"
  expected_output: "Rebuild complete"
```

**Also add validation** that rejects:
- verify_commands with absolute paths (`/home/`)
- verify_commands using `cat | grep` instead of `rg`
- Generic expected_output like just "success"

---

### Task 3: Add Stuck Detection + Escalation

**Reference:** `~/.claude/skills/do_it/SKILL.md` - Stuck Detection section

**The Pattern:**
- Track each verification failure with unique `issue_id`
- Same issue 3x at worker → escalate to supervisor
- Same issue 2x at supervisor → escalate to human
- Max 50 iterations (hard ceiling)

**Files to update:**

1. `execution.py` - Add issue tracking:
   ```python
   import hashlib
   import re

   def _compute_issue_id(error: str) -> str:
       """Normalize error to stable ID for stuck detection."""
       normalized = re.sub(r':\d+:', ':N:', error)  # Strip line numbers
       normalized = re.sub(r'/home/\w+/', '/HOME/', normalized)  # Strip paths
       normalized = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', normalized)  # Strip dates
       return hashlib.md5(normalized.encode()).hexdigest()[:8]

   # Track in subtask execution:
   issue_counts: dict[str, int] = {}  # issue_id -> count

   def _track_failure(error: str) -> tuple[str, int]:
       issue_id = _compute_issue_id(error)
       issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
       return issue_id, issue_counts[issue_id]
   ```

2. `escalation.py` - Already has 3-2-1 pattern, wire it up:
   - When worker fails 3x same issue → call supervisor
   - When supervisor fails 2x same issue → escalate to human_review status

**Escalation output format:**
```
ESCALATION_REQUIRED
Task: <task-id>
Subtask: <subtask-id>
Issue: <brief description>
Attempts: <count>/50
Reason: <why escalation needed>
```

---

### Task 4: Add QA Review Stage

**Reference:** `~/.claude/skills/do_it/SKILL.md` - QA Review section

**After all subtasks complete, run QA review:**

1. Call Agent Hub with `agent_slug="reviewer"` (already exists)
2. QA returns verdict: `APPROVED | NEEDS_FIX | PLAN_DEFECT | ESCALATE`

**Handle verdicts:**
- `APPROVED` → Move task to `pr_created` status
- `NEEDS_FIX` → Log issues, retry execution
- `PLAN_DEFECT` → Add fix step, mark original as defect, retry
- `ESCALATE` → Move to `human_review` status

**File:** Create `backend/app/tasks/autonomous/review.py` or update existing

---

### Task 5: Add Plan Defect Handling

**Reference:** `~/.claude/skills/do_it/SKILL.md` - On Verification Failure section

When implementation is correct but plan's verify_command is wrong:

1. Add fix step with correct verification
2. Pass the fix step (proving correct behavior)
3. Mark original step as `PLAN_DEFECT` with link to fix step
4. Continue execution

**This requires:**
- API to add steps to subtasks dynamically
- Step status field: `pending | passed | failed | plan_defect`
- Link field: `defect_fixed_by: <step_id>`

---

### Task 6: Add Spirit/Anti to Triage + Execution

**Reference:** `~/.claude/skills/plan_it/SKILL.md` - Spirit/Anti question

**Triage:** Ask LLM to identify:
- `spirit`: The core goal/intent (what TO do)
- `anti`: What should absolutely NOT be done

**Store in task_spirit:**
```python
create_task_spirit(
    task_id=task_id,
    objective=result.get("objective"),
    spirit_anti=f"SPIRIT: {result.get('spirit')}. ANTI: {result.get('anti')}",
    done_when=result.get("requirements"),
)
```

**Execution:** Before each subtask, check:
- Does this action advance SPIRIT?
- Does this action violate ANTI?
- If misaligned, log warning and potentially skip

---

### Task 7: Add Wind-Down / Session Preservation

**Reference:** `~/.claude/skills/do_it/SKILL.md` - Wind-Down Procedure

When execution pauses (timeout, max iterations, human escalation):

1. Log current progress:
   ```
   SESSION END <date>:
   COMPLETED: subtasks 1.1, 1.2
   IN PROGRESS: subtask 2.1 step 3
   REMAINING: subtasks 2.2, 3.1

   NEXT SESSION:
   1. Resume at: subtask 2.1 step 3
   2. Context: <key decisions made>
   3. Blockers: <issues found>
   ```

2. Set task status to `paused`
3. Store in progress_log for next session to read

---

## Reference: Complete Patterns from Skills

### plan.json Schema (from plan_it)

```json
{
  "title": "Action-oriented title",
  "objective": "Single measurable goal",
  "complexity": "SIMPLE | STANDARD",
  "spirit_anti": "SPIRIT: What to achieve. ANTI: What to avoid.",
  "done_when": ["Condition 1", "Condition 2"],
  "acceptance_criteria": [
    {
      "id": "ac-1",
      "criterion": "Measurable condition",
      "verify_command": "bash command",
      "expected_output": "string in output",
      "verify_by": "test | human"
    }
  ],
  "subtasks": [
    {
      "id": "1.1",
      "phase": "backend | frontend | scripts | data | verification",
      "description": "What this accomplishes",
      "depends_on": [],
      "steps": [
        {
          "description": "Step description",
          "verify_command": "bash command",
          "expected_output": "Expected output"
        }
      ]
    }
  ]
}
```

### Phase Guide (from plan_it)

| Phase | Deploy Required | Browser Check |
|-------|-----------------|---------------|
| `backend` | YES (`rebuild.sh --backend`) | NO |
| `frontend` | YES (`rebuild.sh --frontend`) | YES (agent-browser) |
| `scripts` | NO | NO |
| `data` | NO | NO |
| `verification` | NO | NO |

### Compliance Checklist (from plan_it)

| Issue | Fix |
|-------|-----|
| Missing `objective` | Add single measurable goal |
| Missing `spirit_anti` | Add "SPIRIT: X. ANTI: Y." |
| Step missing `verify_command` | Add bash command (exit 0 = pass) |
| Step missing `expected_output` | Add string that must appear |
| Absolute paths in verify | Use relative: `backend/`, not `/home/.../` |
| Backend subtask missing deploy | Add rebuild.sh step |
| Frontend missing browser check | Add agent-browser step |
| No verification subtask | Add final subtask with `phase: verification` |

### Execution Anti-Patterns (from do_it)

| Don't | Do |
|-------|-----|
| Retry same approach 5+ times | Track issue_id, escalate |
| Modify verify_command | Add fix step, mark PLAN_DEFECT |
| Skip stuck detection | Always track issue_id |
| Mark done without verification | Run verify_command |
| Ignore QA verdict | Apply fixes or escalate |
| Rush through work | Quality over quantity |

---

## Session 2026-01-25 (Night) - COMPLETED

### What Was Done

1. **Agent Hub Client Credentials** - Created summitflow-backend client
2. **Fixed triage.py** - Creates task_spirit with objective
3. **Fixed planning.py** - Uses complete() with agent_slug="planner"
4. **Added agent_slug to run_agent()** - Proper fix in Agent Hub backend + SDK
5. **Fixed execution.py** - Uses run_agent(agent_slug="coder")

### Test Results

- Triage: ✅ Works
- Planning: ✅ Works (creates subtasks)
- Execution: ✅ Works (HTTP 200, agent runs)
- **WebSocket streaming: ❌ Not wired up**
- **Verification: ❌ Generic verify_commands fail**
- **QA Review: ❌ Not implemented**
- **Stuck Detection: ❌ Not implemented**

---

## Files Modified This Session

**Agent Hub:**
- `backend/app/api/orchestration.py` - Added agent_slug support to run_agent
- `packages/agent-hub-client/agent_hub/client.py` - Added agent_slug to run_agent()

**SummitFlow:**
- `backend/app/tasks/autonomous/triage.py` - Create task_spirit on CLEAR
- `backend/app/tasks/autonomous/planning.py` - Use complete() not run_agent()
- `backend/app/tasks/autonomous/execution.py` - Use agent_slug="coder"
- `backend/.env` - Client credentials

---

## Notes

- Celery logs: `journalctl --user -u summitflow-celery -f`
- Agent Hub logs: `journalctl --user -u agent-hub-backend -f`
- Credentials: `/home/kasadis/summitflow/backend/.env`
- Skills: `~/.claude/skills/plan_it/SKILL.md`, `~/.claude/skills/do_it/SKILL.md`
- WebSocket endpoint: `backend/app/api/ws_execution.py`
- Frontend hook: `frontend/hooks/useExecutionWebSocket.ts`
