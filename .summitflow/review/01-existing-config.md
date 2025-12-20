# Existing Claude Code Configuration

**Review Date:** 2025-12-20
**Reviewer:** Claude Code (Opus 4.5)

## CLAUDE.md Files Found

- [x] **Root CLAUDE.md:** `./CLAUDE.md` (163 lines)
  - Key sections: MANDATORY issue tracking, Quick Reference, Rules index, URLs, Service Management, Project Structure, Database schema, API Conventions
  - References: AGENTS.md, workflow-guide.md, task-reference.md
  - Version: 2.0.0, Updated 2025-12-19
- [ ] **Subdirectory CLAUDE.md files:** None found
- [ ] **Global ~/.claude/CLAUDE.md:** Does not exist

## Rules Directory

- [x] **Exists:** Yes - `.claude/rules/` with 6 files
- [x] **Files:**
  | File | Size | Purpose |
  |------|------|---------|
  | `architecture-coherence.md` | 7.1KB | Anti-silo, DRY, holistic architecture (MANDATORY) |
  | `explorer-architecture.md` | 3.8KB | Explorer layer boundaries (MANDATORY) |
  | `interaction-style.md` | 2.7KB | Direct communication, technical focus |
  | `issue-tracking.md` | 3.6KB | Every discovered bug = task (MANDATORY) |
  | `service-management.md` | 2.2KB | Systemd service control |
  | `ui-backend-lockstep.md` | 1.9KB | Backend changes need UI visibility |
- [ ] **Path targeting used:** No - all rules apply globally

## Global Rules (`~/.claude/rules/`)

- [x] **Files found:**
  | File | Purpose |
  |------|---------|
  | `summitflow-vs-app.md` | SummitFlow vs app code separation |
  | `tasks-workflow.md` | `st` CLI essential commands |

## Global Docs (`~/.claude/docs/`)

- [x] **Files found:**
  | File | Purpose |
  |------|---------|
  | `task-reference.md` | Full `st` CLI reference |

## Custom Commands

- [x] **Directory exists:** `.claude/commands/` - empty (0 files)
- [ ] **Commands found:** None
- [ ] **Relevant to Phase 10:** N/A

## Custom Agents

- [x] **Directory exists:** `.claude/agents/` - empty (0 files)
- [ ] **Agents found:** None
- [ ] **Tool permissions:** N/A

## Skills Directory

- [x] **Directory exists:** `.claude/skills/` with 2 subdirectories:
  | Skill | Purpose |
  |-------|---------|
  | `browser-automation/` | Playwright-based browser automation |
  | `context-manager/` | Context usage monitoring (check.js) |

## Hooks Configuration

**Project Settings:** `.claude/settings.json` - Does not exist
**Local Settings:** `.claude/settings.local.json`

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/stop.py\"",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

| Hook | Configured | Purpose |
|------|------------|---------|
| **PreToolUse** | No | - |
| **PostToolUse** | No | - |
| **Stop** | **Yes** | Context monitoring (75-90% thresholds), auto-commit at 85%+ |
| **PreCompact** | No | - |
| **SessionStart** | No | - |

### Stop Hook Analysis (`stop.py`)

The existing stop hook provides:
- Context percentage monitoring via `check.js`
- Threshold warnings: 75% (warning), 80% (wrap up), 85% (checkpoint), 90% (critical)
- Auto-commit at 85%+ context
- Uncommitted file warnings

**Key Integration Point:** This hook already runs after every response - can be extended for observation capture.

## MCP Servers

- [ ] **MCP config:** `.mcp.json` does not exist
- [ ] **Memory-related servers:** None

## Global Settings (`~/.claude/settings.json`)

| Setting | Value |
|---------|-------|
| Model | opus |
| statusLine | Custom bash script |
| alwaysThinkingEnabled | true |
| Plugins | frontend-design enabled |
| Permissions | Extensive allow list for common commands |

## Existing Roundtable Infrastructure (v2 Critical)

### Agent Clients (`backend/app/services/agents/`)

| File | Lines | Purpose |
|------|-------|---------|
| `base.py` | 10.6KB | LLMClient base class, LLMResponse dataclass |
| `claude.py` | 11.4KB | ClaudeClient using official Agent SDK |
| `gemini.py` | 11.1KB | GeminiClient using Google ADK |
| `__init__.py` | 4.6KB | Agent factory, AgentType enum |

### Claude Client Integration Points

- `ClaudeClient.generate_with_tools_native()` (line 183-314)
- Uses `HookMatcher` with `PreToolUse` hooks for permission control
- **Can add PostToolUse hook for observation capture**
- Permission callback pattern: `async def permission_hook(input_data, tool_use_id, context)`

### Gemini Client Integration Points

- `GeminiClient._create_before_tool_callback()` (line 178-244)
- `GeminiClient.generate_with_tools_native()` (line 246-314)
- Uses ADK's `before_tool_callback` pattern
- **Can add after_tool_callback or wrap before_tool_callback for capture**

### Roundtable Services

| File | Size | Purpose |
|------|------|---------|
| `roundtable.py` | 35.4KB | RoundtableService, RoundtableSession, message routing |
| `roundtable_tools.py` | 32.2KB | RoundtableToolExecutor, tool definitions |
| `roundtable_permissions.py` | 5.3KB | PermissionManager for write tool approval |

### Tool Executor Integration Point

- `RoundtableToolExecutor.execute()` in `roundtable_tools.py`
- **Can add asyncio.create_task() after execute() for observation capture**

### Session Storage (`backend/app/storage/roundtable.py`)

- 14.7KB, handles session persistence
- **Can extend for observation_queue table access**

### SSE Streaming (`backend/app/api/roundtable.py`)

- 30.8KB, handles SSE events
- Current events: `message`, `tool_use`, `tool_result`, `permission_request`, `permission_response`, `error`, `done`
- **Can add `observation_created` event**

### Celery Setup

- `backend/app/celery_app.py` - Celery with Redis broker (DB 1), PostgreSQL backend
- Ready for observation processing tasks

## Insights for Phase 10 v2

### What We Can Leverage

1. **Stop Hook:** Already exists and runs after every response - can extend for diary/checkpoint triggers
2. **Agent Clients:** ClaudeClient and GeminiClient have clear integration points for after-tool capture
3. **RoundtableToolExecutor:** Clear execute() method to wrap with observation capture
4. **SSE Infrastructure:** Event system ready for `observation_created` events
5. **Celery:** Redis + PostgreSQL backend ready for background observation processing
6. **Rules Directory:** Established pattern for domain-specific rules - perfect for auto-generated patterns
7. **Context Manager Skill:** Already tracks context usage - can feed into checkpoint decisions

### What Conflicts With Our Plan

1. **No PreCompact hook:** Plan mentions PreCompact for diary entries, but no hook infrastructure exists yet
2. **No PostToolUse hook on Claude SDK:** Would need to add to `ClaudeClient.generate_with_tools_native()`
3. **Empty agents directory:** No custom agent definitions exist - need to create memory-sync and reflection agents

### What Gaps Exist

1. **No observation tables:** Need to create `observations`, `observation_queue` tables
2. **No FTS on roundtable_sessions:** Need to add tsvector columns
3. **No pattern storage:** No `.summitflow/rules/patterns/` directory
4. **No diary infrastructure:** No diary table or PreCompact trigger
5. **No checkpoint system:** No pause/resume capability for roundtable sessions
6. **No context builder:** RoundtableSession.get_context() is simple string concat, not progressive disclosure

### Existing Hooks We Can Extend

| Hook | Current Use | Phase 10 Extension |
|------|-------------|-------------------|
| **Stop** | Context monitoring, auto-commit | Add diary entry trigger at context thresholds |
| **(New) PostToolUse** | None | Capture tool executions for observation queue |
| **(New) PreCompact** | None | Trigger diary entry before context compression |
