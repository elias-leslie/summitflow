---
tier: reference
summary: Commit message and branch conventions
trigger_task_types: [refactor, bug, feature, chore, docs]
pinned: false
tags: [skill:commit-conventions, git, commit]
---

# Commit & Branch Conventions

## Commit Message Format
- Use conventional commits: `type(scope): description`
- Types: feat, fix, refactor, test, chore, docs, perf
- Scope: module or component name (e.g., `feat(agent): add tier preference`)
- Keep subject line under 72 characters
- Body explains "why" not "what"

## Autocode Commits
- Prefix with `[auto]` for autonomous execution commits
- Prefix with `[pristine]` for pre-execution quality fixes
- Prefix with `[auto-fix]` for quality gate auto-fix commits

## Branch Naming
- Feature branches: `task/<task-id>` (created by worktree system)
- Worktree branches are managed by the orchestrator

## Commit Safety
- Never use `git commit` directly — use `commit.sh --push --msg "..."` (or `commit.sh --all --push --msg "..."` for multi-repo work)
- Never force push to main
- Never amend published commits
