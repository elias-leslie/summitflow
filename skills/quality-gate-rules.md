---
tier: guardrail
summary: Quality gate and dt usage rules
trigger_task_types: [refactor, bug, feature, chore]
pinned: false
tags: [skill:quality-gate-rules, quality, dt]
---

# Quality Gate Rules

## Tool Usage
- Always use `dt` wrapper for quality checks, never raw tools
- Tool definitions live in `~/summitflow/scripts/lib/tool-registry.json`
- Common combos: `dt -q -d` (quick + changed), `dt --check` (full)
- Use `dt <tool> --fix` for auto-fixing (e.g., `dt ruff --fix`)

## Quality Gate Tools
- **pytest**: Backend tests (`dt pytest`)
- **ruff**: Python linting (`dt ruff`)
- **types**: Python type checking (`dt types`)
- **biome**: Frontend linting (`dt biome`)
- **tsc**: TypeScript compilation (`dt tsc`)
- **sqlfluff**: SQL linting (`dt sqlfluff`)
- **squawk**: Migration linting (`dt squawk`)

## Per-Project Configuration
- Quality gate tools and mode are configurable per project in autonomous settings
- Empty tool list = use mode (quick/check/changed-only)
- Specific tools override mode: `["ruff", "types"]` runs only those

## Self-Healing Flow
1. Quality gate fails -> attempt `dt --fix`
2. If fix produces changes -> auto-commit with `[auto-fix]` prefix
3. Re-run quality gate to verify
4. If still failing -> escalate to supervisor
