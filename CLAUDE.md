# All project context managed by Agent Hub memory system — see ~/.claude/hooks/SessionStart.sh

## Local Snapshot Workflow

- Use `st snap "<label>"` before risky repo-local operations in the current Btrfs-backed scope.
- Use `st snaps` to inspect recent snapshots for the current project scope.
- Prefer `st recover <id|name|-1> [--name <project>]` as the default restore path. It creates a sibling recovery project copy for inspection, diffing, and testing.
- Use `st rollback <id|name|-1>` only from the current project root when you intentionally want a destructive restore of that project state.
- Jenny/persona should recover into a sibling scope, inspect, and delegate verification before promoting or manually repairing.

## Version Control

- Use `st jj --help` as the source of truth.
- Normal work uses `st jj` and `st commit`; agents do not call raw git or raw jj.
- `st git` is only for inspection and residue repair.
