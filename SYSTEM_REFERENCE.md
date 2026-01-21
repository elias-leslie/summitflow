# SummitFlow + Agent Hub System Reference

## Executive Summary

**SummitFlow** and **Agent Hub** form an autonomous AI-assisted software development platform.

| System | Role | Port | Database |
|--------|------|------|----------|
| SummitFlow | Task orchestration, evidence capture, worktree isolation | 8001 (API), 3001 (UI) | PostgreSQL `summitflow` |
| Agent Hub | LLM routing, memory injection, session management | 8003 (API), 3003 (UI) | PostgreSQL `agent_hub` + Neo4j |

**Integration**: SummitFlow calls Agent Hub via REST API with `external_id` (task ID) and `project_id` for cost tracking and memory scoping. Agent Hub handles all LLM calls and memory operations transparently.

**Spirit**: "Fight entropy" - autonomous AI execution with human oversight gates, evidence-based verification, progressive memory enhancement, token efficiency.

---

## Index

1. [Architecture Overview](#1-architecture-overview)
2. [SummitFlow](#2-summitflow)
   - [2.1 Tech Stack](#21-tech-stack)
   - [2.2 Database Schema](#22-database-schema)
   - [2.3 API Endpoints](#23-api-endpoints)
   - [2.4 Services](#24-services)
   - [2.5 CLI Commands](#25-cli-commands)
   - [2.6 UI Pages](#26-ui-pages)
   - [2.7 Celery Tasks](#27-celery-tasks)
   - [2.8 Error Handling](#28-error-handling)
   - [2.9 Deployment](#29-deployment)
3. [Agent Hub](#3-agent-hub)
   - [3.1 Tech Stack](#31-tech-stack)
   - [3.2 Database Schema](#32-database-schema)
   - [3.3 API Endpoints](#33-api-endpoints)
   - [3.4 Memory System](#34-memory-system)
   - [3.5 Agents](#35-agents)
   - [3.6 UI Pages](#36-ui-pages)
   - [3.7 Error Handling](#37-error-handling)
   - [3.8 Deployment](#38-deployment)
4. [Integration](#4-integration)
5. [Live System State](#5-live-system-state)
6. [Key File Paths](#6-key-file-paths)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SUMMITFLOW (dev.summitflow.dev)                 │
│  Celery Beat (30 min) → autonomous_work_pickup() → OrchestratorService  │
│  ├─ Claim task (PostgreSQL lock)                                        │
│  ├─ Create worktree (/tmp/summitflow-worktrees/{project}/{task})        │
│  ├─ Execute subtasks via Agent Hub                                      │
│  ├─ Opus review gate                                                    │
│  └─ Auto-merge (Tier 1 only)                                           │
│                                                                         │
│  UI: Dashboard | Design | Explorer | Evidence | Kanban | Git | Backups  │
│  Backend: FastAPI (8001) | Celery | PostgreSQL | Redis DB 1             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ REST API + external_id
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         AGENT HUB (agent.summitflow.dev)                │
│  POST /api/complete                                                     │
│  ├─ Memory injection (3-block progressive)                              │
│  ├─ LLM call (Claude/Gemini with fallback chains)                       │
│  ├─ Citation tracking                                                   │
│  └─ Cost tracking per external_id                                       │
│                                                                         │
│  UI: Dashboard | Chat | Agents | Memory | Sessions | Admin              │
│  Backend: FastAPI (8003) | Neo4j (Graphiti) | PostgreSQL | Redis DB 2   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. SummitFlow

### 2.1 Tech Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Backend | FastAPI + Uvicorn | 0.115+ |
| Frontend | Next.js + React | 16.1.2 / 19 |
| Database | PostgreSQL + psycopg3 | 15+ |
| Queue | Celery + Redis | 5.4+ |
| Language | Python | 3.12+ |
| Styling | Tailwind CSS | 4.1 |
| Type Check | MyPy (strict) | 1.13+ |
| Linting | Ruff | 0.8+ |

### 2.2 Database Schema

**85 migrations** in `/home/kasadis/summitflow/backend/migrations/`

#### Core Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `projects` | Project registry | id, name, base_url, root_path, agent_configs (JSONB), automation_settings (JSONB) |
| `tasks` | Task records | id, project_id, title, status, priority, task_type, autonomous, complexity, claimed_by, lock_expires_at |
| `subtasks` | Task breakdown | id, task_id, title, status, order_index |
| `steps` | Subtask steps | id, subtask_id, title, status, order_index |
| `acceptance_criteria` | Reusable criteria | id, criterion_id, project_id, criterion, category, measurement, threshold |
| `task_criteria` | Task-criteria link | task_id, criterion_db_id |
| `evidence` | Captured artifacts | id, evidence_id, project_id, task_id, explorer_entry_id, evidence_type, file_path, quality_status, version |
| `explorer_entries` | Codebase entities | id, project_id, entry_type, path, name, health_status, metadata (JSONB) |
| `mockups` | Design mockups | id, mockup_id, project_id, name, status, file_path, generator, task_id |
| `design_standards` | Design rules | id, project_id, name, base_standard_id, is_base |
| `design_rules` | Individual rules | id, standard_id, category, rule_id, name, requirements (JSONB) |
| `backups` | Backup records | id, project_id, name, status, size_bytes, location |
| `backup_schedules` | Backup scheduling | id, project_id, enabled, frequency, retention_count |
| `scan_history` | Explorer scan logs | id, project_id, scan_type, triggered_by, metrics (JSONB) |

#### Task Status Values
```
pending → running → paused/blocked → pr_created → ai_reviewing → human_review → completed/failed/cancelled
```

#### Evidence Types
```
screenshot, mockup, test-output, api-response, console_error
```

#### Explorer Entry Types
```
file, table, endpoint, page, celery_task, dependency
```

### 2.3 API Endpoints

#### Projects
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/projects` | Register project |
| GET | `/api/projects` | List projects |
| GET | `/api/projects/with-stats` | List with task counts |
| GET | `/api/projects/{id}/health` | Health check |

#### Tasks
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/projects/{id}/tasks` | Create task |
| GET | `/api/projects/{id}/tasks` | List tasks |
| GET | `/api/tasks/{id}` | Get task |
| PATCH | `/api/tasks/{id}` | Update task |
| PATCH | `/api/tasks/{id}/status` | Update status |
| POST | `/api/tasks/{id}/claim` | Claim task |
| DELETE | `/api/tasks/{id}` | Delete task |

#### Subtasks & Steps
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/tasks/{id}/subtasks` | Create subtask |
| GET | `/api/tasks/{id}/subtasks` | List subtasks |
| POST | `/api/subtasks/{id}/steps` | Create step |
| PATCH | `/api/subtasks/{id}/status` | Update subtask status |
| PATCH | `/api/steps/{id}/status` | Update step status |

#### Criteria
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/tasks/{id}/criteria` | Add criterion |
| GET | `/api/tasks/{id}/criteria` | List criteria |
| POST | `/api/projects/{id}/acceptance-criteria` | Create reusable criterion |

#### Evidence
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/projects/{id}/evidence/capture` | Trigger capture |
| GET | `/api/projects/{id}/evidence` | List evidence |
| GET | `/api/projects/{id}/evidence/{eid}` | Get evidence |
| GET | `/api/projects/{id}/evidence/{eid}/screenshot` | Get image |
| POST | `/api/projects/{id}/evidence/{eid}/review` | User review |

#### Explorer
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/projects/{id}/explorer/scan` | Trigger scan |
| GET | `/api/projects/{id}/explorer` | List entries |
| GET | `/api/projects/{id}/explorer/stats` | Get stats |
| GET | `/api/projects/{id}/explorer/refactor-targets` | Get refactor candidates |

#### Mockups
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/projects/{id}/mockups` | Create mockup |
| GET | `/api/projects/{id}/mockups` | List mockups |
| GET | `/api/projects/{id}/mockups/stats` | Get stats |
| PUT | `/api/projects/{id}/mockups/{mid}/status` | Update status |

#### Design Standards
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/design-standards/base` | Get base standard |
| GET | `/api/projects/{id}/design-standards/effective-rules` | Get merged rules |
| POST | `/api/projects/{id}/design-standards/validate` | Validate element |

#### Git
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/git/status` | All repos status |
| POST | `/api/git/sync` | Sync all repos |
| GET | `/api/projects/{id}/worktrees` | List worktrees |
| DELETE | `/api/projects/{id}/worktrees/{task_id}` | Delete worktree |
| POST | `/api/projects/{id}/worktrees/{task_id}/merge` | Merge worktree |

#### Backups
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/projects/{id}/backups` | Create backup |
| GET | `/api/projects/{id}/backups` | List backups |
| POST | `/api/projects/{id}/backups/{bid}/restore` | Restore backup |
| GET | `/api/projects/{id}/backups/schedule` | Get schedule |
| PUT | `/api/projects/{id}/backups/schedule` | Update schedule |

#### Autonomous
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/projects/{id}/autonomous/settings` | Get settings |
| PUT | `/api/projects/{id}/autonomous/settings` | Update settings |
| GET | `/api/projects/{id}/autonomous/status` | Get status |

#### WebSocket
| Endpoint | Purpose |
|----------|---------|
| `/ws/execution/{task_id}` | Real-time execution streaming |

### 2.4 Services

| Service | File | Purpose |
|---------|------|---------|
| OrchestratorService | `services/orchestrator.py` | Task execution coordination |
| WorktreeManager | `services/worktree_manager.py` | Git worktree isolation |
| EvidenceManager | `services/evidence_manager.py` | Evidence capture/storage |
| MockupGenerator | `services/mockup_generator.py` | AI mockup generation |
| AgentHubClient | `services/agent_hub_client.py` | Agent Hub integration |
| SelfHealingOrchestrator | `services/self_healing/orchestrator.py` | Auto-fix orchestration |
| RecoveryManager | `services/recovery/manager.py` | Build state recovery |
| GitLifecycle | `services/git_lifecycle.py` | Git state machine |

### 2.5 CLI Commands

**Entry point**: `st` command

| Command | Subcommands | Purpose |
|---------|-------------|---------|
| `st create` | - | Create task |
| `st list` | - | List tasks |
| `st ready` | - | Mark task ready |
| `st show` | - | Show task details |
| `st close` | - | Close task |
| `st subtask` | list, show, create, pass, delete | Subtask management |
| `st step` | list, pass, create, add, delete | Step management |
| `st criterion` | list, create, update, preflight | Criteria management |
| `st worktree` | list, prune | Worktree management |
| `st git` | status, sync, cleanup | Git operations |
| `st backup` | list, create, restore, status, schedule | Backup management |
| `st autonomous` | enable, disable, status | Autonomous settings |

**Output modes**: `--compact` (TOON), `--human` (pretty JSON), `--no-compact` (raw JSON)

### 2.6 UI Pages

| URL | Component | Features |
|-----|-----------|----------|
| `/` | Dashboard | Project grid, activity feed, quick access |
| `/projects/{id}?tab=kanban` | Kanban | 6 columns, drag-drop, WebSocket streaming |
| `/projects/{id}?tab=explorer` | Explorer | 6 entry types, health status, refactor targets |
| `/projects/{id}?tab=evidence` | Evidence | Screenshots, AI review, mockup comparison |
| `/projects/{id}/design` | Design | Mockup management, Outrun Design System |
| `/git` | Git | Repository status, worktree management |
| `/backups` | Backups | Backup list, scheduling, restore |

#### Kanban Columns
```
Ideas → Planning → In Progress → AI Review → Human Review → Done
```

#### Design Standards (Outrun Design System)
- **Categories**: layout, typography, color, components, navigation
- **Rules**: 24 total across 5 categories
- **Colors**: Primary #ff0066, Secondary #00f5ff, Backgrounds #0f0a18/#1a0a2e
- **Fonts**: Space Grotesk (display), IBM Plex Sans (body), JetBrains Mono (code)

### 2.7 Celery Tasks

| Task | Schedule | Purpose |
|------|----------|---------|
| `autonomous-work-pickup-summitflow` | 30 min | Pick eligible tasks for execution |
| `review-pending-tasks-summitflow` | 30 min | Opus review gate |
| `cleanup-orphaned-worktrees` | 6 hours | Clean stale worktrees (30-day TTL) |
| `scan-all-projects` | 6 hours | Explorer scan |
| `daily-code-health-scan` | Daily | Code health metrics |
| `daily-evidence-capture` | Daily 2am | Automated evidence capture |
| `run-scheduled-backups` | Hourly | Scheduled backups |
| `process-crowdsourced-ideas-monkey-fight` | Daily 3am | Process approved ideas |
| `monitor-systemd-errors` | 5 min | Monitor service errors |
| `orchestrate-self-healing` | 15 min | Auto-fix orchestration |

### 2.8 Error Handling

#### Custom Exceptions
| Exception | File | Purpose |
|-----------|------|---------|
| `WorktreeError` | `worktree_manager.py` | Git worktree failures |
| `BudgetExceededError` | `self_healing/orchestrator.py` | $2.00 USD cap exceeded |
| `PristineCheckError` | `orchestrator_runner.py` | Quality gate failure |
| `StepGateError` | `steps.py` | Step gate failure |
| `SubtaskGateError` | `subtasks.py` | Subtask gate failure |
| `CycleError` | `subtask_dependencies.py` | Cyclic dependency |
| `FileLockError` | `file_lock.py` | File lock failure |

#### Safety Mechanisms
| Mechanism | Value | Purpose |
|-----------|-------|---------|
| Max retries | 3 | Task failure threshold |
| Stuck threshold | 2 | Escalate to supervisor after 2 failures |
| Budget cap | $2.00 USD | Self-healing cost limit |
| Blast radius | 5 files OR 100 deleted lines | Merge gate threshold |
| Worktree TTL | 30 days | Cleanup stale worktrees |
| Claim lock | 30 min | Task claim expiration |

#### WebSocket Recovery
- Message replay buffer: 100 messages
- Reconnection: via `?from_sequence={N}` parameter
- Stop signal: `{type: "stop_signal"}` for immediate halt

### 2.9 Deployment

#### Systemd Services
| Service | Port | Command |
|---------|------|---------|
| `summitflow-backend` | 8001 | `uvicorn app.main:app --host 0.0.0.0 --port 8001` |
| `summitflow-frontend` | 3001 | `npm run start -- --hostname 0.0.0.0 --port 3001` |
| `summitflow-celery` | - | `celery -A app.celery_app worker --concurrency=2` |
| `summitflow-celery-beat` | - | `celery -A app.celery_app beat` |

#### Environment Variables
```
DATABASE_URL=postgresql://summitflow_app:PASSWORD@localhost:5432/summitflow
REDIS_URL=redis://localhost:6379
AGENT_HUB_URL=http://localhost:8003
```

#### Redis Configuration
- **Database**: 1 (Celery broker)
- **Separation**: DB 0 = portfolio-ai, DB 1 = SummitFlow, DB 2 = Agent Hub

---

## 3. Agent Hub

### 3.1 Tech Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Backend | FastAPI + Uvicorn | 0.115+ |
| Frontend | Next.js + React | 16.1.2 / 19 |
| Primary DB | PostgreSQL | 15+ |
| Graph DB | Neo4j (Graphiti) | 2025.12.1 |
| Queue | Celery + Redis | 5.4+ |
| Language | Python | 3.13+ |
| LLM | Anthropic SDK, Google AI SDK | 0.40+, 1.21+ |

### 3.2 Database Schema

**14 migrations** in `/home/kasadis/agent-hub/backend/migrations/versions/`

#### PostgreSQL Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `sessions` | AI conversation sessions | id, project_id, external_id, provider, model, status, purpose, session_type |
| `messages` | Individual messages | id, session_id, role, content, tokens, agent_id, agent_name |
| `credentials` | Encrypted API keys | id, provider, credential_type, value_encrypted |
| `cost_logs` | Token/cost tracking | id, session_id, model, input_tokens, output_tokens, cost_usd |
| `agents` | Agent configurations | id, slug, name, system_prompt, primary_model_id, fallback_models, mandate_tags |
| `agent_versions` | Agent change history | id, agent_id, version, config_snapshot |
| `api_keys` | Virtual API keys | id, key_hash, project_id, rate_limit_rpm |
| `client_control` | Kill switch - clients | client_name, enabled, disabled_by, reason |
| `purpose_control` | Kill switch - purposes | purpose, enabled, disabled_by, reason |
| `client_purpose_control` | Kill switch - combos | client_name, purpose, enabled |
| `truncation_events` | Context overflow logs | id, model, output_tokens, max_tokens_requested |
| `message_feedback` | User ratings | id, message_id, feedback_type, category |

#### Neo4j Schema (Graphiti)

```cypher
(:Episodic {
  uuid: String,
  content: String,
  source_description: String,
  created_at: DateTime,
  loaded_count: Int,
  referenced_count: Int,
  success_count: Int,
  utility_score: Float
})

(:Entity {
  id: String,
  name: String,
  type: String
})

(:Episodic)-[:MENTIONS]->(:Entity)
```

### 3.3 API Endpoints

#### Completions
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/complete` | Single completion |
| POST | `/api/v1/chat/completions` | OpenAI-compatible |
| WS | `/api/stream` | WebSocket streaming |

#### Sessions
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/sessions` | Create session |
| GET | `/api/sessions` | List sessions |
| GET | `/api/sessions/{id}` | Get session with messages |
| POST | `/api/sessions/{id}/close` | Close session |
| POST | `/api/sessions/{id}/cancel` | Cancel streaming |

#### Agents
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/agents` | List agents |
| POST | `/api/agents` | Create agent |
| GET | `/api/agents/{slug}` | Get agent |
| PUT | `/api/agents/{slug}` | Update agent |
| DELETE | `/api/agents/{slug}` | Delete agent |
| GET | `/api/agents/{slug}/preview` | Preview with mandates |
| GET | `/api/agents/{slug}/metrics` | Get 24h metrics |

#### Memory
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/memory/add` | Add episode |
| GET | `/api/memory/list` | List episodes |
| GET | `/api/memory/search` | Semantic search |
| GET | `/api/memory/stats` | Get statistics |
| GET | `/api/memory/progressive-context` | Get 3-block context |
| POST | `/api/memory/save-learning` | Save learning |
| GET | `/api/memory/golden-standards` | List golden standards |
| POST | `/api/memory/promote` | Promote to canonical |
| DELETE | `/api/memory/episode/{id}` | Delete episode |

#### Orchestration
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/orchestration/subagent` | Spawn subagent |
| POST | `/api/orchestration/parallel` | Parallel execution |
| POST | `/api/orchestration/maker-checker` | Verification pattern |
| WS | `/api/orchestration/roundtable` | Multi-agent discussion |

#### Admin
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/admin/clients` | List clients |
| POST | `/api/admin/clients/{name}/disable` | Disable client |
| DELETE | `/api/admin/clients/{name}/disable` | Enable client |
| GET | `/api/admin/blocked-requests` | Get blocked log |

#### Analytics
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/analytics/costs` | Cost aggregation |
| GET | `/api/analytics/truncations` | Truncation metrics |
| GET | `/api/feedback/stats` | Feedback statistics |

### 3.4 Memory System

#### 3-Block Progressive Disclosure

| Block | Content | Token Budget | Injection |
|-------|---------|--------------|-----------|
| **Mandates** | Golden standards (confidence=100) | ~250 tokens | `[M:uuid8] content` |
| **Guardrails** | Gotchas, warnings, pitfalls | ~150 tokens | `[G:uuid8] content` |
| **Reference** | Patterns, workflows, standards | ~100 tokens | Bullet list |

#### Memory Scopes
```
GLOBAL → System-wide learnings
PROJECT → Project-specific (project-{id})
TASK → Active task state (task-{id}, ephemeral)
```

#### Memory Categories
```
coding_standard, troubleshooting_guide, system_design, operational_context, domain_knowledge, active_state
```

#### Confidence Levels
- 100 = Golden standard (always inject as Mandate)
- 90+ = Canonical (high confidence)
- 70-89 = Provisional (needs validation)
- <70 = Experimental

#### Usage Tracking
```
loaded_count: Times injected into context
referenced_count: Times cited by LLM ([M:uuid8])
success_count: Times associated with positive feedback
utility_score: success_count / referenced_count
```

### 3.5 Agents

#### Seeded Agents

| Slug | Primary Model | Fallback | Escalation | Purpose |
|------|---------------|----------|------------|---------|
| `coder` | claude-sonnet-4-5 | gemini-3-flash | claude-opus-4-5 | Implementation |
| `planner` | claude-sonnet-4-5 | gemini-3-pro | claude-opus-4-5 | Planning |
| `reviewer` | claude-opus-4-5 | gemini-3-pro | - | Code review |
| `fixer` | claude-sonnet-4-5 | gemini-3-flash | claude-opus-4-5 | Debugging |
| `worker` | gemini-3-flash | claude-haiku-4-5 | claude-sonnet-4-5 | Quick fixes |
| `supervisor` | claude-sonnet-4-5 | gemini-3-pro | claude-opus-4-5 | Complex analysis |
| `auditor` | gemini-3-pro | claude-sonnet-4-5 | - | Fix verification |
| `summarizer` | gemini-3-flash | claude-haiku-4-5 | - | Summarization |
| `analyst` | claude-sonnet-4-5 | gemini-3-pro | - | Architecture |
| `extractor` | gemini-3-flash | claude-haiku-4-5 | - | Data extraction |

#### Agent Schema
```python
{
  slug: str,          # Unique identifier (a-z0-9-)
  name: str,          # Display name
  system_prompt: str, # Base prompt
  primary_model_id: str,
  fallback_models: list[str],
  escalation_model_id: str | None,
  mandate_tags: list[str],  # Tags for memory injection
  temperature: float,       # 0.0-2.0
  max_tokens: int | None,
  is_active: bool,
  version: int
}
```

### 3.6 UI Pages

| URL | Component | Features |
|-----|-----------|----------|
| `/dashboard` | Dashboard | KPI cards, cost charts, provider health, feedback stats |
| `/chat` | Chat | Single/Roundtable mode, memory toggle, coding agent mode |
| `/agents` | Agents | Agent list, metrics, CRUD, version history |
| `/memory` | Memory | Episode browser, 6 categories, golden standards, bulk delete |
| `/sessions` | Sessions | Session list, message history, token breakdown, cost |
| `/admin` | Admin | Kill switch controls, blocked requests log |

#### Chat Modes
- **Single**: 1-on-1 with model selection (5 models)
- **Roundtable**: 2-4 models deliberate sequentially (volley pattern)
- **Coding Agent**: File read/write/bash with working directory

#### Kill Switch Hierarchy
```
1. ClientPurposeControl (most specific)
2. ClientControl
3. PurposeControl (least specific)
```

### 3.7 Error Handling

#### Provider Errors
- Fallback chain: Primary → Fallback models in order
- Circuit breaker: Opens after consecutive failures
- States: closed, half_open, open

#### Kill Switch Response
```json
{
  "error": "client_disabled",
  "message": "Client 'summitflow' is disabled",
  "retry_after": -1,
  "contact": "Contact admin to re-enable"
}
```

#### Stream Cancellation
- **WebSocket**: Send `{type: "cancel"}`
- **REST**: POST `/sessions/{id}/cancel`
- **Registry**: Redis-backed for cross-instance cancellation

#### Session Timeouts
| Type | Timeout |
|------|---------|
| Completion | 30 min |
| Chat | 24 hours |
| Roundtable | 24 hours |
| Image Generation | 2 hours |
| Agent | 24 hours |

### 3.8 Deployment

#### Systemd Services
| Service | Port | Command |
|---------|------|---------|
| `agent-hub-backend` | 8003 | `uvicorn app.main:app --host 0.0.0.0 --port 8003` |
| `agent-hub-frontend` | 3003 | `npm run start -- --hostname 0.0.0.0 --port 3003` |
| `agent-hub-celery` | - | `celery -A app.celery_app worker --concurrency=2` |
| `neo4j` | 7687 | Neo4j Community 2025.12.1 |

#### Environment Variables
```
AGENT_HUB_DB_URL=postgresql://agent_hub_app:PASSWORD@localhost:5432/agent_hub
AGENT_HUB_REDIS_URL=redis://localhost:6379/2
AGENT_HUB_ENCRYPTION_KEY=<44-char Fernet key>
NEO4J_URI=bolt://localhost:7687
```

#### Redis Configuration
- **Database**: 2 (separate from SummitFlow)
- **Cache TTL**: Agent configs 5 min, search results 30s

---

## 4. Integration

### SummitFlow → Agent Hub Request

```python
# From summitflow/backend/app/services/agent_hub_client.py:247-257
response = client.complete(
    model=self.model,           # "agent:coder", "claude-sonnet-4-5"
    messages=messages,
    max_tokens=max_tokens,
    temperature=temperature,
    project_id=self.project_id, # "summitflow" - memory scope
    session_id=session_id,      # Continue existing session
    purpose=purpose,            # "code_generation", "task_enrichment"
    external_id=task_id,        # Links to task for cost tracking
    enable_caching=True,
)
```

### Agent Hub Response

```python
{
    "content": "...",
    "model": "claude-sonnet-4-5",
    "session_id": "...",
    "usage": {
        "input_tokens": 1234,
        "output_tokens": 567
    },
    "memory_facts_injected": 12,
    "memory_uuids": "uuid1,uuid2,uuid3"  # For feedback attribution
}
```

### Key Integration Parameters

| Parameter | Purpose | Used By |
|-----------|---------|---------|
| `project_id` | Memory scope | Agent Hub memory queries |
| `external_id` | Cost aggregation | Agent Hub cost tracking |
| `purpose` | Usage categorization | Kill switch, analytics |
| `session_id` | Conversation continuity | Agent Hub session management |

### Memory Flow

```
1. SummitFlow calls Agent Hub with project_id + external_id
2. Agent Hub queries Neo4j for relevant episodes (project scope)
3. Agent Hub injects 3-block context into system prompt
4. LLM generates response
5. Agent Hub extracts citations ([M:uuid8]) from response
6. Agent Hub tracks usage (loaded_count, referenced_count)
7. Session linked via external_id for cost aggregation
```

---

## 5. Live System State

### Active Databases

| Database | Size | Tables | Recent Activity |
|----------|------|--------|-----------------|
| `summitflow` | ~112 MB | 28 | 3 commits in 8h |
| `agent_hub` | ~2 MB | 12 | 9 agents seeded |
| Neo4j | - | Graphiti | 126 episodes |

### Registered Projects

| Project | Autonomous | Purpose |
|---------|------------|---------|
| `summitflow` | Enabled | Main platform |
| `monkey-fight` | Enabled (ideas) | Game project |
| `portfolio-ai` | Disabled | Financial app |

### Memory Statistics

```
Total Learnings: 126
By Category:
  - coding_standard: 89
  - system_design: 25
  - operational_context: 8
  - troubleshooting_guide: 3
  - domain_knowledge: 1
Scope: Global (126) + Project (35)
```

### Running Services

| Service | PID | Memory | Port |
|---------|-----|--------|------|
| SummitFlow Backend | 1790744 | 142 MB | 8001 |
| SummitFlow Celery | 1790801 | 118 MB | - |
| Agent Hub Backend | 1811312 | 313 MB | 8003 |
| Neo4j | 1811156 | - | 7687 |
| PostgreSQL | 1065 | - | 5432 |
| Redis | 1182 | - | 6379 |

### Recent Backups

| Project | File | Size | Verified |
|---------|------|------|----------|
| summitflow | summitflow-20260120-182551.tar.gz | 112 MB | 8,692 files |
| agent-hub | agent-hub-20260120-182545.tar.gz | 43 MB | 5,712 files |

---

## 6. Key File Paths

### SummitFlow Backend

| Path | Purpose |
|------|---------|
| `/home/kasadis/summitflow/backend/app/main.py` | FastAPI entry |
| `/home/kasadis/summitflow/backend/app/celery_app.py` | Celery config |
| `/home/kasadis/summitflow/backend/app/storage/schema.py` | DB schema |
| `/home/kasadis/summitflow/backend/app/services/orchestrator.py` | Task orchestration |
| `/home/kasadis/summitflow/backend/app/services/worktree_manager.py` | Git isolation |
| `/home/kasadis/summitflow/backend/app/services/agent_hub_client.py` | Agent Hub integration |
| `/home/kasadis/summitflow/backend/app/services/evidence_manager.py` | Evidence capture |
| `/home/kasadis/summitflow/backend/app/tasks/autonomous/execution.py` | Autonomous pickup |
| `/home/kasadis/summitflow/backend/migrations/` | 85 migrations |

### SummitFlow Frontend

| Path | Purpose |
|------|---------|
| `/home/kasadis/summitflow/frontend/app/page.tsx` | Dashboard |
| `/home/kasadis/summitflow/frontend/app/projects/[id]/design/page.tsx` | Design page |
| `/home/kasadis/summitflow/frontend/components/kanban/` | Kanban board |
| `/home/kasadis/summitflow/frontend/components/explorer/` | Explorer UI |
| `/home/kasadis/summitflow/frontend/lib/api/` | API clients |

### Agent Hub Backend

| Path | Purpose |
|------|---------|
| `/home/kasadis/agent-hub/backend/app/main.py` | FastAPI entry |
| `/home/kasadis/agent-hub/backend/app/config.py` | Settings |
| `/home/kasadis/agent-hub/backend/app/models.py` | DB models |
| `/home/kasadis/agent-hub/backend/app/api/complete.py` | Completion API |
| `/home/kasadis/agent-hub/backend/app/api/memory.py` | Memory API |
| `/home/kasadis/agent-hub/backend/app/api/agents.py` | Agents API |
| `/home/kasadis/agent-hub/backend/app/services/memory/context_injector.py` | Memory injection |
| `/home/kasadis/agent-hub/backend/app/services/memory/service.py` | Memory service |
| `/home/kasadis/agent-hub/backend/app/services/memory/graphiti_client.py` | Neo4j client |
| `/home/kasadis/agent-hub/backend/app/middleware/kill_switch.py` | Kill switch |

### Agent Hub Frontend

| Path | Purpose |
|------|---------|
| `/home/kasadis/agent-hub/frontend/src/app/dashboard/page.tsx` | Dashboard |
| `/home/kasadis/agent-hub/frontend/src/app/chat/page.tsx` | Chat UI |
| `/home/kasadis/agent-hub/frontend/src/app/agents/page.tsx` | Agents list |
| `/home/kasadis/agent-hub/frontend/src/app/memory/page.tsx` | Memory browser |
| `/home/kasadis/agent-hub/frontend/src/app/admin/page.tsx` | Admin panel |

### Configuration

| Path | Purpose |
|------|---------|
| `~/.env.local` | Master environment config |
| `/home/kasadis/summitflow/scripts/systemd/` | Systemd services |
| `/home/kasadis/agent-hub/scripts/systemd/` | Systemd services |
| `/home/kasadis/neo4j-community-2025.12.1/conf/neo4j.conf` | Neo4j config |
| `~/.cloudflared/config.yml` | Cloudflare tunnels |

### Data Directories

| Path | Purpose |
|------|---------|
| `/home/kasadis/summitflow/data/projects/` | Evidence storage |
| `/tmp/summitflow-worktrees/` | Active worktrees |
| `/home/kasadis/summitflow/backups/` | Local backups |
| `/home/kasadis/summitflow/tasks/` | Task definitions |

---

## Quick Reference

### Start All Services
```bash
# SummitFlow
systemctl --user start summitflow-backend summitflow-frontend summitflow-celery summitflow-celery-beat

# Agent Hub
systemctl --user start agent-hub-backend agent-hub-frontend agent-hub-celery neo4j
```

### Health Checks
```bash
curl http://localhost:8001/health          # SummitFlow backend
curl http://localhost:8003/health          # Agent Hub backend
curl http://localhost:8003/api/memory/stats # Memory system
```

### Common CLI Commands
```bash
st list                          # List tasks
st ready                         # Mark task ready
st backup create                 # Create backup
st autonomous status             # Check autonomous settings
```

### Memory API Quick Reference
```bash
# Get progressive context
curl "http://localhost:8003/api/memory/progressive-context?query=database"

# Save learning
curl -X POST "http://localhost:8003/api/memory/save-learning" \
  -H "Content-Type: application/json" \
  -d '{"content": "...", "category": "coding_standard", "confidence": 85}'
```

---

*Generated: 2026-01-20 | Confidence: 99%*
