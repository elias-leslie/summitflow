# Phase 10 v2 Implementation Recommendations

**Review Date:** 2025-12-20
**Reviewer:** Claude Code (Opus 4.5)

## Priority 1: Must Fix Before Implementation

None. The plan is well-aligned and ready for implementation.

The review identified no critical issues that would block implementation. Minor adjustments are recommended below but none are blockers.

---

## Priority 2: Should Adjust

### 1. Use `app/tasks/` Directory Instead of `app/jobs/`

**Issue:** Plan specifies creating `backend/app/jobs/observation_processor.py` and `backend/app/jobs/weekly_reflection.py`, but existing pattern uses `app/tasks/`.

**Recommendation:**
- Create `backend/app/tasks/observation_tasks.py` instead
- Create `backend/app/tasks/reflection_tasks.py` instead
- Update task references in implementation JSON (tasks 10a5.3, 10e.8)

### 2. Add session_id to RoundtableToolExecutor

**Issue:** `RoundtableToolExecutor` doesn't track `session_id`, but observation capture needs it.

**Recommendation:** Add to `RoundtableSession.create()` or session initialization:
```python
session.tool_executor.session_id = session.id
```

Or add `session_id` parameter to `RoundtableToolExecutor.__init__()`.

### 3. Use Redis Pubsub for SSE Observation Notifications

**Issue:** Plan mentions SSE event `observation_created` but doesn't specify how Celery task communicates to SSE endpoint.

**Recommendation:** Use Redis pubsub:
- Celery task publishes to channel `observations:{session_id}`
- SSE endpoint subscribes to channel and yields events
- This provides real-time experience without polling

---

## Priority 3: Nice to Have

### 1. Leverage Claude Code Rules Directory for Patterns

**Enhancement:** Write patterns to `.claude/rules/patterns/` in addition to database.

**Why:** Claude Code automatically loads rules from this directory, making patterns immediately available to future sessions without API calls.

**How:** In 10e.5 pattern application, also write to:
```
.claude/rules/patterns/{pattern_name}.md
```

### 2. Add PreCompact Hook for Session Diary

**Enhancement:** Add PreCompact hook to capture diary before context compression.

**Why:** Currently diary is created only on task completion. PreCompact would trigger diary for long sessions that hit context limits.

**How:** Add to `.claude/settings.local.json`:
```json
{
  "hooks": {
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "curl -X POST http://localhost:8001/api/diary/auto-save",
        "timeout": 5
      }]
    }]
  }
}
```

### 3. Claude Code CLI Integration

**Enhancement:** Create `/save-observation` skill for manual capture during CLI sessions.

**Why:** Currently observation capture only covers backend agents. When you (Claude Code) run directly, observations aren't captured.

**How:** Create `.claude/skills/save-observation/` with skill that calls backend API.

### 4. Observation De-duplication

**Enhancement:** Hash tool_input + tool_output to detect duplicates before queueing.

**Why:** Reduces redundant LLM extraction calls, saving cost.

**How:** Add to `ObservationQueue.enqueue()`:
```python
import hashlib
content_hash = hashlib.md5(f"{tool_name}:{json.dumps(tool_input)}:{tool_output}".encode()).hexdigest()
# Skip if hash exists in recent observations
```

---

## Existing Assets to Leverage

### Backend Infrastructure

| Asset | How to Leverage |
|-------|-----------------|
| ClaudeClient with PreToolUse hooks | Extend to capture tool results after execution |
| GeminiClient with before_tool_callback | Add after_tool_callback for capture |
| RoundtableToolExecutor.execute() | Add asyncio.create_task() after execution |
| SSE streaming in roundtable.py | Add observation_created event type |
| Celery app with beat schedule | Add observation processor and reflection tasks |
| Storage layer pattern | Follow existing function-based pattern |
| Migration system | Continue from 006+ |

### Claude Code Configuration

| Asset | How to Leverage |
|-------|-----------------|
| Stop hook (context monitoring) | Consider extending for diary triggers |
| Rules directory | Store learned patterns for auto-loading |
| Skills directory | Add observation-related skills |

---

## New Files to Create

### Backend Services

```
backend/app/services/
├── observation_queue.py      # Fire-and-forget queue
├── observation_extractor.py  # LLM extraction
├── context_builder.py        # Progressive disclosure
├── checkpoint_service.py     # Pause/resume
├── diary_service.py          # Auto-learning
├── explorer_cache.py         # Context caching
└── memory_init.py            # Project memory setup
```

### Backend Storage

```
backend/app/storage/
├── observations.py           # Observations table
├── observation_queue.py      # Queue table
├── checkpoints.py            # Checkpoints table
├── diary.py                  # Diary table
└── patterns.py               # Patterns table
```

### Backend Tasks (NOT jobs)

```
backend/app/tasks/
├── observation_tasks.py      # process_observation_queue Celery task
└── reflection_tasks.py       # run_weekly_reflection Celery task
```

### Backend API

```
backend/app/api/
├── memory.py                 # Memory init, knowledge graph, search
├── checkpoints.py            # Checkpoint CRUD, resume
└── diary.py                  # Diary, patterns, observations
```

### Database Migrations

```
backend/migrations/
├── 006_create_observations.sql       # observations + observation_queue tables
├── 007_create_checkpoints.sql        # agent_checkpoints table
├── 008_create_diary_patterns.sql     # session_diary + project_patterns tables
├── 009_add_roundtable_fts.sql        # FTS column on roundtable_sessions
└── 010_add_feature_session_link.sql  # roundtable_session_id on features
```

### Frontend Components

```
frontend/components/
├── observations/
│   └── ObservationViewer.tsx     # List and search observations
├── patterns/
│   └── PatternLibrary.tsx        # View and apply patterns
├── diary/
│   └── DiaryViewer.tsx           # View diary entries
├── learning/
│   └── LearningDashboard.tsx     # ROI metrics
├── tasks/
│   └── CheckpointViewer.tsx      # View/resume checkpoints
└── roundtable/
    └── RoundtableHistory.tsx     # Session history with search
```

### Claude Code Configuration (Optional Enhancements)

```
.claude/rules/patterns/
└── .gitkeep                  # Auto-generated patterns go here

.claude/skills/save-observation/
├── prompt.md                 # Skill for manual observation capture
└── handler.sh                # Calls backend API
```

---

## Updated Task List

### Tasks Needing Location Update

| Task ID | Current | Recommended |
|---------|---------|-------------|
| 10a5.3 | `app/jobs/observation_processor.py` | `app/tasks/observation_tasks.py` |
| 10e.8 | `app/jobs/weekly_reflection.py` | `app/tasks/reflection_tasks.py` |

### Tasks Needing Additional Steps

| Task ID | Additional Step |
|---------|-----------------|
| 10a5.4 | Add session_id property to RoundtableToolExecutor |
| 10a5.7 | Specify Redis pubsub mechanism for SSE notification |
| 10e.5 | Consider writing patterns to `.claude/rules/patterns/` |

---

## Implementation Order Recommendation

The plan's subphase ordering is correct. Within each phase:

### Phase 10A (Memory Infrastructure)

1. Database migrations first (10a.1-10a.6)
2. Storage layers (10a.7-10a.8)
3. Services (10a.9-10a.10)
4. API endpoints (10a.11)
5. Frontend (10a.12)
6. E2E verification (10a.13)

### Phase 10A.5 (Observation Capture)

1. ObservationQueue service first (10a5.1) - the foundation
2. ObservationExtractor (10a5.2) - uses existing LLM clients
3. Celery task (10a5.3) - ties queue to extractor
4. Integration points (10a5.4, 10a5.5, 10a5.6) - can be parallel
5. SSE event (10a5.7) - requires 10a5.3 to publish
6. Frontend (10a5.8)
7. E2E verification (10a5.9)

### Parallel Phase Opportunities

After 10A completes:
- 10C (Checkpoint/Resume) can run in parallel with 10A.5, 10B, 10D
- 10B depends on 10A.5 for observations
- 10D depends on 10A.5 for observation extraction
- 10E depends on 10A.5 for observations

Suggested order: 10A → 10A.5 → [10B, 10C, 10D] → 10E

---

## Risk Mitigation

### Performance Risk

**Risk:** Observation capture adds latency to tool execution.

**Mitigation:** The plan correctly specifies:
- Fire-and-forget with asyncio.create_task()
- <100ms latency target
- Graceful degradation on failures

### LLM Cost Risk

**Risk:** Observation extraction uses LLM calls, adding cost.

**Mitigation:**
- Use cheaper model (Gemini) for extraction
- Track discovery_tokens for ROI analysis
- Consider de-duplication to avoid redundant extraction

### Database Performance Risk

**Risk:** FTS queries on large tables could be slow.

**Mitigation:**
- GIN indexes specified in schema
- Use LIMIT in queries
- Consider partitioning if tables grow large

---

## Summary

The Phase 10 v2 plan is implementation-ready with minor adjustments:

1. **Critical:** None
2. **Should Adjust:** Use `app/tasks/` directory, add session_id tracking, specify Redis pubsub for SSE
3. **Nice to Have:** Rules directory for patterns, PreCompact hook, Claude Code CLI integration

The plan correctly extends existing infrastructure rather than rebuilding. All 60 tasks are aligned with v2 requirements. Implementation can proceed after these minor adjustments are incorporated into the implementation session prompts.
