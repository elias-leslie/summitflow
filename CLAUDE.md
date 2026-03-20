# All project context managed by Agent Hub memory system — see ~/.claude/hooks/SessionStart.sh

## Local Snapshot Workflow

- Use `st snap "<label>"` before risky repo-local operations in the current worktree lane.
- Use `st snaps` to inspect recent quick snapshots and `st rollback <id|name|-1>` to restore the current lane.
- Quick snapshots are Git-ref based today and do not restore ignored files; use regular backups for full-environment recovery until a Btrfs phase lands.
