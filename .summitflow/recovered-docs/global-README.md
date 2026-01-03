# Claude Code Configuration

Personal Claude Code configuration with custom agents, commands, rules, and skills.

## Structure

```
~/.claude/
├── agents/           # Custom agent definitions
├── commands/         # Slash commands (/refactor_it, /next_it, etc.)
├── docs/             # Reference documentation
├── hooks/            # Claude Code hooks
├── plugins/          # Plugin configuration
├── rules/            # Global rules (apply to all projects)
├── skills/           # Custom skills
└── settings.json     # Claude Code settings
```

## Key Components

### Agents

| Agent | Purpose |
|-------|---------|
| `elite-code-architect` | High-quality implementation with codebase research |
| `pre-implementation-check` | Verify assumptions before implementation |
| `refactor-executor` | Execute planned refactoring tasks |

### Commands

| Command | Purpose |
|---------|---------|
| `/refactor_it` | Orchestrate refactoring with inventory, planning, execution |
| `/next_it` | Work on next highest-priority task |
| `/do_it` | Execute implementation from JSON task files |
| `/task_it` | Generate implementation files from planning |
| `/update_it` | Dependency updates |
| `/memory_health` | Check memory system health |
| `/memory_backfill` | Mine session history for patterns |
| `/project_review` | Project review and documentation |

### Rules

| Rule | Purpose |
|------|---------|
| `interaction-style.md` | Direct, technical communication style |
| `tasks-workflow.md` | SummitFlow task tracking (st CLI) |
| `tool-selection.md` | Optimal tool usage patterns |
| `summitflow-vs-app.md` | Dev tooling vs app code separation |
| `learned-patterns.md` | Auto-learned patterns from sessions |

### Skills

| Skill | Purpose |
|-------|---------|
| `browser-automation` | Playwright-based browser control |
| `context-manager` | Session context management |

## Usage

This directory is automatically loaded by Claude Code. Rules in `rules/` apply globally to all projects. Project-specific rules go in each project's `.claude/rules/` directory.

## Related Projects

- [summitflow](https://github.com/elias-leslie/summitflow) - AI-assisted development platform
- [terminal](https://github.com/elias-leslie/terminal) - Standalone web terminal service
