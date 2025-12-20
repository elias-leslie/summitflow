# Architecture Alignment Review

**Review Date:** 2025-12-20
**Reviewer:** Claude Code (Opus 4.5)

## Existing Services to Integrate With

### ClaudeClient (`backend/app/services/agents/claude.py`)

- **Current capability:** PreToolUse hooks for permission control
- **How to add after-tool callback:**
  - Extend `generate_with_tools_native()` to capture tool results AFTER execution
  - The SDK streams messages including tool results - intercept `ToolResultMessage` or similar
  - Add fire-and-forget `asyncio.create_task(capture_observation(...))` after tool completes
- **Lines 183-314:** Main integration point

### GeminiClient (`backend/app/services/agents/gemini.py`)

- **Current capability:** `before_tool_callback` for permission control via ADK
- **How to add after-tool callback:**
  - Google ADK supports `after_tool_callback` parameter in LlmAgent
  - Create wrapper that captures tool result after execution
  - Current `_create_before_tool_callback()` at line 178-244 can be paired with after callback
- **Lines 246-314:** Main integration point for `generate_with_tools_native()`

### RoundtableToolExecutor (`backend/app/services/roundtable_tools.py`)

- **Current capability:** Executes tools with path validation and permission checks
- **How to extend for capture:**
  - Add capture AFTER `executor(parameters)` returns at line 416
  - Pass session_id through executor (currently not tracked - need to add)
  - Fire-and-forget via `asyncio.create_task()`
- **Lines 400-423:** `execute()` method - main integration point

### RoundtableSession (`backend/app/services/roundtable.py`)

- **Current capability:** `get_context(max_messages=20)` returns simple string concatenation
- **How to extend for progressive disclosure:**
  - Add `get_context_index()` method returning ~500 token summary
  - Add `expand_entity(entity_id)` method for on-demand expansion
  - Integrate with TaskContextBuilder service
- **Lines 138-145:** `get_context()` method to extend

### RoundtableService (`backend/app/services/roundtable.py`)

- **Current capability:** Multi-agent routing, session management
- **How to extend:**
  - Add observation capture to message processing flow
  - Extend session creation to track observation context
- **Lines 148+:** Service class

---

## Agent Callback Integration Points

### ClaudeClient.generate_with_tools_native()

- **Location:** `backend/app/services/agents/claude.py:183-314`
- **Current implementation:**
  ```python
  async for message in query(prompt=full_prompt, options=options):
      yield message
  ```
- **How to extend:**
  - Intercept tool result messages in the async generator
  - When tool result detected, fire-and-forget capture
  - Or wrap the entire generator to capture post-execution

### GeminiClient._create_before_tool_callback()

- **Location:** `backend/app/services/agents/gemini.py:178-244`
- **Current implementation:** Returns permission decision before tool runs
- **How to extend:**
  - Add corresponding `_create_after_tool_callback()` method
  - Pass to LlmAgent constructor alongside before_tool_callback
  - ADK supports both callbacks natively

### RoundtableToolExecutor.execute()

- **Location:** `backend/app/services/roundtable_tools.py:406-423`
- **Current implementation:**
  ```python
  try:
      return executor(parameters)
  except Exception as e:
      ...
  ```
- **How to extend:**
  ```python
  try:
      result = executor(parameters)
      if result.success:
          asyncio.create_task(capture_observation(
              session_id=self.session_id,  # Need to add this property
              tool_name=tool_name,
              tool_input=parameters,
              tool_output=result.output,
          ))
      return result
  ```

---

## Database Schema Compatibility

### Existing Tables Phase 10 Extends

| Table | Extension Needed |
|-------|-----------------|
| `roundtable_sessions` | Add `messages_tsv tsvector` column for FTS |
| `tasks` | Foreign key target for `agent_checkpoints`, `session_diary` |
| `features` | Add `roundtable_session_id` column for linking (10d.4) |

### New Tables to Create

| Table | Purpose | Foreign Keys |
|-------|---------|--------------|
| `observations` | Store extracted observations | `session_id` (to roundtable_sessions or task execution) |
| `observation_queue` | Async processing queue | `session_id` |
| `agent_checkpoints` | Pause/resume state | `task_id` → `tasks` |
| `session_diary` | Execution learnings | `task_id` → `tasks` |
| `project_patterns` | Learned patterns | None (project_id nullable for global) |

### Migration Considerations

- Existing migrations in `backend/migrations/` (001-005)
- New migrations should be 006+
- Use `run_migration.py` pattern for execution
- Generated columns (tsvector) require PostgreSQL 12+
- GIN indexes for FTS performance

---

## API Router Organization

### Existing Pattern

```
backend/app/api/
├── beads.py           # Task-like entities
├── celery_endpoints.py # Celery status
├── evidence.py        # Evidence capture
├── explorer.py        # Codebase exploration
├── features.py        # Feature tracking
├── notifications.py   # User notifications
├── projects.py        # Project management
├── roundtable.py      # Multi-agent chat (SSE streaming)
├── tasks.py           # Task management
├── terminal.py        # Terminal sessions
├── terminal_sessions.py
├── vision_content.py  # Vision docs
└── vision_goals.py    # Vision goals
```

### Where Phase 10 Routers Fit

| New Router | Purpose | Registration |
|------------|---------|--------------|
| `memory.py` | Memory init, knowledge graph, search | `main.py` |
| `checkpoints.py` | Checkpoint CRUD, resume | `main.py` |
| `diary.py` | Diary entries, patterns, observations | `main.py` |

**Alternative:** Add endpoints to existing routers:
- Memory endpoints → `projects.py` (project-scoped)
- Checkpoint endpoints → `tasks.py` (task-scoped)
- Roundtable search → `roundtable.py` (session-scoped)

---

## Celery Integration

### Celery App Location

- **Path:** `backend/app/celery_app.py`
- **Broker:** Redis (DB 1)
- **Backend:** PostgreSQL via `db+DATABASE_URL`

### Existing Tasks

| Task | Location | Schedule |
|------|----------|----------|
| `scan_all_projects` | `app/tasks/explorer_tasks.py` | Every 6 hours |
| `capture_scheduled_evidence` | `app/tasks/evidence_tasks.py` | Every 6 hours |
| `cleanup_debug_captures` | `app/tasks/evidence_tasks.py` | Daily |

### New Tasks to Add

| Task | Location | Schedule |
|------|----------|----------|
| `process_observation_queue` | `app/jobs/observation_processor.py` | Every 30s (beat) |
| `run_weekly_reflection` | `app/jobs/weekly_reflection.py` | Weekly (beat) |

**Note:** Plan uses `app/jobs/` directory but existing tasks are in `app/tasks/`. Recommend using existing `app/tasks/` pattern for consistency.

### Beat Schedule Addition

```python
celery_app.conf.beat_schedule = {
    # ... existing tasks ...

    # Observation processing - every 30 seconds
    "process-observation-queue": {
        "task": "summitflow.process_observation_queue",
        "schedule": 30,  # Every 30 seconds
        "kwargs": {"batch_size": 10},
    },

    # Weekly reflection - Sundays at 3 AM UTC
    "run-weekly-reflection": {
        "task": "summitflow.run_weekly_reflection",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),
        "kwargs": {"days_back": 7},
    },
}
```

---

## SSE Streaming Integration

### Existing Events (from roundtable.py)

| Event | When Fired | Data |
|-------|------------|------|
| `user_message` | User sends message | Message content |
| `agent_start` | Agent begins response | Agent name, model |
| `agent_complete` | Agent finishes | Full response |
| `tool_use` | Tool being used | Tool name, args |
| `tool_result` | Tool completed | Result |
| `permission_request` | Write tool needs approval | Tool details |
| `permission_response` | User approved/denied | Decision |
| `keepalive` | Periodic | Timestamp |
| `done` | Stream complete | - |
| `error` | Error occurred | Error message |

### Where to Add observation_created Event

- **Location:** `backend/app/api/roundtable.py` SSE endpoint
- **When:** After Celery task extracts observation
- **Mechanism:** Use existing SSE broadcaster or add notification
- **Data:**
  ```json
  {
    "event": "observation_created",
    "data": {
      "id": "obs-123",
      "type": "discovery",
      "title": "Found authentication pattern",
      "session_id": "sess-456"
    }
  }
  ```

**Challenge:** Celery task runs separately from SSE stream. Options:
1. **Polling:** Frontend polls for new observations
2. **Redis pubsub:** Celery publishes, SSE subscribes
3. **Webhook:** Celery calls API which broadcasts SSE

Recommend option 2 (Redis pubsub) for real-time experience.

---

## Integration Points Verified

| Phase 10 Component | Integrates With | Method | Location |
|--------------------|-----------------|--------|----------|
| ObservationQueue | RoundtableToolExecutor | asyncio.create_task after execute() | roundtable_tools.py:416 |
| ObservationQueue | ClaudeClient | Intercept tool results in stream | claude.py:310 |
| ObservationQueue | GeminiClient | Add after_tool_callback to LlmAgent | gemini.py:282 |
| ObservationExtractor | Celery worker | process_observation_queue task | app/tasks/ (new) |
| ObservationExtractor | Agent clients | Uses get_agent() for LLM calls | agents/__init__.py |
| TaskContextBuilder | RoundtableSession | Extend get_context() | roundtable.py:138 |
| TaskContextBuilder | Explorer storage | Query explorer_entries | storage/explorer.py |
| CheckpointService | Tasks storage | Store/retrieve checkpoints | storage/tasks.py |
| DiaryService | Task completion | Hook into task status change | tasks.py API |
| FTS Search | roundtable_sessions | tsvector column + GIN index | storage/roundtable.py |
| SSE observation_created | Redis pubsub | Celery → Redis → SSE | roundtable.py API |

---

## Potential Conflicts

### 1. session_id Tracking in Tool Executor

**Issue:** `RoundtableToolExecutor` doesn't track `session_id` - it's created at the session level but executor doesn't receive it.

**Resolution:** Pass session_id when creating executor or add as property:
```python
# In RoundtableSession
self.tool_executor = get_default_executor()
self.tool_executor.session_id = self.id  # Add this
```

### 2. Jobs vs Tasks Directory

**Issue:** Plan proposes `app/jobs/` but existing pattern is `app/tasks/`

**Resolution:** Use `app/tasks/` for consistency:
- `app/tasks/observation_tasks.py` instead of `app/jobs/observation_processor.py`
- `app/tasks/reflection_tasks.py` instead of `app/jobs/weekly_reflection.py`

### 3. Celery Task Registration

**Issue:** New tasks need to be imported in `celery_app.py` for registration.

**Resolution:** Add to imports at bottom of `celery_app.py`:
```python
from app.tasks import (
    agent_runner,
    evidence_tasks,
    explorer_tasks,
    observation_tasks,  # Add
    reflection_tasks,   # Add
)
```

### 4. Memory Directory Location

**Issue:** Plan mentions `.summitflow/` directory in project roots, but SummitFlow manages external projects. Where is this created?

**Resolution:** Clarify in 10a.9:
- For SummitFlow project itself: `/home/kasadis/summitflow/.summitflow/`
- For managed projects: `{project_path}/.summitflow/`

### 5. Models Directory Empty

**Issue:** `backend/app/models/` exists but is empty. Plan doesn't specify using Pydantic models or dataclasses.

**Resolution:** Current pattern uses inline Pydantic models in API routers. Keep this pattern - no dedicated models needed.

---

## Recommendations

### 1. Use Existing Patterns

- Place new tasks in `app/tasks/` not `app/jobs/`
- Follow existing storage layer pattern (function-based, not class-based)
- Use existing Pydantic model pattern in API routers

### 2. Add session_id to Tool Executor

```python
# backend/app/services/roundtable.py
def create_session(...):
    session = RoundtableSession.create(...)
    session.tool_executor.session_id = session.id
    return session
```

### 3. Use Redis Pubsub for SSE Notifications

```python
# In Celery task after extraction
import redis
r = redis.from_url(REDIS_URL)
r.publish(f"observations:{session_id}", json.dumps({
    "event": "observation_created",
    "data": observation_dict
}))

# In SSE endpoint
async def sse_generator():
    pubsub = r.pubsub()
    pubsub.subscribe(f"observations:{session_id}")
    for message in pubsub.listen():
        if message["type"] == "message":
            yield f"event: observation_created\ndata: {message['data']}\n\n"
```

### 4. Progressive Disclosure in get_context()

```python
# backend/app/services/roundtable.py
def get_context_index(self, max_messages: int = 20) -> str:
    """Return ~500 token summary for progressive disclosure."""
    recent = self.messages[-max_messages:]
    return "\n".join([
        f"- [{m.id}] {m.agent}: {m.content[:60]}... (~{len(m.content)//4} tokens)"
        for m in recent
    ])

def expand_message(self, message_id: str) -> str:
    """Return full content for specific message."""
    for m in self.messages:
        if m.id == message_id:
            return m.content
    return ""
```

---

## Summary

The Phase 10 v2 plan is architecturally compatible with SummitFlow's existing infrastructure. Key integration points are well-defined and use established patterns. Minor adjustments needed:

1. **Directory:** Use `app/tasks/` not `app/jobs/`
2. **session_id:** Add to RoundtableToolExecutor
3. **SSE notifications:** Use Redis pubsub for real-time observation events
4. **Migrations:** Continue numbering from 006+

No fundamental conflicts detected. The plan extends rather than replaces existing infrastructure.
