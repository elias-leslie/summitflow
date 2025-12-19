# Project Review: Auto Claude

> Generated: 2025-12-18T19:10:00Z | Target: https://github.com/AndyMik90/Auto-Claude | Confidence: HIGH

## Executive Summary

Auto Claude is a sophisticated multi-agent autonomous coding framework that leverages the Claude Code SDK to orchestrate AI agents for end-to-end software development. The framework excels at decomposing complex tasks into manageable subtasks, implementing them in isolated git worktrees, and self-validating through automated QA loops.

The architecture demonstrates impressive engineering with a three-layer security model (OS sandbox, filesystem permissions, command allowlisting), dual-layer memory system (file-based + Graphiti graph database), and intelligent merge conflict resolution. The polished Electron desktop UI provides a visual Kanban board, up to 12 concurrent agent terminals, roadmap planning, and ideation features.

**Creator:** Andre Mikalsen, who uses AI to code production-level applications daily. Active in a free Discord community for support and networking.

While the technical implementation is strong, the AGPL-3.0 license and dependency on Claude Code subscription may limit broader adoption. The single-contributor status represents a bus factor risk, but the comprehensive test suite and documentation suggest maintainable code.

### Quick Stats

| Metric | Value |
|--------|-------|
| Primary Languages | Python, TypeScript |
| Framework | Claude Agent SDK + Electron + React 19 |
| Architecture | Modular Monolith (domain-based) |
| Quality Score | **B** |
| Maturity | Production |
| Test Files | 48 (Python) + Vitest/Playwright (Frontend) |
| Lines of Code | ~162,628 |
| License | AGPL-3.0 (Copyleft) |

### SWOT Analysis

**Strengths:**
- Sophisticated multi-agent pipeline (planner, coder, QA reviewer, QA fixer)
- Three-layer security model with dynamic command allowlisting
- Git worktree isolation for safe parallel development
- AI-powered merge conflict resolution (~98% prompt reduction)
- Cross-session memory via Graphiti graph database
- Comprehensive test suite (48 Python test files)
- Production-grade Electron UI with 5-stage Kanban workflow, comparable to Linear/Notion
- Excellent documentation (README, CONTRIBUTING, CLAUDE.md)

**Weaknesses:**
- AGPL-3.0 license limits commercial/proprietary use
- Heavy dependency on Claude Code CLI and subscription
- No API documentation or OpenAPI spec
- Limited observability/monitoring
- Single contributor (bus factor = 1)
- Complex setup requirements (6 prerequisites)

**Opportunities:**
- Expand LLM provider support (Gemini, Mistral, etc.)
- Create VS Code extension for integrated experience
- Add web-based interface as alternative to Electron
- Implement distributed agent execution
- Add team collaboration features
- Plugin/extension system for custom agents

**Threats:**
- Rapid AI coding tool evolution (new competitors daily)
- Single vendor dependency (Claude Code SDK)
- AGPL licensing may deter enterprise adoption
- Complex setup may limit casual adoption

---

## Detailed Analysis

### 1. Project Identity & Purpose

**Auto Claude** is positioned as "Your AI coding companion" that enables developers to describe what they want to build and let autonomous agents handle the planning, coding, and validation. The framework targets both "vibe coders just getting started" and experienced developers.

**Key Value Propositions:**
- **Autonomous Tasks**: Describe what you want, agents handle the rest
- **Parallel Agents**: Run up to 12 Claude Code terminals simultaneously
- **Git Worktree Isolation**: All work happens in separate worktrees, protecting main branch
- **Self-Validating**: Built-in QA loops catch issues before human review
- **AI Merge Resolution**: Handles conflicts when main branch evolves during builds

The framework integrates deeply with the Claude ecosystem, requiring a Claude Pro or Max subscription and the Claude Code CLI.

### 2. Architecture & Design

Auto Claude follows a **modular monolith** pattern with clear domain separation:

```
auto-claude/               # Python Backend
├── agents/                # Core agent session logic
├── core/                  # Client, auth, security
├── memory/                # Session memory (file + Graphiti)
├── merge/                 # Sophisticated merge strategies
├── spec/                  # Spec creation pipeline
├── prompts/               # Agent prompt templates
├── integrations/          # Linear, Graphiti providers
└── cli/                   # Command-line interface

auto-claude-ui/            # Electron Frontend
├── src/main/              # Electron main process
├── src/renderer/          # React UI
│   ├── components/        # Feature-based components
│   └── stores/            # Zustand state stores
└── src/shared/            # Shared types
```

**Agent Pipeline Architecture:**

1. **Spec Creation (3-8 phases based on complexity)**
   - Discovery → Requirements → [Research] → Context → Spec → [Self-Critique] → Plan → Validate

2. **Implementation**
   - Planner Agent → Coder Agent (with subagents) → QA Reviewer → QA Fixer (loop)

3. **Merge**
   - Conflict Detection → Git Auto-Merge → Conflict-Only AI → Parallel Resolution

**Notable Design Decisions:**
- **Facade Pattern**: `agent.py` re-exports from `agents/` for backward compatibility
- **Dual Memory**: Primary file-based (zero deps) + optional Graphiti (graph + semantic search)
- **Security Hooks**: `PreToolUse` hook validates bash commands against dynamic allowlist

### 3. Technology Stack

#### Frontend (Electron Desktop App)

| Component | Technology | Version |
|-----------|------------|---------|
| Framework | Electron | 39.2.6 |
| UI Library | React | 19.2.3 |
| State Management | Zustand | 5.0.9 |
| Styling | Tailwind CSS | 4.1.17 |
| Components | Radix UI | Various |
| Terminals | xterm.js + node-pty | 5.5.0 / 1.1.0-beta42 |
| Animations | Motion | 12.23.26 |
| Build Tool | Electron Vite | 5.0.0 |

The UI provides a polished, production-grade experience comparable to commercial tools like Linear or Notion:

- **Kanban Board**: 5-stage workflow (Planning → In Progress → AI Review → Human Review → Done) with progress bars, color-coded status badges, and time stamps
- **Task Creation Wizard**: Rich form with model selection (Claude Opus 4.5), thinking levels (Ultra Think for extended reasoning), reference images (drag-drop, up to 10MB each), reference files browser, and optional "human review before coding" toggle
- **Task Complexity Auto-Assessment**: AI automatically identifies task complexity (simple/medium/complex) with confidence percentage (e.g., "90% confidence simple task"), which dictates spec depth and testing strategy
- **Agent Terminals**: 2x3 grid layout (expandable to 12), individual headers with status badges (STREAMING, Running), real-time Claude Code output, one-click task context injection. Terminals can be named/renamed to track context across multiple tasks. **Session restoring** preserves terminal state across app restarts.
- **Roadmap**: AI-generated feature prioritization using MoSCoW methodology (Must Have, Should Have, Could Have, Won't Have) with impact scoring and target audience analysis. Upcoming Canny integration for user feedback collection.
- **Phase Visualization**: Plan/Code/QA tabs with progress indicators and status badges (Planning, Running, Pending, Completed)
- **Ideation**: Categorized improvement suggestions (Security, Performance, Code Improvements) - AI analyzes project to identify low-hanging fruits and quick wins
- **Insights**: ChatGPT-style project conversations with chat history. Used for investigating code, sparring partner discussions, and general project exploration
- **Changelog & GitHub Integration**: Generate changelogs from git history OR completed Auto Claude tasks. Direct GitHub release creation with one click. Useful for tracking project changes over time

The clean dark theme features good contrast, subtle gradients, and well-organized sidebar navigation.

#### Backend (Python CLI)

| Component | Technology | Version |
|-----------|------------|---------|
| Runtime | Python | 3.10+ |
| LLM SDK | claude-agent-sdk | >=0.1.16 |
| Memory | graphiti-core[falkordb] | >=0.5.0 |
| Environment | python-dotenv | >=1.0.0 |

**Supported Memory Providers:**
- LLM: OpenAI, Anthropic, Azure OpenAI, Ollama
- Embeddings: OpenAI, Voyage AI, Azure OpenAI, Ollama

**Cost Efficiency Claim:** The memory system improves with use - the more you work with Auto Claude, the smarter context retrieval becomes at smaller token usage, potentially making it cheaper than raw Claude Code over time.

#### Database

- **FalkorDB** (Redis-compatible graph database) via Docker
- Used for Graphiti-based cross-session memory
- Optional - file-based memory works without any database

### 4. Code Quality Assessment

**Linting & Formatting:**
- **Python**: Ruff with comprehensive rules (E, W, F, I, B, C4, UP)
- **TypeScript**: ESLint with strict mode + TypeScript checking
- **Pre-commit hooks**: Automated enforcement on every commit

**Type Safety:**
- Python: Type hints used throughout
- TypeScript: Strict mode enabled

**Code Organization:**
```python
# Example: Clean re-exports for backward compatibility
# auto-claude/core/agent.py

from agents import (
    run_autonomous_agent,
    run_agent_session,
    post_session_processing,
    # ... 15 more exports
)

__all__ = [
    "run_autonomous_agent",
    # ... comprehensive export list
]
```

**Patterns Observed:**
- Factory pattern for LLM/embedder creation
- Strategy pattern for merge algorithms
- Facade pattern for module organization
- Clear separation of concerns

### 5. Testing Coverage

| Test Type | Framework | Count | Coverage |
|-----------|-----------|-------|----------|
| Unit (Python) | pytest | 48 files | Good |
| Integration | pytest | ~10 files | Good |
| E2E | Playwright | 1 file | Basic |
| Frontend | Vitest | Present | Unknown |

**Notable Test Areas:**
- Security (command validation, secrets scanning)
- Merge algorithms (auto-merger, conflict detection, AI resolver)
- QA loop and criteria validation
- Spec creation pipeline
- Graphiti integration
- Worktree management

**CI Configuration:**
- Tests run on Python 3.11 and 3.12
- Frontend tests via pnpm
- Lint checks for both Python and TypeScript

### 6. Security Posture

Auto Claude implements a **three-layer security model**:

1. **OS Sandbox**: Bash commands run in isolation
2. **Filesystem Permissions**: Operations restricted to project directory
3. **Command Allowlist**: Dynamic allowlist based on project stack analysis

```python
# Security hook example
security_settings = {
    "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True},
    "permissions": {
        "defaultMode": "acceptEdits",
        "allow": [
            "Read(./**)",
            "Write(./**)",
            "Edit(./**)",
            "Bash(*)",  # Validated by security hook
        ],
    },
}
```

**Security Features:**
- Dynamic command allowlisting based on detected project stack
- Secret scanning script (`scan-for-secrets`)
- `.secretsignore` example provided
- Security profile cached in `.auto-claude-security.json`
- Agent-type-based tool filtering (QA agents get different tools than Coder)

### 7. DevOps & Infrastructure

**GitHub Actions Workflows:**
- `ci.yml`: Python tests (3.11, 3.12) + Frontend tests
- `lint.yml`: Ruff + ESLint + TypeScript checks
- `test-on-tag.yml`: Full test suite on version tags
- `build-prebuilds.yml`: Native module prebuilds for Windows
- `discord-release.yml`: Release notifications

**Docker:**
- `docker-compose.yml` for FalkorDB + Graphiti MCP server
- No Dockerfile for the main app (Electron distributed as standalone)

### 8. Documentation Quality

| Document | Quality | Notes |
|----------|---------|-------|
| README.md | Excellent | Comprehensive setup, features, architecture |
| CONTRIBUTING.md | Excellent | Detailed dev setup, code style, testing |
| CLAUDE.md | Good | Commands, architecture, security model |
| CHANGELOG.md | Good | Detailed version history |
| guides/ | Good | CLI usage, Docker setup |

**Missing:**
- API documentation
- Architecture diagrams
- ADRs (Architecture Decision Records)

**Community:**
- Free Discord community for support, bug reports, and networking with AI enthusiasts, developers, entrepreneurs, and marketers

### 9. Developer Experience

**Setup Steps:**
1. Install Node.js 18+, Python 3.10+, Docker Desktop
2. Install Claude Code CLI
3. Set up Python virtual environment
4. Start FalkorDB with Docker Compose
5. Install frontend dependencies with pnpm
6. Build and start Electron app

**DX Features:**
- Pre-commit hooks for automated linting
- Hot reload in Electron dev mode
- pnpm/npm scripts for common tasks
- Husky for git hooks

**Pain Points:**
- 6 prerequisites required
- Claude subscription required
- Native module (node-pty) may require build tools on Windows

**Power User Features:**
- **Multiple Claude Account Support**: Heavy users can configure multiple Claude Code Max subscriptions and swap between them. Planned auto-switching based on rate limit detection enables continuous background work.
- **GitHub Issues Integration**: GitHub issues flow directly into Auto Claude. Create tasks from issues and the system can identify and fix problems automatically in the background.

**Coming Soon (per demo):**
- BMAD method integration for context engineering and AI coding validation
- Auto account switching based on rate limits
- Canny integration for user feedback pipeline

### 10. Performance Considerations

**Strengths:**
- Parallel agent execution via git worktrees
- Parallel merge conflict resolution
- File-based caching for specs and memory
- Efficient IPC between Electron processes

**Concerns:**
- Electron app size (typical for the platform)
- Memory usage with 12 concurrent terminals unknown
- No performance benchmarks available

---

## Recommendations

### High Priority

1. **Address bus factor risk**: Document critical architectural decisions, consider attracting co-maintainers
2. **Add monitoring/observability**: Implement error tracking (Sentry) and basic telemetry
3. **Create API documentation**: Document the Python CLI and any programmatic interfaces
4. **Consider dual licensing**: MIT/Apache for broader adoption + AGPL for copyleft users

### Medium Priority

1. **Add architecture diagrams**: Visual documentation of agent pipeline and data flow
2. **Create VS Code extension**: Lower barrier to entry for developers
3. **Implement plugin system**: Allow custom agents and tools
4. **Add performance benchmarks**: Document expected behavior under load

### Nice to Have

1. **Web-based alternative**: For users who prefer browser over Electron
2. **Team collaboration features**: Shared projects, agent coordination
3. **Multi-LLM support**: Beyond Claude (Gemini, GPT-4, Mistral)
4. **Internationalization**: Multi-language support for UI

---

## Appendix

### A. File Statistics

| Type | Count |
|------|-------|
| Python files (.py) | 422 |
| TypeScript files (.ts) | 299 |
| React components (.tsx) | 207 |
| Test files | 48+ |
| Prompt templates (.md) | 26 |

### B. Key Configuration Files

| File | Purpose |
|------|---------|
| `ruff.toml` | Python linting configuration |
| `.pre-commit-config.yaml` | Pre-commit hooks (Ruff, ESLint, TypeScript) |
| `docker-compose.yml` | FalkorDB + Graphiti MCP services |
| `electron.vite.config.ts` | Electron build configuration |
| `auto-claude/.env.example` | Environment variable template |

### C. Agent Prompt Templates

| Prompt | Purpose |
|--------|---------|
| `planner.md` | Creates implementation plan with subtasks |
| `coder.md` | Implements individual subtasks |
| `coder_recovery.md` | Recovers from stuck/failed subtasks |
| `qa_reviewer.md` | Validates acceptance criteria |
| `qa_fixer.md` | Fixes QA-reported issues |
| `spec_gatherer.md` | Collects user requirements |
| `spec_researcher.md` | Validates external integrations |
| `spec_writer.md` | Creates spec.md document |
| `spec_critic.md` | Self-critique using extended thinking |
| `complexity_assessor.md` | AI-based complexity assessment |

### D. Metrics Summary

| Metric | Value |
|--------|-------|
| Total Lines of Code | ~162,628 |
| Primary Language | Python (48%), TypeScript (52%) |
| Dependencies (Frontend) | ~50 direct, ~30 dev |
| Dependencies (Backend) | 3 direct |
| Test Coverage | Good (estimated) |
| Documentation Coverage | Good |
| Security Score | Good |
| Overall Grade | B |

---

---

## Appendix B: Comprehensive Codebase Analysis

The following details were discovered through deep exploration of the Auto Claude source code.

### Agent System (Far More Extensive Than Initially Documented)

**Spec Creation Agents (3-8 phases, complexity-adaptive):**

| Agent | Purpose |
|-------|---------|
| Discovery Agent | Analyzes project structure and tech stack |
| Requirements Agent | Gathers task requirements interactively |
| Research Agent | Validates external integrations against real docs |
| Context Discovery Agent | Finds relevant files in codebase |
| Spec Writer Agent | Creates comprehensive specifications |
| Spec Critic Agent | Self-critiques specs using **extended thinking** |
| Planner Agent | Breaks work into subtasks with dependencies |
| Validation Agent | Validates all outputs before proceeding |

**Implementation Agents:**

| Agent | Purpose |
|-------|---------|
| Coder Agent | Implements subtasks with verification steps |
| Coder Recovery Agent | Recovers from failed/stuck sessions |
| Followup Planner | Adaptive planning for discovered dependencies |

**QA Agents (Self-Healing Loop):**

| Agent | Purpose |
|-------|---------|
| QA Reviewer | Validates acceptance criteria, test coverage, code quality |
| QA Fixer | Auto-fixes issues, runs up to **50 iterations** |
| Loop Orchestrator | Detects recurring issues (3+ → human escalation) |

**Analysis Agents:**

| Agent | Purpose |
|-------|---------|
| Ideation Generator | Code quality, performance, security, UI/UX, docs analysis |
| Roadmap Generator | Strategic planning with **competitor analysis** |
| Insights Agent | ChatGPT-style Q&A with task suggestions |
| Complexity Assessor | AI-based task complexity with confidence scoring |

### Three-Tier Complexity Model

| Tier | Criteria | Phases | Features |
|------|----------|--------|----------|
| **SIMPLE** | <3 files, single service | 3 | Discovery → Quick Spec → Validate |
| **STANDARD** | 3-10 files, 1-2 services | 6 | + Requirements, Context, Spec, Planning |
| **COMPLEX** | 10+ files, multiple services | 8 | + Research, Self-Critique (extended thinking) |

**Complexity Signals Detected:**
- Environment variables, config files → configuration complexity
- External APIs, third-party services → integration complexity
- Database schema changes, migrations → infrastructure changes
- Multiple file modifications across services → broader scope

### Project Analysis System (`analysis/analyzers/`)

| Analyzer | Purpose |
|----------|---------|
| RouteDetector | API endpoint discovery |
| PortDetector | Service port detection |
| DatabaseDetector | Database type/schema analysis |
| ServiceAnalyzer | Microservice identification |
| AuthDetector | Authentication pattern detection |
| JobsDetector | Background job system detection |
| MigrationsDetector | Database migrations tracking |

### Prediction & Risk Analysis (`prediction/`)

| Component | Purpose |
|-----------|---------|
| Predictor | Anticipates implementation risks |
| RiskAnalyzer | Evaluates risk factors |
| PatternAnalyzer | Identifies patterns in success/failure |
| ChecklistGenerator | Generates task checklists |
| MemoryLoader | Loads historical patterns from Graphiti |

### Security Validators (`security/`)

| Validator | Purpose |
|-----------|---------|
| DatabaseValidators | SQL injection prevention |
| FilesystemValidators | Path traversal prevention |
| GitValidators | Git operation safety |
| ProcessValidators | Process execution safety |
| ScanSecrets | Secret detection and prevention |
| Hooks | Pre-execution validation |
| Validator Registry | Centralized validation rules |

### Context Building System (`context/`)

| Component | Purpose |
|-----------|---------|
| ContextBuilder | Assembles project context for agents |
| Orchestrator | Coordinates context gathering |
| RecoveryManager | Recovers interrupted sessions |
| ServiceMatcher | Matches detected services to patterns |
| PatternDiscovery | Identifies codebase patterns |
| KeywordExtractor | Extracts domain keywords |

### Merge System Components (`merge/`)

| Component | Purpose |
|-----------|---------|
| SemanticAnalyzer | Analyzes semantic changes from tasks |
| ConflictDetector | Identifies conflicts between parallel tasks |
| AutoMerger | Deterministic merges for non-conflicting changes |
| AIResolver | Claude-powered resolution for ambiguous conflicts |
| ConflictResolver | Fine-grained conflict handling |
| FileEvolutionTracker | Tracks baselines and task changes |
| TimelineTracker | Git history timeline |

**3-Tier Merge Strategy:**
1. **Git Auto-Merge** - Simple non-conflicting changes merge instantly
2. **Conflict-Only AI** - AI receives only specific conflict regions (~98% prompt reduction)
3. **Full-File AI** - Fallback for complex multi-change conflicts

### Electron Main Process Services

| Service | Purpose |
|---------|---------|
| AgentManager | Manages agent lifecycles, routes task execution |
| TerminalManager | Multiple terminal sessions, session persistence |
| PythonEnvManager | Python installation detection, venv management |
| DockerService | Docker detection, FalkorDB container management |
| FalkorDBService | Database lifecycle, health checks |
| ClaudeProfileManager | Multi-profile OAuth, token persistence |
| RateLimitDetector | Detects rate limits, classifies type (session/weekly) |
| TaskLogService | Phase-based log loading, streaming updates |

### Zustand State Stores (15+ stores)

| Store | Purpose |
|-------|---------|
| task-store | Task CRUD and status |
| project-store | Project data |
| terminal-store | Terminal state |
| insights-store | Chat history and suggestions |
| roadmap-store | Roadmap data |
| ideation-store | Ideation results |
| changelog-store | Changelog data |
| context-store | Project context |
| settings-store | User settings |
| rate-limit-store | Rate limit tracking |
| claude-profile-store | Profile management |
| github-store | GitHub integration state |
| file-explorer-store | File browsing state |
| release-store | Release management |

### Spec Persistence Structure

```
.auto-claude/specs/{spec-id}/
├── spec.md                    # Full specification
├── implementation_plan.json   # Subtask breakdown
├── complexity_assessment.json # Complexity analysis
├── qa_criteria.json           # QA acceptance criteria
└── task_logs.json             # Phase-based logs
```

### Terminal Session Persistence

- Sessions stored by date (YYYY-MM-DD)
- Per-project session tracking
- **10-day history retention**
- **100KB output buffer** per terminal

### CLI Commands

**Spec Creation:**
```bash
python spec_runner.py --interactive          # Interactive mode
python spec_runner.py --task "Description"   # From description
python spec_runner.py --continue 001         # Continue previous
python spec_runner.py --complexity simple    # Force complexity
python spec_runner.py --no-ai-assessment     # Heuristic only
```

**Build Execution:**
```bash
python run.py --spec 001                     # Run autonomous build
python run.py --list                         # List all specs
python run.py --spec 001 --review            # Review changes
python run.py --spec 001 --merge             # Merge to main
python run.py --spec 001 --discard           # Delete build
python run.py --spec 001 --qa                # Run QA manually
python run.py --spec 001 --qa-status         # Check QA status
```

**Analysis:**
```bash
python roadmap_runner.py --project /path     # Generate roadmap
python roadmap_runner.py --refresh           # Force regenerate
python insights_runner.py --project /path    # Chat interface
```

### Linear Integration Details

- Task state synchronization
- Status updates during planning, coding, QA phases
- Build completion status
- **Stuck task detection**
- State persistence via JSON serialization

### IPC Handler Organization

```
src/main/ipc-handlers/
├── task/
│   ├── crud-handlers.ts       # Create, Read, Update, Delete
│   ├── execution-handlers.ts  # Start, Stop, Review, Recovery
│   ├── worktree-handlers.ts   # Worktree status, diffs, merge
│   └── logs-handlers.ts       # Load, watch task logs
├── project-handlers.ts        # Init, Python env, discovery
├── terminal-handlers.ts       # Terminal lifecycle
├── linear-handlers.ts         # Linear sync
├── github-handlers.ts         # GitHub issues/PRs
├── changelog-handlers.ts      # Changelog generation
├── roadmap-handlers.ts        # Roadmap CRUD
├── ideation-handlers.ts       # Ideation phases
└── insights-handlers.ts       # Chat-based insights
```

---

## Appendix C: Demo Transcript Insights

The following details were extracted from a video demo transcript (`transcript.md`) by Andre Mikalsen:

### Key Demo Highlights

1. **Task Complexity Auto-Assessment**: When creating a task, the system automatically identifies complexity level (simple/medium/complex) with a confidence percentage (e.g., "90% confidence simple task"). This dictates the spec depth, testing strategy, and resource allocation.

2. **Multiple Claude Account Support**: For heavy users who need continuous AI coding, Auto Claude supports configuring multiple Claude Code Max subscriptions. Planned feature: automatic switching when one account hits rate limits.

3. **GitHub Issues Integration**: Issues from GitHub can flow directly into Auto Claude. Create tasks from issues, and the system can identify what's wrong and fix it automatically in the background.

4. **Changelog & GitHub Releases**: Generate changelogs from either git history OR completed Auto Claude tasks. One-click GitHub release creation with emoji support.

5. **Session Restoring**: Terminal sessions persist across app restarts - you can close the application and spawn it up again with your session state preserved.

6. **Memory System Cost Efficiency**: The graph memory system improves with use - the more you work with Auto Claude, the smarter context retrieval becomes at smaller token usage, potentially making it cheaper than raw Claude Code over time.

7. **Coming Features**:
   - BMAD method for context engineering and AI coding validation
   - Auto account switching based on rate limits
   - Canny integration for user feedback pipeline

### Demo Workflow Shown

1. Created task with screenshot (double close button bug)
2. AI auto-identified complexity: simple (90% confidence)
3. Task entered planning phase with 27 log entries
4. Created second task while first ran in background
5. Showed parallel task execution on same files (worktree isolation)
6. Demonstrated AI merge conflict resolution layer
7. Showed AI self-review before human review
8. Staged changes with one-click merge conflict resolution
9. Generated changelog from git history → one-click GitHub release

---

*Generated by project_review command | Run `/project_review --compare` to compare with another project*

*Updated with demo transcript: 2025-12-18*
