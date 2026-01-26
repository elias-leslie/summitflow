# SummitFlow Quick Reference

**Companion to**: [SYSTEM_REFERENCE.md](./SYSTEM_REFERENCE.md)

---

## Core Workflow

```
st ready → st work <task-id> → st context → /do_it → st subtask pass → st close
```

## Active Task Context

```bash
st work task-abc123    # Set active task
st work --show         # Show current context
st work --done         # Clear context
```

Once set, these commands use active task automatically:
- `st context`, `st close`, `st cancel`, `st claim`, `st delete`
- `st log`, `st update`, `st export`, `st autocode`
- `st subtask list/pass/block`, `st step pass/new/insert`

## Execution Pathways

| Pathway | Command | Use When |
|---------|---------|----------|
| **Claude Code** | `/do_it` | Interactive session (you ARE the agent) |
| **Autonomous** | `st autocode` | Queue for Celery (async, full pipeline) |
| **Autonomous (sync)** | `st autocode --sync` | Direct dispatch (blocks, single subtask) |
| **Scheduled** | Celery Beat | autonomous_work_pickup() |

**Note**: When using Claude Code with `/do_it`, you execute steps directly and use `st step pass`/`st subtask pass`. The `st autocode` command queues work for the full autonomous pipeline (worktrees, review gates). Use `--sync` for debugging.

## Verification Model

```
Every step MUST have verify_command + expected_output
Steps only pass when verify_command exits 0
Subtasks only pass when ALL steps pass
Tasks only close when ALL subtasks pass
```

**Verification gates are immutable** - never modify verify_commands to make failing steps pass.

## Plan Schema (Critical Fields)

```json
{
  "title": "Action-oriented title (10-200 chars)",
  "objective": "Single measurable goal (20+ chars)",
  "complexity": "SIMPLE | STANDARD | COMPLEX",
  "spirit_anti": "Required for STANDARD+",
  "done_when": ["Required for STANDARD+"],
  "decisions": [{"id": "d1", ...}],  // Required for COMPLEX
  "subtasks": [
    {
      "id": "1.1",
      "phase": "backend | frontend | scripts | data | verification",
      "steps": [
        {
          "description": "...",
          "verify_command": "bash command (exit 0 = pass)",
          "expected_output": "expected string"
        }
      ]
    }
  ]
}
```

## Deploy Steps (Required for backend/frontend phases)

```bash
# Backend
./scripts/rebuild.sh --backend 2>&1 | rg -q 'Rebuild complete' && echo 'Rebuild complete'

# Frontend (plus browser check)
./scripts/rebuild.sh --frontend 2>&1 | rg -q 'Rebuild complete' && echo 'Rebuild complete'
AGENT_BROWSER_SESSION=verify_$$ agent-browser open http://localhost:PORT/page && \
  agent-browser errors | [ -z "$(cat)" ] && echo 'No errors'
```

## Skills

| Skill | Purpose |
|-------|---------|
| `/do_it <task-id>` | Execute task steps |
| `/plan_it <desc>` | Create task plan |
| `/wrap_it` | Session wind-down |
| `/commit_it` | Quality-gated commit |
| `/qa_it` | Quality checkpoint |

## Service Management

```bash
# ALWAYS use scripts, never manual commands
./scripts/rebuild.sh --backend    # Restart backend + celery
./scripts/rebuild.sh --frontend   # Rebuild and restart frontend
./scripts/status.sh               # Check health

# Ports
SummitFlow: 8001 (API), 3001 (UI)
Agent Hub:  8003 (API), 3003 (UI)
```

## Memory System (ACE-aligned)

Based on [Agentic Context Engineering (ACE) paper](https://arxiv.org/pdf/2510.04618) - see `references/ace_review.md`

```bash
# Save learning (provisional 70-89, canonical 90-99)
curl -X POST http://localhost:8003/api/memory/save-learning \
  -d '{"content": "...", "category": "coding_standard", "confidence": 85}'

# Golden standard (mandate, always injected)
curl -X POST http://localhost:8003/api/memory/golden-standards \
  -d '{"content": "...", "category": "coding_standard"}'
```

**Categories**: coding_standard, troubleshooting_guide, operational_context, system_design, domain_knowledge

### Citation Tracking (ACE Model)

| System | Tracks | Purpose |
|--------|--------|---------|
| SummitFlow | `subtask_citations` with rating (+/-/used) | Per-subtask citation logging |
| Agent Hub | `loaded_count`, `referenced_count` | Injection and citation counts |
| Agent Hub | `helpful_count`, `harmful_count` | ACE voting (task-181399fe) |

**Citation suffix notation**: `st citations log M:abc+ G:def-` where `+` = helpful, `-` = harmful

### Learning Loop (task-181399fe)

```
run_agent() → memory injection → agent cites [M:uuid8] → log_citations(+/-)
    → aggregate to helpful_count/harmful_count → tier_optimizer promotes/demotes
    → close_session() → retrospective → extract_learnings() → future injection
```

## Common Gotchas

| Gotcha | Fix |
|--------|-----|
| verify_command uses absolute paths | Use relative: `backend/...` not `/home/.../backend/` |
| Single uvicorn worker deadlock | Add `--workers 2` to ExecStart |
| agent-browser session not shared | Use `AGENT_BROWSER_SESSION=name` env var |
| Frontend 90s shutdown delay | Add `TimeoutStopSec=10 KillMode=mixed` to service |
| verify_commands run from /home/kasadis/summitflow | Prefix with `cd <project-root> &&` |

## Anti-Patterns

- Direct `git commit` → Use `/commit_it`
- Modify verify_commands to pass → Fix implementation instead
- Skip verification → All subtasks must pass
- Half-ass work at low context → Use `/wrap_it`
- Cherry-pick subtasks → Follow dependency order

## Known Gaps (task-181399fe)

| Gap | Current State | After Fix |
|-----|---------------|-----------|
| run_agent sessions | Fake (uses agent_id) | Real DB sessions |
| run_agent memory | No injection | Injection on turn 1 |
| ACE helpful/harmful | Not implemented | helpful_count/harmful_count on episodes |
| tier_optimizer | Uses utility_score only | Uses helpful >= 5, harmful >= 3 |
| Retrospectives | Don't exist | Generated on close_session() |

---

*Updated: 2026-01-26 | See [SYSTEM_REFERENCE.md](./SYSTEM_REFERENCE.md) for full details*
