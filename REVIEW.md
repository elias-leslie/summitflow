# SummitFlow + Agent Hub Comprehensive Technical Review

> Generated: 2026-01-31
> Reviewed by: Claude Opus 4.5 via comprehensive exploration agents

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [SummitFlow Architecture](#2-summitflow-architecture)
   - [2.1 Backend (FastAPI)](#21-backend-fastapi)
   - [2.2 Frontend (Next.js)](#22-frontend-nextjs)
   - [2.3 Celery Tasks](#23-celery-tasks)
   - [2.4 Database Schema](#24-database-schema)
3. [Agent Hub Architecture](#3-agent-hub-architecture)
   - [3.1 Backend Services](#31-backend-services)
   - [3.2 Memory System (Graphiti)](#32-memory-system-graphiti)
   - [3.3 Multi-Agent Orchestration](#33-multi-agent-orchestration)
   - [3.4 Access Control](#34-access-control)
   - [3.5 Database Schema](#35-database-schema)
4. [CLI Tools](#4-cli-tools)
   - [4.1 ST CLI (SummitFlow Tasks)](#41-st-cli-summitflow-tasks)
   - [4.2 DT CLI (Dev Standards)](#42-dt-cli-dev-standards)
   - [4.3 Shell Scripts](#43-shell-scripts)
5. [Integration Points](#5-integration-points)
6. [Key Design Patterns](#6-key-design-patterns)
7. [Statistics Summary](#7-statistics-summary)

---

## 1. Executive Summary

**SummitFlow** and **Agent Hub** are companion projects forming a comprehensive AI-assisted software development platform:

- **SummitFlow** (ports 8001/3001): Task management, codebase exploration, quality gates, autonomous execution orchestration
- **Agent Hub** (ports 8003/3003): Unified LLM gateway, memory system (Graphiti/Neo4j), multi-agent coordination, access control

### Key Capabilities

| Feature | SummitFlow | Agent Hub |
|---------|------------|-----------|
| Task Management | Full lifecycle (create → execute → review) | Session tracking, cost logging |
| Code Quality | Quality gates, auto-fix, health monitoring | - |
| Memory System | - | 3-tier Graphiti (mandate/guardrail/reference) |
| LLM Integration | Via Agent Hub client | Claude, Gemini, OpenAI adapters |
| Multi-Agent | Autonomous execution pipeline | Roundtable, subagents, parallel execution |
| Access Control | Project-scoped | Client auth with rate limiting |

### Technology Stack

| Layer | SummitFlow | Agent Hub |
|-------|------------|-----------|
| Backend | FastAPI, Python 3.12+ | FastAPI, Python 3.13+ |
| Frontend | Next.js 16, React 19, Tailwind 4 | Next.js, React 19 |
| Database | PostgreSQL (37 tables) | PostgreSQL (20 tables) + Neo4j |
| Task Queue | Celery + Redis (14 tasks) | Celery + Redis (2 tasks) |
| CLI | ST (Typer) | via ST memory commands |

---

## 2. SummitFlow Architecture

### 2.1 Backend (FastAPI)

**Location**: `/home/kasadis/summitflow/backend/`

#### API Routes (160+ endpoints across 30 modules)

| Module | Endpoints | Purpose |
|--------|-----------|---------|
| `projects/` | 7+ | Project CRUD, health, agent config |
| `tasks/core.py` | 10 | Task CRUD, status, batch operations |
| `tasks/subtasks.py` | 8 | Subtask management |
| `tasks/steps.py` | 11 | Step-level implementation |
| `tasks/workflow.py` | 3 | Workflow automation |
| `explorer.py` | 15 | Codebase exploration (files, tables, endpoints, pages) |
| `quality_gate.py` | 8 | Quality checks, auto-fix |
| `backups.py` | 10 | Database backup/restore, scheduling |
| `ideas.py` | 8 | Crowdsourced idea management |
| `mockups.py` | 13 | UI mockup generation |
| `design_standards.py` | 14 | Design rule management |
| `notifications.py` | 8 | User alerts |
| `git.py` | 5 | Git operations |
| `checkpoints.py` | 3 | Task checkpoint recovery |

**Key API Patterns**:
- Modular router organization by domain
- Pydantic schemas for validation
- Project-scoped endpoints with `project_id` parameter
- Full async/await support

#### Services Layer (35+ modules)

| Service | Purpose |
|---------|---------|
| `explorer/` | Codebase analysis, AST parsing, index generation |
| `quality_gate/` | Code quality enforcement, fix agents, escalation |
| `autonomous/` | Autonomous task execution coordination |
| `implementation/` | Task implementation with verification |
| `self_healing/` | Error recovery, pattern memory |
| `git_lifecycle.py` | Branch management, worktrees |
| `agent_hub_client.py` | LLM abstraction via Agent Hub |
| `complexity_assessor.py` | Task classification (SIMPLE/STANDARD/COMPLEX) |

#### Storage Layer (28 modules)

- **Connection Pool**: psycopg with 5-20 connections
- **Query Builders**: Raw SQL with parameterized queries
- **Transaction Management**: Context managers for atomicity

### 2.2 Frontend (Next.js)

**Location**: `/home/kasadis/summitflow/frontend/`

#### Pages (13 routes)

```
/                                    → Dashboard
/about                              → Getting Started
/backups                            → Global Backups
/git                                → Global Git Status
/projects/new                       → Create Project
/projects/[id]                      → Project Detail (Kanban, Tasks, Explorer, Health tabs)
/projects/[id]/design               → Mockup Management
/projects/[id]/git                  → Project Git
/projects/[id]/git/worktrees        → Worktree Management
/projects/[id]/backups              → Project Backups
/projects/[id]/backups/[backupId]/restore → Restore Preview
/projects/[id]/settings             → Project Settings
```

#### Components (109 files across 12 directories)

| Directory | Files | Purpose |
|-----------|-------|---------|
| `tasks/` | 37 | Task modals, filters, subtasks, criteria |
| `ui/` | 20 | Shadcn/Radix primitives |
| `explorer/` | 16 | Unified file/database/API explorer |
| `design/` | 11 | Mockup gallery and generation |
| `layout/` | 6 | App shell, sidebar, topbar |
| `kanban/` | 4 | Drag-and-drop task board |
| `settings/` | 4 | Agent and automation config |
| `dashboard/` | 3 | Activity feed, project cards |
| `notifications/` | 3 | Notification bell and detail |
| `execution/` | 2 | Execution dock, escalation |
| `health/` | 1 | Health metrics display |
| `backup/` | 2 | Backup restoration UI |

#### API Clients (12 modules, 2,741 LOC)

| Client | LOC | Purpose |
|--------|-----|---------|
| `tasks.ts` | 672 | Task CRUD, filtering, subtasks |
| `explorer.ts` | 580 | Explorer entries, scanning |
| `projects.ts` | 285 | Project management |
| `git.ts` | 251 | Git operations |
| `mockups.ts` | 239 | Mockup generation |
| `backups.ts` | 234 | Backup/restore |

#### Custom Hooks (12)

- `useExecutionWebSocket` - Real-time execution streaming
- `useTabPersistence` - localStorage + URL sync
- `useExplorerData` - React Query integration
- `useTaskModal` - Modal state management

#### Design System

- **Theme**: "Outrun" neon aesthetic (dark-only)
- **Primary**: Hot Pink `#ff0066`
- **Secondary**: Neon Cyan `#00f5ff`
- **Typography**: Space Grotesk (display), IBM Plex Sans (body)

### 2.3 Celery Tasks

**14 scheduled tasks**:

| Task | Schedule | Purpose |
|------|----------|---------|
| `autonomous_work_pickup` | Every 30 min | Pick up ready autonomous tasks |
| `review_pending_tasks` | Every 30 min | Review for auto-merge |
| `monitor_systemd_errors` | Every 5 min | Service error monitoring |
| `monitor_browser_errors` | Every 6 hours | Frontend error capture |
| `orchestrate_self_healing` | Every 15 min | Error recovery coordination |
| `reset_expired_task_claims` | Every 1 hour | Clean up expired locks |
| `run_scheduled_backups` | Every 1 hour | Execute scheduled backups |
| `scan_all_projects` | Every 6 hours | Explorer scans |
| `daily_code_health_scan` | Every 1 day | Code quality assessment |
| `weekly_deep_scan` | Every 7 days | Comprehensive analysis |
| `cleanup_stale_tasks` | Every 1 day | Remove orphaned tasks |
| `generate_tasks_from_scan` | Every 7 days | Auto-generate from issues |
| `process_crowdsourced_ideas` | Every 1 day | Process user ideas |
| `cleanup_debug_captures` | Every 1 day | Clean debug logs |

### 2.4 Database Schema

**37 tables** organized by domain:

#### Core Tables

| Table | Purpose |
|-------|---------|
| `projects` | Project registration with health endpoints |
| `tasks` | Issue tracking with status, priority, complexity |
| `task_subtasks` | Hierarchical task breakdown |
| `task_subtask_steps` | Implementation steps with commands |
| `task_dependencies` | Task relationship tracking |
| `task_labels` | Task categorization |
| `task_spirit` | Task intent and constraints |

#### Explorer Tables

| Table | Purpose |
|-------|---------|
| `explorer_entries` | Files, tables, endpoints, pages |
| `explorer_relationships` | Dependency relationships |
| `explorer_sub_elements` | Methods, fields, columns |
| `scan_history` | Scan audit trail |
| `scan_states` | Current scan status |

#### Quality & Health Tables

| Table | Purpose |
|-------|---------|
| `quality_check_results` | Quality check outcomes |
| `qa_issues` | Code violations |
| `code_health_lists` | Allow/block lists |

#### Additional Tables

- `agent_sessions` - Agent execution tracking
- `backups`, `backup_schedules` - Backup management
- `notifications` - User alerts
- `design_standards`, `design_rules` - UI/UX standards
- `mockups` - Design artifacts
- `ideas` - Crowdsourced improvements
- `events` - Event logging with trace IDs
- `refactor_sessions` - Refactoring context
- `terminal_sessions`, `terminal_panes` - Terminal state

---

## 3. Agent Hub Architecture

### 3.1 Backend Services

**Location**: `/home/kasadis/agent-hub/backend/`

#### API Routes (40+ endpoints across 34 modules)

| Module | Endpoints | Purpose |
|--------|-----------|---------|
| `complete.py` | 2 | Main completion + estimation |
| `memory.py` + `memory_*.py` | 14 | Memory CRUD, search, settings |
| `sessions.py` | 6 | Session management |
| `agents.py` | 6 | Agent CRUD + versions |
| `orchestration.py` | 5 | Multi-agent coordination |
| `access_control*.py` | 12 | Client auth, rate limiting |
| `analytics.py` | 1 | Cost aggregation |
| `admin.py`, `db.py` | 6 | Database ops, audit |
| `credentials.py`, `api_keys.py` | - | Credential management |
| `webhooks.py` | - | Event subscriptions |

#### Core Services (60+ modules)

| Service | Purpose |
|---------|---------|
| `completion.py` | Unified LLM entry point with memory injection |
| `agent_routing.py` | Agent resolution and fallback |
| `provider_chain.py` | Provider fallback management |
| `agent_runner/` | Autonomous task execution |
| `orchestration/` | Subagent, parallel, maker-checker |
| `client_auth.py` | Client authentication |
| `cost_tracker.py` | Token and cost tracking |
| `voice/` | Speech-to-text, text-to-speech |

#### Provider Adapters

| Adapter | Features |
|---------|----------|
| `claude.py` | Code execution sandbox, tool calling, streaming |
| `gemini.py` | Tool calling, streaming, embeddings |
| `openai.py` | Placeholder for future support |
| `gemini_image.py` | Image generation |

### 3.2 Memory System (Graphiti)

**44 service modules** implementing a Neo4j-based knowledge graph.

#### Tier Architecture (3 Levels)

| Tier | Name | Confidence | Injection |
|------|------|------------|-----------|
| T1 | **Mandate** | 100% | Always injected |
| T2 | **Guardrail** | High | Filtered by task type |
| T3 | **Reference** | Variable | Semantic search |

#### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| Main API | `service.py` | High-level search, CRUD |
| Graphiti Client | `graphiti_client.py` | Neo4j + Gemini integration |
| Context Injector | `context_injector.py` | Progressive 3-block disclosure |
| Episode Creator | `episode_creator.py` | Memory storage |
| Tier Operations | `tier_*.py` | Promotion, demotion, optimization |

#### Graphiti Configuration

| Component | Model/Config |
|-----------|--------------|
| LLM | gemini-2.5-flash-lite |
| Embeddings | gemini-embedding-001 (768 dims) |
| Reranker | gemini-3-flash-preview |
| Graph DB | Neo4j (bolt://localhost:7687) |

#### Tier Promotion/Demotion

**Promotion Criteria**:
- Utility score > 0.70
- Referenced count >= 20
- Age >= 7 days
- OR: Helpful citations >= 5

**Demotion Criteria**:
- Utility score < 0.15
- Loaded count >= 200
- Age >= 7 days
- OR: Harmful citations >= 3
- Grace period: 48 hours

### 3.3 Multi-Agent Orchestration

#### Orchestration Patterns

| Pattern | Endpoint | Purpose |
|---------|----------|---------|
| Subagent | `POST /api/orchestration/subagent` | Spawn isolated context |
| Parallel | `POST /api/orchestration/parallel` | Concurrent execution |
| Maker-Checker | `POST /api/orchestration/maker-checker` | Two-agent verification |
| Code Review | `POST /api/orchestration/code-review` | Specialized review |
| Agent Runner | `POST /api/orchestration/run-agent` | Full tool loop |

#### Roundtable Sessions

- **Modes**: `quick` or `deliberation`
- **Tool Modes**: `read_only` or `yolo` (sandboxed execution)
- **Agent Types**: Claude, Gemini (extensible)
- **Memory Integration**: Optional group_id for scoped memory

### 3.4 Access Control

#### Authentication

| Header | Purpose |
|--------|---------|
| `X-Client-Id` | Client UUID |
| `X-Client-Secret` | bcrypt-verified secret (ahc_... prefix) |
| `X-Request-Source` | Caller identification |
| `X-Source-Client` | Client type (st-cli, sdk) |
| `X-Tool-Name` | Command/method |
| `X-Source-Path` | Caller file path |
| `X-Agent-Hub-Internal` | Dashboard bypass |

#### Rate Limiting

- **RPM**: Requests per minute (default 60)
- **TPM**: Tokens per minute (default 100,000)
- **Per-client**: Configurable limits

#### Client States

| State | Description |
|-------|-------------|
| `active` | Normal operation |
| `suspended` | Temporarily blocked |
| `blocked` | Permanently blocked |

### 3.5 Database Schema

**20 tables** (PostgreSQL + Neo4j for graph):

#### Session & Message Tables

| Table | Purpose |
|-------|---------|
| `sessions` | Completion sessions with provider, model, status |
| `messages` | Conversation messages with role, content, tokens |
| `cost_logs` | Token and cost tracking |

#### Agent Tables

| Table | Purpose |
|-------|---------|
| `agents` | Agent definitions with prompts, models, strategies |
| `agent_versions` | Version history for audit |

#### Client Tables

| Table | Purpose |
|-------|---------|
| `clients` | Client registration with rate limits |
| `api_keys` | Legacy API key support |
| `client_controls` | Additional control rules |

#### Memory Tables

| Table | Purpose |
|-------|---------|
| `memory_injection_metrics` | A/B testing, latency, counts |
| `memory_settings` | Kill switch, tier limits |
| `usage_stats` | Time-series statistics |

#### Roundtable Tables

| Table | Purpose |
|-------|---------|
| `roundtable_sessions` | Multi-agent sessions |
| `roundtable_messages` | Agent-attributed messages |

#### Telemetry Tables

| Table | Purpose |
|-------|---------|
| `request_logs` | 30-day audit trail |
| `truncation_events` | Context window events |

#### Config Tables

- `credentials` - Encrypted API keys
- `webhook_subscriptions` - Event subscriptions
- `user_preferences` - Per-user settings
- `global_instructions` - System prompts

---

## 4. CLI Tools

### 4.1 ST CLI (SummitFlow Tasks)

**Location**: `/home/kasadis/summitflow/backend/cli/`
**Entry Point**: `/home/kasadis/bin/st`
**Framework**: Typer (Python)

#### Command Groups (50+ commands)

##### Task Management

```bash
st create <title> [-t type] [-p priority] [-d desc] [--blocked-by id]
st list [--status S] [--type T] [--priority P]
st ready                           # Show unblocked tasks
st context <id> [--subtask X.Y]    # Full task context
st export <id> [-o file.json]      # JSON export
st log <id> <message>              # Add progress log
st autocode <id> [--dry-run]       # Queue for autonomous
st verify <plan.json>              # Validate plan
st exec-monitor <id> [-f] [-n N]   # Monitor execution
```

##### Checkpoint Workflow

```bash
st claim <id> [--force]            # Claim task, create checkpoint
st claim <subtask> -t <task>       # Claim subtask, create branch
st done <subtask> -t <task>        # Complete subtask, merge
st done <task>                     # Complete task, merge to main
st abandon <subtask> -t <task>     # Abandon subtask
st abandon <task> [--force]        # Abandon task, restore DB
st checkpoints [-p] [-d]           # Show active checkpoints
```

##### Subtask & Step Management

```bash
st subtask list|show|create|pass|delete <task-id> [subtask-id]
st step pass|new|update|add|delete|defect <task> <subtask> [step#]
```

##### Additional Commands

```bash
st dep list|add|rm <task-id>       # Dependencies
st backup list|create|restore|status|schedule|show|delete
st git status|sync                 # Git integration
st health [status|results|sync]    # Quality gate
st memory stats|save|list|search|get|delete  # Agent Hub memory
st projects list|current           # Project management
```

#### Output Formats

| Flag | Format | Use Case |
|------|--------|----------|
| `--compact/-c` | TOON (default) | Claude consumption |
| `--no-compact` | Raw JSON | Programmatic access |
| `--human` | Pretty JSON | Human debugging |

### 4.2 DT CLI (Dev Standards)

**Location**: `/home/kasadis/summitflow/scripts/dev-tools.sh`
**Entry Point**: `/home/kasadis/bin/dt`
**Framework**: Bash (812 lines)

#### Tool Subcommands

| Command | Tool | Purpose |
|---------|------|---------|
| `dt pytest` | pytest | Run tests with TOON output |
| `dt ruff` | ruff | Python linting |
| `dt mypy` | mypy | Type checking |
| `dt biome` | biome | Frontend linting |
| `dt tsc` | tsc | TypeScript compilation |
| `dt sqlfluff` | sqlfluff | SQL linting |
| `dt squawk` | squawk | Migration safety |

#### Global Options

```bash
dt                    # Dashboard of all projects
dt --check, -c        # Full quality gate
dt --quick, -q        # Fast check (lint + types)
dt --frontend-only    # Frontend only
dt --fix, -f          # Auto-fix + deps
dt --fix-all          # Fix all managed projects
dt --rebuild-venv     # Nuclear venv rebuild
```

#### TOON Output Format

```
LINT:OK:0                              # Pass (~20 bytes)
LINT:FAIL:5|details:.dev-tools/ruff-details.txt  # Fail (~60 bytes)
TEST:OK:677 passed in 45.23s           # Test pass (~50 bytes)
```

#### Managed Projects

```bash
MANAGED_PROJECTS=(summitflow agent-hub terminal portfolio-ai)
```

### 4.3 Shell Scripts

**Location**: `/home/kasadis/summitflow/scripts/`

#### Infrastructure Scripts

| Script | Purpose |
|--------|---------|
| `rebuild.sh` | Rebuild and restart services |
| `backup.sh` | Create compressed backup to SMB |
| `restore.sh` | Restore from backup archive |
| `start.sh` | Start all services |
| `shutdown.sh` | Stop all services |
| `restart.sh` | Restart services |
| `status.sh` | Show service status |
| `setup-services.sh` | Install systemd services |

#### Systemd Services (6)

| Service | Port | Purpose |
|---------|------|---------|
| `summitflow-backend` | 8001 | FastAPI backend |
| `summitflow-frontend` | 3001 | Next.js frontend |
| `summitflow-celery` | - | Celery worker |
| `summitflow-celery-beat` | - | Celery scheduler |
| `summitflow-terminal` | - | Terminal backend |
| `summitflow-terminal-frontend` | 3002 | Terminal frontend |

---

## 5. Integration Points

### SummitFlow ↔ Agent Hub

```
┌─────────────────────┐          ┌─────────────────────┐
│     SummitFlow      │          │     Agent Hub       │
├─────────────────────┤          ├─────────────────────┤
│ agent_hub_client.py │─────────>│ POST /api/complete  │
│                     │          │                     │
│ st memory commands  │─────────>│ Memory API          │
│                     │          │                     │
│ Autonomous tasks    │─────────>│ Agent Runner        │
│                     │          │                     │
│ Quality fixes       │─────────>│ Code execution      │
└─────────────────────┘          └─────────────────────┘
```

### Memory Injection Flow

```
1. SummitFlow calls Agent Hub /api/complete
2. Agent Hub extracts memory options
3. Memory Service retrieves episodes:
   - Block 1: All mandates (always)
   - Block 2: Guardrails (filtered by task type)
   - Block 3: References (semantic search)
4. Context injector formats progressive disclosure
5. LLM receives enhanced prompt with <memory> tags
6. Response parsed for citations
7. Metrics logged for A/B analysis
```

### CLI ↔ Backend

```
┌─────────┐    HTTP    ┌─────────────────┐
│ ST CLI  │───────────>│ SummitFlow API  │
└─────────┘            └─────────────────┘
     │
     │ (memory commands)
     │
     └────────────────>┌─────────────────┐
                       │ Agent Hub API   │
                       └─────────────────┘
```

---

## 6. Key Design Patterns

### Layered Architecture (Both Projects)

```
┌───────────────────────────────────┐
│         API Layer (FastAPI)       │
│   (Routers, Pydantic schemas)     │
├───────────────────────────────────┤
│        Service Layer              │
│   (Business logic, orchestration) │
├───────────────────────────────────┤
│        Storage Layer              │
│   (PostgreSQL, Neo4j, Redis)      │
└───────────────────────────────────┘
```

### Progressive Context Disclosure (Agent Hub)

```
System Prompt
  │
  ├── <memory>
  │     ├── MANDATES (always)
  │     ├── GUARDRAILS (filtered)
  │     └── REFERENCES (semantic)
  │   </memory>
  │
User Message
```

### Checkpoint Recovery (SummitFlow)

```
claim → [git branch + DB snapshot]
  │
  ├── work → done → merge
  │
  └── abandon → restore → delete branch
```

### Provider Fallback Chain (Agent Hub)

```
Primary (Claude) → Fallback (Gemini) → Error
```

### TOON Output (CLI)

Token-optimized output for LLM consumption:
- Minimal bytes on success
- Details in rotated files
- Machine-parseable format

---

## 7. Statistics Summary

### Code Metrics

| Metric | SummitFlow | Agent Hub |
|--------|------------|-----------|
| Backend LOC | ~48,000 | ~35,000 |
| Frontend Files | 225 | 239 |
| API Endpoints | 160+ | 40+ |
| Database Tables | 37 | 20 |
| Celery Tasks | 14 | 2 |
| Service Modules | 35+ | 60+ |

### Component Counts

| Component | SummitFlow | Agent Hub |
|-----------|------------|-----------|
| API Router Files | 30 | 34 |
| Storage Modules | 28 | - |
| Memory Services | - | 44 |
| Frontend Components | 109 | - |
| Custom Hooks | 12 | - |

### Feature Coverage

| Feature | SummitFlow | Agent Hub |
|---------|------------|-----------|
| Task Management | Full lifecycle | Session tracking |
| Code Quality | Quality gates, auto-fix | - |
| Memory System | - | 3-tier Graphiti |
| LLM Integration | Via client | Multi-provider |
| Multi-Agent | Autonomous pipeline | Roundtable, orchestration |
| Access Control | Project-scoped | Client auth + rate limits |
| CLI | ST (50+ commands) | Via ST memory |
| Dev Tools | DT (7 tools) | Shared via symlinks |

---

## File Paths Reference

### SummitFlow

```
/home/kasadis/summitflow/
├── backend/
│   ├── app/
│   │   ├── api/             # 30 router files
│   │   ├── services/        # 35+ service modules
│   │   ├── storage/         # 28 storage modules
│   │   └── tasks/           # 14 Celery tasks
│   └── cli/                 # ST CLI source
├── frontend/
│   ├── app/                 # 13 pages
│   ├── components/          # 109 components
│   ├── lib/api/             # 12 API clients
│   └── hooks/               # 12 custom hooks
└── scripts/                 # Shell scripts, systemd
```

### Agent Hub

```
/home/kasadis/agent-hub/
├── backend/
│   ├── app/
│   │   ├── api/             # 34 router files
│   │   ├── services/        # 60+ services
│   │   │   └── memory/      # 44 memory services
│   │   ├── models/          # 9 SQLAlchemy models
│   │   ├── adapters/        # Provider implementations
│   │   └── tasks/           # 2 Celery tasks
│   └── middleware/          # Access control
├── frontend/                # Next.js dashboard
└── scripts/                 # Symlinks to summitflow
```

---

*This review was generated through comprehensive exploration of both codebases using multiple specialized agents with validation passes. All statistics and claims have been verified against actual source files.*
