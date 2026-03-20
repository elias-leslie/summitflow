# All project context managed by Agent Hub memory system — see ~/.claude/hooks/SessionStart.sh

## Local Snapshot Workflow

- Use `st snap "<label>"` before risky repo-local operations in the current Btrfs-backed scope.
- Use `st snaps` to inspect recent snapshots for the current lane or project scope.
- Prefer `st recover <id|name|-1> [--name <lane>]` as the default restore path. It creates a sibling recovery lane or project copy for inspection, diffing, and testing.
- Use `st rollback <id|name|-1>` only inside the current task lane when you intentionally want a destructive restore of that lane.
- Never run destructive rollback from a project root. Project-level recovery is `st recover`, not `st rollback`.
- Jenny/persona should recover into a sibling scope, inspect, and delegate verification before promoting or manually repairing.
