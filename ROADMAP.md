# SummitFlow & Agent Hub Roadmap

> Generated from moltbot/pi analysis on 2026-01-31
> Last Updated: 2026-01-31

## Status Legend

| Emoji | Status |
|-------|--------|
| 🔴 | Not Started |
| 🟡 | In Progress |
| 🟢 | Completed |
| 💬 | Needs Discussion |
| ⏸️ | Deferred |

---

## Priority Tiers

### Tier 1: Quick Wins (High ROI, Low Effort)

| # | Idea | Confidence | Effort | Impact | Status |
|---|------|------------|--------|--------|--------|
| 1 | Token-Aware Batch Packing for Graphiti | 92% | Easy | Reduce API costs by ~40% | 🔴 |
| 38 | Health Snapshot Caching with Async Refresh | 95% | Low | Faster health checks | 🔴 |
| 33 | OS-Specific Skill Gating | 98% | Trivial | Prevent skill errors on wrong OS | 🔴 |
| 2 | File-Level Change Debouncing | 90% | Easy | Reduce CPU/DB churn | 🔴 |
| 6 | Multi-Source Isolation | 88% | Easy | Better memory scoping | 🔴 |
| 7 | Line Number Tracking for Citations | 82% | Easy | Precise code citations | 🔴 |
| 31 | Bundled Resources for Skills | 96% | Low | Organized skill assets | 🔴 |
| 55 | YAML Frontmatter for Hooks | 87% | Low | Declarative hook config | 🔴 |
| 64 | Session-Based Prompt Caching | 87% | Low | API cost reduction | 🔴 |

### Tier 2: Foundation (Enables Future Features)

| # | Idea | Confidence | Effort | Impact | Status |
|---|------|------------|--------|--------|--------|
| 67 | Tool Call ID Normalization | 93% | Low-Med | Cross-provider support | 💬 |
| 22 | Real-Time Log Tailing | 92% | Low | Better debugging | 🟢 |
| 50 | Flexible Schedule Types (at/every/cron) | 92% | Medium | Schedule flexibility | 🟢 |
| 62 | ThinkingLevel Abstraction | 90% | Medium | Reasoning control | 🔴 |
| 65 | Content Type Abstraction | 92% | Low-Med | Multi-modal support | 🔴 |
| 68 | Provider Registry System | 91% | Low | Cleaner architecture | 🔴 |
| 69 | Error Classification & Recovery | 85% | Low | Better debugging | 🔴 |
| 23 | Command Registry with Routing | 90% | Low-Med | Faster CLI startup | 🔴 |
| 30 | Flexible Requirements (bins/env/anyBins) | 98% | Low-Med | Automatic skill gating | 🔴 |

### Tier 3: Strategic (Solves Major Pain Points)

| # | Idea | Confidence | Effort | Impact | Status |
|---|------|------------|--------|--------|--------|
| 60 | Cross-Provider Message Transformation | 95% | High | Seamless multi-provider | 💬 |
| 43 | Multi-Profile Browser Persistence | 92% | Medium | Login state survival | 💬 |
| 4 | Provider Fallback Chain | 88% | Medium | Production resilience | 🔴 |
| 21 | Interactive Multi-Section Wizards | 95% | Medium | Better setup UX | 🔴 |
| 29 | YAML Frontmatter Metadata Schema | 95% | Medium | Skill discovery | 🔴 |
| 32 | Multi-Method Install Orchestration | 92% | Medium | Better DX | 🔴 |
| 41 | Hot Config Reload | 91% | Medium | Developer UX | 🔴 |
| 51 | Run Logging with JSONL History | 90% | Medium | Audit trail | 🔴 |
| 52 | Run State Machine with Stuck Detection | 91% | Medium | Reliability | 🔴 |
| 59 | Unified Event Stream Interface | 92% | Medium | Real-time UX | 🔴 |

### Tier 4: Transformational (Architecture Changes)

| # | Idea | Confidence | Effort | Impact | Status |
|---|------|------------|--------|--------|--------|
| 24 | Comprehensive Doctor Commands | 88% | High | System diagnostics | 💬 |
| 36 | WebSocket RPC Protocol | 92% | High | Real-time comms | 🔴 |
| 44 | Tool Policy System | 88% | High | Access control | 🔴 |
| 46 | Sandbox Isolation (Docker) | 90% | High | Code execution safety | 🔴 |
| 54 | Event-Driven Hook System | 82% | High | Extensibility | 🔴 |
| 13 | Gateway Lifecycle Management | 97% | Hard | Production reliability | 🔴 |
| 14 | Security & DM Policies | 94% | Hard | Security | 🔴 |
| 15 | Thread/Group Context | 93% | Hard | Better conversation UX | 🔴 |
| 10 | Plugin Registration API | 95% | Hard | Extensibility | 🔴 |

### Tier 5: Future Consideration (Research/Prototype)

| # | Idea | Confidence | Effort | Impact | Status |
|---|------|------------|--------|--------|--------|
| 11 | Comprehensive Adapter Architecture | 98% | Very Hard | Full messaging capability | ⏸️ |
| 45 | A2UI Canvas System | 85% | Very Hard | Rich UI generation | ⏸️ |
| 57 | Gmail Watcher Service | 75% | Very High | External email triggers | ⏸️ |
| 35 | Skill Registry/Marketplace | 85% | High | Skill distribution | ⏸️ |
| 5 | Atomic Index Swapping | 78% | Hard | Safe reindexing | ⏸️ |
| 47 | Node Tools (camera/screen/location) | 78% | High | Device integration | ⏸️ |

---

## Complete Idea Inventory

### Memory System (Agent Hub)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 1 | Token-Aware Batch Packing | 92% | Easy | Pack episodes into batches by token count, not count |
| 2 | File-Level Change Debouncing | 90% | Easy | Debounce rapid file changes to reduce indexing |
| 3 | Hybrid Search Weighting | 85% | Medium | Combine vector + BM25 with tunable weights |
| 4 | Provider Fallback Chain | 88% | Medium | Auto-fallback when embedding provider fails |
| 5 | Atomic Index Swapping | 78% | Hard | Blue-green deployment for index rebuilds |
| 6 | Multi-Source Isolation | 88% | Easy | Scope memory by source type (file, user, etc) |
| 7 | Line Number Tracking | 82% | Easy | Track line numbers for precise citations |
| 8 | Smart Cache Key for Models | 75% | Medium | Cache invalidation on model change |
| 9 | Session-Aware Memory Search | 79% | Medium | Weight results by session relevance |

### Channel/Plugin System (Agent Hub)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 10 | Plugin Registration API | 95% | Hard | Dynamic plugin registration and discovery |
| 11 | Comprehensive Adapter Architecture | 98% | Very Hard | Full messaging capability matrix |
| 12 | Multi-Account Management | 92% | Medium | Multiple accounts per channel type |
| 13 | Gateway Lifecycle Management | 97% | Hard | Connect/disconnect with health monitoring |
| 14 | Security & DM Policies | 94% | Hard | Channel-level security policies |
| 15 | Thread/Group Context | 93% | Hard | Thread-aware conversation context |
| 16 | Message Actions | 91% | Medium | React, edit, delete message support |
| 17 | Health Checking & Status | 89% | Medium | Channel health monitoring |
| 18 | Config Schema with UI Hints | 87% | Medium | Self-documenting configuration |
| 19 | Directory/Peer Resolution | 88% | Medium | User discovery across channels |
| 20 | Streaming Coalescence | 83% | Medium | Buffer streaming output |

### CLI System (SummitFlow)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 21 | Interactive Wizards | 95% | Medium | Multi-step guided workflows |
| 22 | Real-Time Log Tailing | 92% | Low | `st logs -f` for live log viewing |
| 23 | Command Registry | 90% | Low-Med | Lazy-load commands for faster startup |
| 24 | Doctor Commands | 88% | High | Comprehensive system diagnostics |
| 25 | Session Compaction | 87% | Medium | Memory management commands |
| 26 | TOON Colorization | 78% | Low | Colored table output |
| 27 | Progress Reporters | 76% | Medium | Progress bars for long operations |
| 28 | Health Metrics Command | 82% | Medium | Resource monitoring CLI |

### Skills Platform (Both)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 29 | YAML Frontmatter Schema | 95% | Medium | Structured skill metadata |
| 30 | Flexible Requirements | 98% | Low-Med | bins/env/anyBins for gating |
| 31 | Bundled Resources | 96% | Low | Package scripts/references with skills |
| 32 | Install Orchestration | 92% | Medium | Multi-method install automation |
| 33 | OS-Specific Gating | 98% | Trivial | Prevent skill errors on wrong OS |
| 34 | Progressive Disclosure | 90% | Medium | Load skill details on demand |
| 35 | Skill Registry | 85% | High | Centralized skill distribution |

### Gateway/Daemon (Both)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 36 | WebSocket RPC | 92% | High | Real-time bidirectional comms |
| 37 | Scope-Based Auth | 88% | Medium | Fine-grained permissions |
| 38 | Health Snapshot Caching | 95% | Low | Cache health results with async refresh |
| 39 | Maintenance Timer Cascade | 93% | Low | Prevent resource leaks |
| 40 | Session Compaction | 90% | Low | Auto-compact old sessions |
| 41 | Hot Config Reload | 91% | Medium | Reload config without restart |
| 42 | Node Subscription Graph | 89% | Medium | Event routing topology |

### Browser/Tools (SummitFlow)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 43 | Multi-Profile Browser | 92% | Medium | Persist login states |
| 44 | Tool Policy System | 88% | High | Tool access control |
| 45 | A2UI Canvas | 85% | Very Hard | Rich UI generation |
| 46 | Sandbox Isolation | 90% | High | Docker-based code sandbox |
| 47 | Node Tools | 78% | High | Camera/screen/location access |
| 48 | Playwright + CDP Fallback | 85% | Low-Med | Browser automation robustness |
| 49 | Session Scope | 80% | Medium | Per-user browser context |

### Scheduling/Hooks (SummitFlow)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 50 | Flexible Schedules | 92% | Medium | at/every/cron syntax |
| 51 | Run Logging | 90% | Medium | JSONL execution history |
| 52 | Run State Machine | 91% | Medium | Detect stuck executions |
| 53 | Queue Modes | 85% | Medium | Delivery semantics (best effort, etc) |
| 54 | Event Hooks | 82% | High | Event-driven automation |
| 55 | YAML Frontmatter | 87% | Low | Declarative hook config |
| 56 | Workspace Precedence | 83% | Medium | Hook customization per workspace |
| 57 | Gmail Watcher | 75% | Very High | External email triggers |
| 58 | Heartbeat Integration | 84% | Medium | Service coordination |

### Pi LLM API (Agent Hub)

| # | Idea | Confidence | Effort | Description |
|---|------|------------|--------|-------------|
| 59 | Event Stream Interface | 92% | Medium | Unified streaming |
| 60 | Message Transformation | 95% | High | Cross-provider message format |
| 61 | OAuth Subscription Auth | 88% | High | User auth via OAuth |
| 62 | ThinkingLevel Abstraction | 90% | Medium | Reasoning budget control |
| 63 | Model Registry | 85% | Med-High | Dynamic model management |
| 64 | Prompt Caching | 87% | Low | Session-based caching |
| 65 | Content Type Abstraction | 92% | Low-Med | Multi-modal content handling |
| 66 | Compatibility Flags | 89% | Medium | Provider capability flags |
| 67 | Tool Call ID Normalization | 93% | Low-Med | Stable tool IDs across providers |
| 68 | Provider Registry | 91% | Low | Clean provider architecture |
| 69 | Error Classification | 85% | Low | Typed error handling |

---

## CC Native Task Tracking

| CC Task | Roadmap Item(s) | Status | Notes |
|---------|-----------------|--------|-------|
| #1 | Token-Aware Batch Packing (#1) | 🟢 | Implemented in episode_creator.py |
| #2 | Health Snapshot Caching (#38) | 🟢 | Implemented in both Agent Hub and SummitFlow |
| #3 | Real-Time Log Tailing (#22) | 🟢 | Implemented: st logs tail with journalctl |
| #4 | Multi-Profile Browser (#43) | ⏸️ | Deferred: CF auth in use, no browser logins needed |
| #5 | Tool Call ID Normalization (#67) | ⏸️ | Deferred: "Fresh Eyes" pattern preferred over history replay |
| #6 | Flexible Schedule Types (#50) | 🟢 | Discussed: Medium scope - event-driven + schedule types |
| #7 | Cross-Provider Message Transform (#60) | ⏸️ | Deferred: Not needed with "Fresh Eyes" escalation |
| #8 | Create ROADMAP.md | 🟢 | This file |

---

## Session Notes

### Session: 2026-01-31 (Initial Mining)

**Activities:**
- Launched 8 parallel explore agents on moltbot/pi repositories
- Analyzed: memory, channels, CLI, skills, gateway, browser, cron, LLM API
- Identified 69 potential improvements across all systems

**Key Insights:**
- moltbot's plugin architecture is far more sophisticated than needed for single-user setup
- Tool ID normalization is prerequisite for cross-provider message transformation
- Many moltbot features assume multi-user/multi-channel - need adaptation for single-user
- ST CLI and DT CLI are key differentiators - leverage them in agent testing

**Decisions:**
- Prioritize quick wins (Tier 1) for immediate value
- Discussion required for features needing single-user adaptation
- Skip multi-tenant features (not applicable)

**Created 7 CC native tasks for highest-priority items**

### Session: 2026-01-31 (Implementation Phase 1)

**Completed:**
- Task #1: Token-Aware Batch Packing (episode_creator.py)
- Task #2: Health Snapshot Caching (both projects)
- Task #3: Real-Time Log Tailing (st logs command)

**Deferred:**
- Task #4: Multi-Profile Browser - Not needed (CF auth, no browser logins)

**Pending Discussion:**
- Task #5: Tool Call ID Normalization
- Task #6: Flexible Schedule Types
- Task #7: Cross-Provider Message Transform (blocked by #5)

**Files Created:**
- `/home/kasadis/agent-hub/backend/app/services/health_cache.py`
- `/home/kasadis/summitflow/backend/app/services/health_cache.py`
- `/home/kasadis/summitflow/backend/cli/commands/logs.py`

**Files Modified:**
- `/home/kasadis/agent-hub/backend/app/services/memory/episode_creator.py`
- `/home/kasadis/agent-hub/backend/app/api/health.py`
- `/home/kasadis/summitflow/backend/app/main.py`
- `/home/kasadis/summitflow/backend/cli/main.py`

### Session: 2026-01-31 (Discussion Phase)

**Completed Discussions:**

**Task #5 & #7 - Tool Call ID Normalization & Cross-Provider Transform:**
- Consulted Gemini Pro via `/consult --pro`
- **Decision: DEFER** - "Fresh Eyes" escalation pattern preferred
- Cross-provider history replay causes "context poisoning"
- Better approach: Structured handoff with Post-Mortem summary
- Supervisor starts fresh session with original requirements + diagnostic context

**Task #6 - Flexible Schedule Types:**
- Explored Celery tasks across all projects (25+ SummitFlow, 3 Agent Hub, 40+ Portfolio-AI)
- **Pain point identified**: 30-min polling latency for `autonomous_work_pickup`
- Explored Auto-Claude (phase events, process spawning) and Moltbot (at/every/cron schedules)
- **Decision: Medium scope** - Event-driven dispatch + discriminated schedule types

**Architecture Decisions:**

1. **Escalation Pattern**: "Fresh Eyes" with structured handoff
   - Agent runs Post-Mortem on failure
   - Summary saved to subtask metadata
   - Supervisor starts fresh (no history replay)

2. **Mid-Session Assist**: Oracle Pattern
   - `consult_supervisor(question, context_summary)` tool
   - Stateless call, returns text answer
   - Agent continues own session

3. **Schedule Types** (moltbot-inspired):
   ```python
   TaskSchedule =
     | { kind: "at", timestamp: datetime }
     | { kind: "every", interval_ms: int, anchor_ms: int | None }
     | { kind: "cron", expr: str, tz: str | None }
   ```

4. **Event-Driven Dispatch**: Redis pub/sub replaces 30-min polling

**Next Steps:**
- ~~Implement Task #6 (event-driven dispatch + schedule types)~~ ✅ Done
- Create new task for "Structured Escalation Handoff" pattern

### Session: 2026-01-31 (Implementation Phase 2)

**Implemented: Event-Driven Dispatch with Flexible Schedule Types**

**Files Created:**
- `backend/app/scheduling/__init__.py` - Module exports
- `backend/app/scheduling/types.py` - TaskSchedule discriminated union (at/every/cron)
- `backend/app/scheduling/dispatch.py` - Redis pub/sub dispatcher

**Files Modified:**
- `backend/app/tasks/autonomous/pickup.py` - Added `dispatch_task_immediate` and `process_scheduled_tasks`
- `backend/app/tasks/autonomous/__init__.py` - Exported new tasks
- `backend/cli/commands/tasks.py` - Added `--at` flag to autocode command
- `backend/app/celery_app.py` - Reduced polling to 2h fallback, added 1-min scheduled task processor
- `backend/cli/main.py` - Updated CLI reference
- `backend/pyproject.toml` - Added croniter and pytz dependencies

**Key Changes:**
1. `st autocode` now publishes to Redis pub/sub for immediate dispatch
2. `st autocode --at "22:00"` schedules for later execution
3. Polling reduced from 30 min to 2 hours (fallback only)
4. Scheduled tasks stored in Redis sorted set, processed every 1 minute

**Schedule Type Support:**
```python
TaskSchedule =
  | OnceSchedule(timestamp=datetime)           # Run once at time
  | EverySchedule(interval_seconds, anchor)    # Recurring with anchor
  | CronSchedule(expr, tz)                     # Cron with timezone
```

---

## References

| Resource | Path |
|----------|------|
| moltbot REVIEW | `/home/kasadis/agent-hub/references/moltbot/REVIEW.md` |
| SummitFlow REVIEW | `/home/kasadis/summitflow/REVIEW.md` |
| moltbot source | `/home/kasadis/agent-hub/references/moltbot/` |
| pi-mono source | `/home/kasadis/agent-hub/references/pi-mono/` |

---

## Maintenance

To update this file:
1. Edit priority tiers as items are completed
2. Update task tracking table with CC task progress
3. Add session notes after each work session
4. Mark completed items with 🟢
