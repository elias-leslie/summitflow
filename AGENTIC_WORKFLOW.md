# SummitFlow Autonomous Development Workflow

> **Executive Summary:** SummitFlow is an autonomous software development platform that operates entirely within a self-hosted environment. It leverages a multi-agent system (Agent Hub) to plan, execute, review, and fix code tasks. The core workflow revolves around "Tasks" which are executed by agents in isolated "Worktrees" with full state checkpoints (Database + Git). This allows for safe experimentation, automated recovery (rollbacks), and continuous learning via the ACE (Agentic Context Engineering) memory system. Developers interact via the `st` CLI or the Web UI, while agents handle the heavy lifting of coding, testing, and verifying.

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
│                    REST: /api/ideas/... (Ideas Workflow)                     │
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
│  │  - daily_code_health_scan (daily)                                     │  │
│  │  - process_crowdsourced_ideas (daily)                                 │  │
│  └─────────────────────────────┬─────────────────────────────────────────┘  │
│                                │                                             │
│  ┌─────────────────────────────▼─────────────────────────────────────────┐  │
│  │                     Execution Pipeline                                │  │
│  │  1. check_pristine_codebase() - dt --check                            │  │
│  │  2. Create worktree: ~/.local/share/st/worktrees/<project>/<task>/   │  │
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
│  │                     Agent Roster (14 Agents)                          │  │
│  │                                                                         │  │
│  │  TIER 1 - Complex Analysis & Planning:                                  │  │
│  │  - planner (Opus→Gemini-3-pro): Creates implementation plans            │  │
│  │  - supervisor (Opus→Gemini-3-pro): Complex error analysis             │  │
│  │  - reviewer (Sonnet→Opus): Code review gate                             │  │
│  │  - qa (Opus→Sonnet): Execution quality review                           │  │
│  │                                                                         │  │
│  │  TIER 2 - Standard Implementation:                                      │  │
│  │  - coder (Gemini-3-flash→Sonnet): Code generation w/ tool permissions  │  │
│  │  - refactor (Flash→Sonnet→Opus): Code refactoring w/ behavior preservation│  │
│  │  - analyst (Sonnet→Gemini-3-pro): Codebase analysis                    │  │
│  │  - explorer (Flash→Sonnet): Fast codebase exploration                   │  │
│  │                                                                         │  │
│  │  TIER 3 - Quick Operations:                                             │  │
│  │  - worker (Flash→Sonnet): Fast error fixing                             │  │
│  │  - validator (Flash→Haiku): Quick validation & syntax checks            │  │
│  │  - auditor (Gemini-3-pro→Sonnet): Cross-checks fixes                    │  │
│  │                                                                         │  │
│  │  SPECIALIZED:                                                           │  │
│  │  - designer (Gemini-3-pro→Sonnet): UI/UX design analysis               │  │
│  │  - idea-intake (Flash→Haiku): Idea triage & clarification               │  │
│  │  - reasoner (Gemini-3-pro→Opus): Complex reasoning & trade-offs         │  │
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
- **Toggles `enabled`** flag in project autonomous settings

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
# /backend/app/tasks/autonomous/execution.py
def start_execution(task_id, project_id):
    # 1. Pristine check
    check_pristine_codebase()  # Uses st health or health cache
    if fails:
        pristine_self_heal()   # Up to 3 attempts via coder agent

    # 2. Create worktree with checkpoint
    worktree_path = create_worktree(task_id)
    # ~/.local/share/st/worktrees/<project>/<task>/

    # 3. Execute subtasks
    for subtask in get_incomplete_subtasks(task_id):
        _execute_subtask(subtask)  # Agent Hub run_agent()
        auto_commit(subtask_id)
        # Checkpoint updated after each subtask

    # 4. AI Review
    ai_review(task_id)  # Opus reviewer agent via Agent Hub
```

**Checkpoint System:**
- Checkpoints are created when claiming a task (`st claim`)
- Each checkpoint captures git state + database state
- If execution fails, can rollback to last checkpoint via `st abandon`
- Checkpoints enable safe experimentation - always have a known-good state to return to

### 4. Subtask Execution

```python
# /backend/app/tasks/autonomous/execution.py
def _execute_subtask(subtask):
    # Call Agent Hub with run_agent (agentic mode with tool loop)
    result = agent_hub.run_agent(
        agent_slug="coder",           # Or agent:supervisor for complex tasks
        messages=[subtask_prompt],
        project_id="summitflow",      # Memory scope
        external_id=subtask.task_id,  # Cost tracking
        purpose="code_generation",    # Kill switch categorization
    )
    # Returns: session_id, memory_uuids, cited_uuids

    # Log citations with ratings for ACE-aligned feedback loop
    log_citations(result.cited_uuids, rating="+")  # or "-" for harmful

    # Verify each step
    for step in subtask.steps:
        output = run_command(step.verify_command)
        if not matches(output, step.expected_output):
            # Self-heal loop (max 3 attempts via fixer agent)
            # Then escalate: worker → supervisor → human_review
```

**Agent Routing:**
- **coder** (claude-sonnet-4-5): Standard implementation tasks
- **supervisor** (claude-sonnet-4-5): Complex analysis, coordination
- **reviewer** (claude-opus-4-5): Code review gate
- **fixer** (claude-sonnet-4-5): Error fixing and debugging
- **worker** (gemini-3-flash): Quick fixes, simple tasks

### 5. Review Gate

```python
# /backend/app/tasks/autonomous/review.py
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

## Ideas & Crowdsourced Workflow

The ideas system allows capturing feature requests from any source and converting them into refined tasks.

### Workflow Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 1. IDEA CAPTURE                                             │
│    - Ideas stored in `ideas` table                          │
│    - Source tracking: manual, auto-detected, crowdsourced   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. IDEA INTAKE (idea-intake agent)                          │
│    - Triages ideas for clarity                              │
│    - Status: needs_clarification → clarification_requested    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. AUTO-CONVERSION TO TASK                                      │
│    - Approved ideas auto-convert to tasks                       │
│    - Task type='idea', source='crowdsourced'                    │
│    - Enters normal task lifecycle (pending → queue → running)   │
└─────────────────────────────────────────────────────────────────┘
```

### CLI Commands (Planned/API)

*Note: Some commands are currently available via API only.*

```bash
# Ideas management is currently handled via API endpoints
# /api/ideas/...
```

### Automated Processing

The `process_crowdsourced_ideas` Celery task (`backend/app/tasks/autonomous/ideas.py`):
1. Finds `approved` ideas without tasks
2. Auto-converts to tasks
3. Dispatches for execution if budget allows

---

## Code Health Workflow

Automated scanning identifies issues and generates fix tasks.

### Workflow Overview

1. **Scan Trigger:** Celery `daily_code_health_scan`
2. **Analysis:** AST analysis via `backend/app/tasks/code_health.py`
3. **Classification:** Gemini Flash classifies issues (True/False Positive)
4. **Task Generation:** True positives create `fix` tasks

### Health Metrics

| Metric | Target |
|--------|--------|
| Overall Health Score | >80% |
| Critical Issues | 0 |
| High Issues | <5 |

### CLI Commands

```bash
st health                              # Show quality gate summary
st health results                      # Show detailed findings
```

---

## Test-Driven Development (TDD) Workflow

TDD mode enforces writing tests before implementation.

### Workflow
1. **RED:** Write Failing Test
2. **GREEN:** Minimal Implementation
3. **REFACTOR:** Clean Up

### API Integration
- `GET /api/projects/{id}/tdd/suggestions`
- Logic in `backend/app/api/tdd.py`

---

## Memory & Citation Feedback Loop

The ACE system improves memory quality over time.

1. **Injection:** `agent-hub` injects Mandates/Guardrails/References.
2. **Citation:** Agent cites used memories `[M:abc]`.
3. **Rating:** System tracks helpfulness.
4. **Optimization:** Daily job promotes/demotes memories based on utility.

### CLI Commands

```bash
st memory stats                        # Overall statistics
st memory save "content"               # Save new learning
st memory list                         # List episodes
```

---

## Checkpoint & Rollback System

Checkpoints provide safe experimentation.

### Checkpoint Lifecycle

1. **Create:** `st claim` (Snapshot DB + Git Worktree)
2. **Execute:** Work happens in isolated worktree
3. **Complete:** `st done` (Merge & Cleanup)
4. **Rollback:** `st abandon` (Restore DB & Delete Worktree)

### Commands

```bash
st claim <task-id>                     # Create checkpoint + worktree
st done <task-id>                      # Complete & Merge
st abandon <task-id> --force           # Full Rollback
st checkpoints                         # List active
```

---

## Key Files

### Backend - Core Execution
| File | Purpose |
|------|---------|
| `backend/app/tasks/autonomous/execution.py` | Main execution orchestrator |
| `backend/app/tasks/autonomous/pickup.py` | Event-driven task dispatch |
| `backend/app/services/agent_hub_client.py` | Agent Hub API client with run_agent integration |
| `backend/app/storage/tasks/core.py` | Task CRUD operations and context retrieval |
| `backend/app/storage/tasks/status.py` | Status state machine and transitions |
| `backend/app/storage/task_spirit.py` | Task objectives, constraints, and approval state |
| `backend/app/api/tasks/core.py` | REST API endpoints for task management |
| `backend/app/api/events.py` | Event streaming API (REST + WebSocket) |

### Backend - Checkpoint & Worktree
| File | Purpose |
|------|---------|
| `backend/cli/lib/checkpoint.py` | Checkpoint logic |
| `backend/cli/lib/worktree.py` | Worktree management |
| `backend/cli/commands/claim.py` | `st claim` command |

### Backend - Explorer & Code Health
| File | Purpose |
|------|---------|
| `backend/app/services/explorer/` | Explorer service |
| `backend/app/tasks/code_health.py` | Code health scan task |
| `backend/app/services/code_health/classifier.py` | Finding classifier |

### Backend - Ideas & Task Generation
| File | Purpose |
|------|---------|
| `backend/app/api/ideas.py` | Ideas API endpoints |
| `backend/app/tasks/autonomous/ideas.py` | Crowdsourced idea processing |
| `backend/app/storage/ideas_repository.py` | Ideas DB storage |

### Backend - Memory
| File | Purpose |
|------|---------|
| `backend/cli/commands/memory.py` | `st memory` CLI commands |

### Frontend
| File | Purpose |
|------|---------|
| `frontend/components/kanban/TaskKanbanBoard.tsx` | Kanban UI |
| `frontend/components/tasks/TaskModal.tsx` | Task Details & Execution |
| `frontend/hooks/useExecutionWebSocket.ts` | Real-time events |

---

## Service Ports

| Service | Port | Health Check |
|---------|------|--------------|
| SummitFlow Backend | 8001 | `/health` |
| SummitFlow Frontend | 3001 | `http://localhost:3001` |
| Agent Hub Backend | 8003 | `/api/health` |

*Last updated: 2026-02-03 (v2.1 - Corrected file paths and CLI availability)*
