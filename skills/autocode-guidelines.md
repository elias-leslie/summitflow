---
tier: guardrail
summary: Autocode execution guidelines
trigger_task_types: [refactor, bug, feature, chore]
pinned: false
tags: [skill:autocode-guidelines, autocode]
---

# Autocode Execution Guidelines

## Pre-Execution
- Verify codebase passes quality gates before starting (`dt --quick`)
- Inspect uncommitted and ahead-of-upstream git state at start, then resolve it inside the session with the canonical commit workflow before new implementation work.
- Read existing tests for the module before writing implementation

## During Execution
- Follow test-first for backend: read tests, adjust tests, then implement
- Complete the vertical slice: backend changes need UI updates
- Use `dt` for all quality checks, never raw tools (ruff, types, etc.)
- Track bugs immediately with `st -P <project> bug "Fix: X"` when discovered

## Post-Execution
- Run `dt --quick` before marking any step as passed
- Publish validated commits with the canonical commit workflow
- Never mark a task as done without restart + verify

## Anti-Patterns
- Never use `# type: ignore`, `# noqa`, `Any` without justification
- Never bypass pre-commit hooks with `--no-verify`
- Never hardcode production project IDs in tests
- Never create parallel utilities — search first, extend existing
