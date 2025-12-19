# Project Comparison Report

> **Auto Claude** vs **SummitFlow**
> Generated: 2025-12-18T19:30:00Z

---

## Executive Summary

| Dimension | Auto Claude | SummitFlow | Winner |
|-----------|-------------|------------|--------|
| Identity & Maturity | Production, AGPL-3.0, Public | Alpha, Unlicensed, Private | Auto Claude |
| Architecture | 9 domain modules, facade pattern | 4 core modules, layered | Auto Claude |
| Frontend | Electron desktop, 15+ stores | Next.js web, TanStack Query | Auto Claude |
| Backend | CLI + SDK, file-based | FastAPI REST, PostgreSQL | Tie |
| Database | File + optional graph | PostgreSQL normalized | SummitFlow |
| AI/ML | 15+ agents, RAG, predictions | No built-in AI | **Auto Claude** |
| Testing | 48 test files, E2E | 3 test files, pytest only | Auto Claude |
| Security | 7 validators, 3-layer model | CORS, param queries | Auto Claude |
| DevOps | GitHub Actions CI | No CI/CD | Auto Claude |
| Code Quality | Pre-commit, 600 line max | Ruff, 1386 line max | Tie |
| Documentation | README, guides | CLAUDE.md, OpenAPI | Tie |
| Developer Experience | Electron hot reload, hooks | Next.js hot reload, scripts | Tie |
| Performance | Desktop optimized | Web with CDN | Tie |
| Community | Discord, contributing guide | Single developer, internal | Auto Claude |

**Overall Scores:** Auto Claude: **77/100** | SummitFlow: **58/100**

**Winner:** Depends on use case (see recommendations below)

---

## Summary

These are **fundamentally different products** despite surface similarities:

- **Auto Claude**: A production-ready autonomous coding framework with sophisticated multi-agent AI orchestration
- **SummitFlow**: An alpha-stage developer platform focused on project management and feature tracking tooling

Direct comparison is only meaningful when evaluating "AI-assisted development" approaches.

---

## Key Metrics

| Metric | Auto Claude | SummitFlow | Ratio |
|--------|-------------|------------|-------|
| Lines of Code | 162,628 | 21,537 | 7.5x |
| Files Analyzed | 928 | 111 | 8.4x |
| Direct Dependencies | 50 | 11 | 4.5x |
| Test Files | 48 | 3 | 16x |
| Setup Time | 15 min | 15 min | 1x |
| Contributors | 1 | 1 | 1x |

---

## Dimension Analysis

### 1. Identity & Market Position

| Aspect | Auto Claude | SummitFlow |
|--------|-------------|------------|
| Maturity | Production | Alpha |
| License | AGPL-3.0 (copyleft) | Unlicensed (private) |
| Distribution | Public GitHub, Electron app | Internal, web app |
| Community | Discord, CONTRIBUTING.md | Single developer |
| Tagline | "Build features, fix bugs, ship faster" | "AI-assisted development platform" |

**Analysis:** Auto Claude has clear market positioning with public presence and community support. SummitFlow is an internal alpha without distribution strategy.

---

### 2. Architecture

| Aspect | Auto Claude | SummitFlow |
|--------|-------------|------------|
| Style | Modular monolith | Modular monolith |
| Patterns | Clean, Repository, MVC, Facade, Strategy, Factory | Repository, MVC, Clean |
| API Style | CLI + Electron IPC (no REST) | REST API |
| State (Frontend) | Zustand (15+ stores) | TanStack React Query |
| State (Backend) | File-based + Graphiti graph | PostgreSQL + in-memory |

**Key Architectural Differences:**

1. **Auto Claude's Domain Modules (9):**
   - agents, analysis, context, merge, prediction, security, spec, qa, runners

2. **SummitFlow's Core Modules (4):**
   - api, services, storage, models

3. **Auto Claude** uses dual-layer memory (file + graph DB) and facade pattern for backward compatibility
4. **SummitFlow** uses traditional REST API with PostgreSQL persistence

---

### 3. Frontend

| Aspect | Auto Claude | SummitFlow |
|--------|-------------|------------|
| Platform | Electron 39.2.6 (desktop) | Next.js 15 (web) |
| React Version | 19.2.3 | 19.0.0 |
| Tailwind Version | 4.1.17 | 3.4.0 |
| State Management | Zustand (15+ stores) | TanStack Query |
| Routing | Custom sidebar | Next.js App Router |

**Auto Claude UI Features (unique):**
- 5-stage Kanban workflow (Planning → In Progress → AI Review → Human Review → Done)
- Terminal grid (2x3, expandable to 12)
- Task Creation Wizard with model/thinking level selection
- Reference image drag-drop (up to 10MB, max 10 images)
- AI-generated product roadmap with MoSCoW prioritization
- Insights (ChatGPT-style project conversations)
- Changelog with one-click GitHub releases

**SummitFlow UI Features (unique):**
- Unified Explorer (files, database, tasks, endpoints)
- Evidence capture with screenshot verification
- Vision/goals management
- Beads issue tracking integration

---

### 4. AI/ML Capabilities

| Aspect | Auto Claude | SummitFlow |
|--------|-------------|------------|
| Built-in AI | Yes (comprehensive) | No |
| LLM Providers | Anthropic, OpenAI, Google, local | None (external Claude Code) |
| Agent Types | 15+ across 4 categories | None |
| Extended Thinking | Yes (spec critic) | No |
| RAG | Yes (Graphiti) | No |
| Predictions | Yes (risk analysis) | No |
| Prompt Templates | 26 | 0 |

**Auto Claude Agent Categories:**

1. **Spec Creation (8 types):** Discovery, Requirements, Research, Context, Spec Writer, Spec Critic, Planner, Validation
2. **Implementation (3 types):** Coder, Coder Recovery, Followup Planner
3. **QA (3 types):** QA Reviewer, QA Fixer, Loop Orchestrator
4. **Analysis (4 types):** Ideation, Roadmap, Insights, Complexity Assessor

**SummitFlow's "AI-assisted" Approach:**
- External Claude Code integration via `.claude/` configuration
- Beads CLI for AI-friendly issue tracking
- No built-in LLM or agent orchestration

**Winner:** Auto Claude (overwhelming advantage)

---

### 5. Testing

| Aspect | Auto Claude | SummitFlow |
|--------|-------------|------------|
| Unit Tests | pytest (48 files) | pytest (3 files) |
| Integration | pytest (10 files) | None |
| E2E | Playwright (1 file) | None |
| Frontend Tests | Vitest | None |
| CI Automated | Yes | No |
| Coverage Metrics | Not reported | Not reported |

**Analysis:** Auto Claude has 16x more test files with E2E and frontend coverage. SummitFlow's testing is a critical gap.

---

### 6. Security

| Aspect | Auto Claude | SummitFlow |
|--------|-------------|------------|
| Authentication | OAuth (Claude Code) | None |
| Security Model | 3-layer (OS → Filesystem → Allowlist) | Framework defaults |
| Validators | 7 types (DB, FS, Git, Process, Secrets, Hooks, Registry) | None |
| Input Validation | Schema + validators | Pydantic |
| SQL Injection | ORM-based | Parameterized queries |
| Secrets Scanning | Yes (.secretsignore) | No |

**Auto Claude's 3-Layer Security:**
1. **OS Sandbox** - Bash commands run in isolation
2. **Filesystem Permissions** - Operations restricted to project directory
3. **Command Allowlist** - Dynamic allowlist based on project stack

---

### 7. DevOps

| Aspect | Auto Claude | SummitFlow |
|--------|-------------|------------|
| CI Platform | GitHub Actions | None |
| CI Stages | lint, test, build | N/A |
| Docker | Docker Compose (FalkorDB) | None |
| Deployment | Manual (Electron build) | Manual (systemd) |
| Env Management | .env example | .env.local |

---

## Technology Stacks

### Shared Technologies
- Python, TypeScript
- React 19
- Tailwind CSS
- Radix UI
- Motion (animations)
- Ruff (linting)
- pytest

### Unique to Auto Claude
- Electron 39.2.6
- Zustand (15+ stores)
- xterm.js + node-pty
- claude-agent-sdk
- graphiti-core (FalkorDB)
- Playwright, Vitest
- LangChain

### Unique to SummitFlow
- Next.js 15
- FastAPI
- PostgreSQL
- Redis + Celery
- psycopg
- TanStack React Query
- mypy
- Cloudflare Tunnel

---

## Feature Matrix

| Feature | Auto Claude | SummitFlow |
|---------|:-----------:|:----------:|
| Multi-agent AI orchestration | YES | - |
| Extended thinking | YES | - |
| Git worktree isolation | YES | - |
| AI merge conflict resolution | YES | - |
| Cross-session memory | YES | - |
| QA loop (50 iterations) | YES | - |
| Terminal grid | YES | - |
| 5-stage Kanban | YES | - |
| Task creation wizard | YES | - |
| AI product roadmap | YES | - |
| Multiple Claude accounts | YES | - |
| GitHub Issues integration | YES | - |
| One-click releases | YES | - |
| REST API | - | YES |
| OpenAPI documentation | - | YES |
| PostgreSQL database | - | YES |
| Celery task queue | - | YES |
| Feature tracking | - | YES |
| Evidence capture | - | YES |
| Vision/goals management | - | YES |
| Beads CLI integration | - | YES |
| Cloudflare Tunnel | - | YES |
| systemd services | - | YES |
| Database explorer | - | YES |
| Endpoint explorer | - | YES |

---

## SWOT Comparison

### Auto Claude

| Strengths | Weaknesses |
|-----------|------------|
| 15+ specialized agent types | AGPL-3.0 limits commercial adoption |
| 3-layer security model | Heavy Claude Code dependency |
| Cross-session memory | Single contributor (bus factor) |
| Comprehensive test suite | No API documentation |
| Production-grade UI | Complex setup requirements |
| Extended thinking integration | |
| Prediction system | |

| Opportunities | Threats |
|---------------|---------|
| More LLM providers | Rapid AI landscape evolution |
| VS Code extension | Single vendor dependency |
| Web-based interface | Enterprise licensing concerns |
| Plugin/extension system | |

### SummitFlow

| Strengths | Weaknesses |
|-----------|------------|
| Modern stack (React 19, Next.js 15) | Very poor test coverage (3 files) |
| Clean layered architecture | No CI/CD pipeline |
| Comprehensive AI agent docs | No authentication |
| Feature-rich tooling | No observability |
| Good code quality | Large files need refactoring |

| Opportunities | Threats |
|---------------|---------|
| Add comprehensive tests | Technical debt risk |
| Implement CI/CD | Single developer risk |
| Add authentication | Limited deployment scenarios |
| Integrate actual AI/ML | Manual deployment errors |

---

## Recommendations

### Choose Auto Claude if:

1. **Autonomous AI coding** is your primary goal
2. You want to **parallelize AI coding tasks** with multiple agents
3. You need **git worktree isolation** for safe parallel development
4. You want **AI-powered merge conflict resolution**
5. **Desktop-first** experience is preferred
6. You're comfortable with **AGPL-3.0 licensing**
7. You want **cross-session memory** for smarter context retrieval

### Choose SummitFlow if:

1. **Project management and feature tracking** is your focus
2. You need **evidence-based verification** workflows
3. You want **unified codebase exploration** (files, DB, tasks, endpoints)
4. **Web-first** experience is preferred
5. You need **REST API integration** with other tools
6. You want a **private/internal development platform**
7. **Beads CLI** integration fits your workflow

### If You Need Both:

These tools could be **complementary**:
- Use **Auto Claude** for autonomous coding tasks
- Use **SummitFlow** for project/feature management and verification
- Connect via Auto Claude's GitHub Issues integration or custom tooling

---

## Conclusion

**Auto Claude** is the more mature, feature-complete product with sophisticated AI orchestration (15+ agents), comprehensive testing (48 files), and production-grade security (7 validators, 3-layer model). It scores **77/100** overall.

**SummitFlow** is an early-stage developer platform with good architecture but significant gaps in testing, CI/CD, and authentication. It excels at codebase exploration and evidence capture but lacks built-in AI capabilities. It scores **58/100** overall.

**The 19-point gap** reflects Auto Claude's advantages in AI/ML (10 vs 2), testing (7 vs 3), and security (9 vs 5). SummitFlow's main advantage is database design (8 vs 6).

For **AI-assisted coding**: Auto Claude is the clear choice.
For **project management tooling**: SummitFlow offers unique features but needs maturation.

---

## Files Generated

- `comparison_auto-claude_vs_summitflow.json` - Machine-readable comparison
- `comparison_auto-claude_vs_summitflow.md` - This report

---

*Generated by project_review comparison mode*
