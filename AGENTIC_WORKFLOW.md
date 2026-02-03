# SummitFlow Autonomous Development Workflow

> Operating entirely within SummitFlow UI + Agent Hub. Agents use CLI tools (st, dt).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACE LAYER                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │  Kanban Board   │  │   Task Modal    │  │  Global Auto-Exec Dropdown  │  │
│  │  (drag status)  │  │  (start/stop)   │  │  (enable/disable projects)  │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────┘  │
│           │                    │                          │                  │
│           └────────────────────┼──────────────────────────┘                  │
│                                │                                             │
│                    WebSocket: /ws/execution/{taskId}                         │
│                    REST: /api/projects/{id}/tasks/{id}/execute               │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 │
┌────────────────────────────────┼─────────────────────────────────────────────┐
│                         SUMMITFLOW BACKEND (:8001)                           │
│                                │                                             │
│  ┌─────────────────────────────▼─────────────────────────────────────────┐  │
│  │                        Task API + Status Machine                       │  │
│  │  pending → queue → running → pr_created → ai_reviewing → completed    │  │
│  │      ↓       ↓        ↓          ↓             ↓                      │  │
│  │  cancelled blocked  paused    human_review  human_review              │  │
│  └─────────────────────────────┬─────────────────────────────────────────┘  │
│                                │                                             │
│  ┌─────────────────────────────▼─────────────────────────────────────────┐  │
│  │                     Redis Dispatch (pub/sub)                          │  │
│  │              Channel: summitflow:task_dispatch                         │  │
│  └─────────────────────────────┬─────────────────────────────────────────┘  │
│                                │                                             │
│  ┌─────────────────────────────▼─────────────────────────────────────────┐  │
│  │                     Celery Worker + Beat                              │  │
│  │  - dispatch_task_immediate (event-driven, <1s latency)                │  │
│  │  - autonomous_work_pickup (polling fallback, every 2h)                │  │
│  │  - process_scheduled_tasks (every 1m)                                 │  │
│  └─────────────────────────────┬─────────────────────────────────────────┘  │
│                                │                                             │
│  ┌─────────────────────────────▼─────────────────────────────────────────┐  │
│  │                     Execution Pipeline                                │  │
│  │  1. check_pristine_codebase() - dt --check                            │  │
│  │  2. Create worktree: ~/.local/share/st/worktrees/<project>/<task>/    │  │
│  │  3. For each subtask: _execute_subtask() via Agent Hub                │  │
│  │  4. Verify steps: run verify_command, check expected_output           │  │
│  │  5. Auto-commit after each subtask                                    │  │
│  │  6. ai_review() - Opus reviews changes                                │  │
│  └─────────────────────────────┬─────────────────────────────────────────┘  │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 │
┌────────────────────────────────┼─────────────────────────────────────────────┐
│                         AGENT HUB (:8003)                                    │
│                                │                                             │
│  ┌─────────────────────────────▼─────────────────────────────────────────┐  │
│  │                     Completion API + Memory                           │  │
│  │  - complete() with execute_tools=True (agentic mode)                  │  │
│  │  - Memory injection: mandates, guardrails, references                 │  │
│  │  - Multi-turn conversation per subtask                                │  │
│  └─────────────────────────────┬─────────────────────────────────────────┘  │
│                                │                                             │
│  ┌─────────────────────────────▼─────────────────────────────────────────┐  │
│  │                     Agent Roster                                      │  │
│  │  - planner: Generate implementation plans (subtasks + steps)          │  │
│  │  - coder: Execute code changes (Flash/Sonnet)                         │  │
│  │  - reviewer: Code review gate (Opus)                                  │  │
│  │  - supervisor: Coordination when stuck (Sonnet)                       │  │
│  │  - fixer: Error fixing (Sonnet)                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Task Lifecycle (Full State Machine)

```
                    ┌──────────────┐
                    │   pending    │ ◄── Task created
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  queue   │ │ planning │ │ cancelled│
        └────┬─────┘ └────┬─────┘ └──────────┘
             │            │
             └─────┬──────┘
                   │
                   ▼
             ┌──────────┐
             │ running  │ ◄── Agent executing
             └────┬─────┘
                  │
     ┌────────────┼────────────┬────────────┐
     │            │            │            │
     ▼            ▼            ▼            ▼
┌─────────┐ ┌─────────┐ ┌───────────┐ ┌──────────┐
│ blocked │ │ paused  │ │pr_created │ │ abandoned│
└────┬────┘ └────┬────┘ └─────┬─────┘ └──────────┘
     │           │            │
     └─────┬─────┘            │
           │                  ▼
           │           ┌─────────────┐
           │           │ai_reviewing │
           │           └──────┬──────┘
           │                  │
           │     ┌────────────┼────────────┐
           │     │            │            │
           │     ▼            ▼            ▼
           │ ┌─────────┐ ┌──────────┐ ┌──────────┐
           └►│human_   │ │completed │ │ failed   │
             │review   │ └──────────┘ └──────────┘
             └────┬────┘
                  │
                  ▼
             ┌──────────┐
             │completed │
             └──────────┘
```

**Kanban Column Mapping:**

| Column | Statuses |
|--------|----------|
| Ideas | pending (crowdsourced) |
| Planning | pending |
| Queue | queue |
| In Progress | running, paused, blocked |
| AI Review | pr_created, ai_reviewing |
| Human Review | human_review |
| Done | completed, failed, cancelled, abandoned |

---

## UI Controls

### Kanban Board (`/projects/{id}?tab=kanban`)

- **Drag tasks** between columns to change status
- **Click task card** to open Task Modal
- **Running tasks** show glowing border + current step

### Task Modal

| Control | Location | Effect |
|---------|----------|--------|
| **Start Execution** | Actions bar | POST `/execute`, status → running |
| **Stop** | Actions bar (when running) | WebSocket stop_signal, status → paused |
| **Continue** | Actions bar (when paused) | Resume execution |
| **Autonomous Toggle** | Actions bar | Enable/disable auto-pickup |
| **Agent Selector** | Actions bar | Choose coder/refactor/etc |
| **Approve/Request Changes** | Actions bar (human_review) | Complete or return to running |

### Execution Timeline (in Task Modal)

- **Auto-connects WebSocket** to `/ws/execution/{taskId}`
- **Shows historical + live events** (deduped, sorted by timestamp)
- **Chat input** to send directions to agent during execution

### Global Auto-Exec Dropdown (top-right)

- **All Off** (red) / **Partial** (yellow) / **All Active** (green)
- **Per-project toggles** with time window awareness
- Toggles `enabled` flag in project autonomous settings

### Bottom Execution Dock (floating panel)

- **Appears when tasks running**
- **Shows count**: "N task(s) running"
- **Accordion items** with current step + expandable timeline

---

## Execution Flow (What Happens)

### 1. Trigger Execution

**From UI:**
- Click "Start Execution" in Task Modal
- Task must have subtasks with steps

**From CLI:**
```bash
st autocode task-abc123              # Immediate
st autocode task-abc123 --at "22:00" # Scheduled
```

### 2. Dispatch

1. Task status → `queue`
2. Redis PUBLISH to `summitflow:task_dispatch`
3. Celery worker picks up via subscriber (event-driven, <1s)
4. Fallback: Beat polling every 2 hours

### 3. Execution Pipeline

```python
# /backend/app/tasks/autonomous/execution.py:667
def start_execution(task_id, project_id):
    # 1. Pristine check
    check_pristine_codebase()  # dt --check
    if fails:
        pristine_self_heal()   # Up to 3 attempts via coder agent

    # 2. Create worktree
    worktree_path = create_worktree(task_id)
    # ~/.local/share/st/worktrees/<project>/<task>/

    # 3. Execute subtasks
    for subtask in get_incomplete_subtasks(task_id):
        _execute_subtask(subtask)  # Agent Hub complete()
        auto_commit(subtask_id)

    # 4. AI Review
    ai_review(task_id)  # Opus reviewer agent
```

### 4. Subtask Execution

```python
# /backend/app/tasks/autonomous/execution.py:906
def _execute_subtask(subtask):
    # Call Agent Hub with execute_tools=True
    result = agent_hub.complete(
        agent="coder",
        messages=[subtask_prompt],
        execute_tools=True,  # Agentic mode
        memory=True          # Inject mandates/guardrails
    )

    # Verify each step
    for step in subtask.steps:
        output = run_command(step.verify_command)
        if not matches(output, step.expected_output):
            # Self-heal loop (3 attempts)
            # Then escalate: worker → supervisor → human
```

### 5. Review Gate

```python
# /backend/app/tasks/autonomous/review.py:25
def ai_review(task_id):
    diff = get_git_diff()
    verdict = agent_hub.complete(
        agent="reviewer",  # Opus
        messages=[review_prompt + diff]
    )

    if verdict == "APPROVED":
        if complexity == "SIMPLE":
            auto_merge()
        else:
            status → human_review
    elif verdict == "NEEDS_FIX":
        create_fix_subtask()
        restart_execution()
    elif verdict == "ESCALATE":
        status → human_review
```

---

## Quick Reference

### Task Management
```bash
st create <title> -t <type> -d <desc>   # Create task
st list --status pending                 # List by status
st context <task-id>                     # Full context (subtasks, steps)
```

### Execution
```bash
st autocode <task-id>                    # Queue for immediate execution
st autocode <task-id> --at "22:00"       # Schedule for 10pm
st exec-monitor <task-id> -f             # Follow execution events
```

### Checkpoint/Worktree
```bash
st claim <task-id>                       # Create worktree + git branch
st done <task-id>                        # Merge worktree to main
st abandon <task-id> --force             # Delete worktree without merge
st checkpoints                           # View active checkpoints
```

### Quality Gates
```bash
dt --check                               # Full quality gate
dt --quick                               # Fast check (lint + types)
./scripts/rebuild.sh                     # Rebuild after code changes
```

---

## Key Files

### Backend

| File | Purpose |
|------|---------|
| `backend/app/storage/tasks/status.py:113` | `update_task_status()` - status transitions |
| `backend/app/scheduling/dispatch.py:93` | `publish_task_ready()` - Redis dispatch |
| `backend/app/tasks/autonomous/pickup.py:382` | `handle_dispatch_event()` - event handler |
| `backend/app/tasks/autonomous/execution.py:667` | `start_execution()` - main orchestrator |
| `backend/app/tasks/autonomous/execution.py:906` | `_execute_subtask()` - per-subtask logic |
| `backend/app/tasks/autonomous/planning.py:25` | `create_plan()` - generate subtasks |
| `backend/app/tasks/autonomous/review.py:25` | `ai_review()` - Opus review gate |
| `backend/app/services/agent_hub_client.py:115` | Agent Hub client factory |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/components/kanban/TaskKanbanBoard.tsx` | Kanban with drag-drop |
| `frontend/components/kanban/TaskCard.tsx` | Task card with execution panel |
| `frontend/components/tasks/TaskModal.tsx` | Full task details + controls |
| `frontend/components/tasks/TaskModalActions.tsx` | Start/Stop/Agent buttons |
| `frontend/components/tasks/ExecutionTimeline.tsx` | Live event timeline |
| `frontend/hooks/useExecutionWebSocket.ts` | WebSocket connection |
| `frontend/components/layout/GlobalAutoExecDropdown.tsx` | Auto-exec toggle |
| `frontend/lib/api/tasks.ts:287` | `executeTask()` - API call |

---

## Service Ports

| Service | Port | Health Check |
|---------|------|--------------|
| SummitFlow Backend | 8001 | `curl localhost:8001/health` |
| SummitFlow Frontend | 3001 | `http://localhost:3001` |
| Agent Hub Backend | 8003 | `curl localhost:8003/api/health` |
| Agent Hub Frontend | 3003 | `http://localhost:3003` |
| Neo4j | 7687 | bolt protocol |
| Redis | 6379 | `redis-cli PING` |
| PostgreSQL | 5432 | `pg_isready` |

---

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Task not executing | `st context <id>` - has subtasks? | Add subtasks with steps |
| Step failing | `st exec-monitor <id>` | Check verify_command output |
| Agent Hub down | `journalctl --user -u agent-hub-backend` | `~/agent-hub/scripts/restart.sh` |
| Worktree missing | `st checkpoints` | `st claim <task-id>` |
| WebSocket not connecting | Browser console | Check CORS, service running |
| Auto-exec not picking up | Check settings | Enable via Global dropdown |

---

## Autonomous Settings

```bash
# View settings
curl localhost:8001/api/projects/summitflow/autonomous/settings

# Enable/disable
curl -X PATCH localhost:8001/api/projects/summitflow/autonomous/settings \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

| Setting | Description |
|---------|-------------|
| `enabled` | Whether autonomous pickup runs |
| `frequency_minutes` | How often to check for work |
| `max_concurrent` | Max parallel executions |
| `start_hour`/`end_hour` | Active hours (24h format) |

---

*Last updated: 2026-02-02*
