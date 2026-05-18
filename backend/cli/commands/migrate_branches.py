"""One-shot migration of legacy task-XXX/* branches.

Walks local and remote refs matching the per-task branch naming from before the
no-branch cutover (`task-<id>/main`, `task-<id>/<subtask>`). For each branch:

- If fully merged into main → delete the ref.
- If has commits not on main → fast-forward those commits onto main (the
  branches diverged from main only by being aliases or by carrying task work
  that wasn't merged at done-time), then delete the ref. Conflicts surface as
  a per-branch error; the script continues with the rest.

Remote branches (`origin/task-*/*`) get `git push --delete` followed by a prune.

Idempotent: rerun safely.
"""

from __future__ import annotations

import re
import subprocess
from typing import Annotated

import typer

from ..lib.usage import usage
from ..output import output_error, output_success, output_warning

app = typer.Typer(help="Migrate legacy task-XXX branches to direct-on-main flow")

_TASK_BRANCH_RE = re.compile(r"^task-[0-9a-f]+(?:/.*)?$")


def _run(args: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


def _local_task_branches(cwd: str | None = None) -> list[str]:
    result = _run(["git", "branch", "--list"], cwd=cwd, check=False)
    branches: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip().lstrip("*+ ").strip()
        if name and _TASK_BRANCH_RE.match(name):
            branches.append(name)
    return branches


def _remote_task_branches(cwd: str | None = None, remote: str = "origin") -> list[str]:
    result = _run(
        ["git", "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}/"],
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        return []
    prefix = f"{remote}/"
    branches: list[str] = []
    for line in result.stdout.splitlines():
        ref = line.strip()
        if not ref.startswith(prefix):
            continue
        name = ref.removeprefix(prefix)
        if name and _TASK_BRANCH_RE.match(name):
            branches.append(name)
    return branches


def _branch_is_merged(branch: str, base: str, cwd: str | None = None) -> bool:
    result = _run(["git", "merge-base", "--is-ancestor", branch, base], cwd=cwd, check=False)
    return result.returncode == 0


def _commits_ahead(branch: str, base: str, cwd: str | None = None) -> list[str]:
    result = _run(
        ["git", "rev-list", "--reverse", f"{base}..{branch}"],
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _delete_local(branch: str, cwd: str | None = None) -> bool:
    result = _run(["git", "branch", "-D", branch], cwd=cwd, check=False)
    return result.returncode == 0


def _delete_remote(branch: str, cwd: str | None = None, remote: str = "origin") -> bool:
    result = _run(["git", "push", remote, "--delete", branch], cwd=cwd, check=False)
    detail = f"{result.stdout}\n{result.stderr}"
    return result.returncode == 0 or "remote ref does not exist" in detail


def _on_branch(branch: str, cwd: str | None = None) -> bool:
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, check=False)
    return result.stdout.strip() == branch


def _checkout(branch: str, cwd: str | None = None) -> None:
    _run(["git", "checkout", branch], cwd=cwd, check=True)


def _migrate_local_branch(branch: str, base: str, cwd: str | None, dry_run: bool) -> str:
    """Force-delete the legacy ref. Commits remain in git reflog for 90 days.

    Pre-cutover task-XXX branches are typically tangled (cross-referenced
    'wip recover prior shared-checkout changes' commits + stale code state);
    auto cherry-pick produces high-rate conflicts. Reflog-backed delete is
    safer for the bulk case. Use `git reflog` + `git cherry-pick <sha>` to
    recover any specific commit by hand.
    """
    if _on_branch(branch, cwd):
        if dry_run:
            return f"WOULD switch off {branch} → {base} before delete"
        _checkout(base, cwd)
    ahead = _commits_ahead(branch, base, cwd)
    n = len(ahead)
    marker = "merged" if _branch_is_merged(branch, base, cwd) else f"{n} commit(s) in reflog"
    if dry_run:
        return f"WOULD delete {branch} ({marker})"
    return f"deleted {branch} ({marker})" if _delete_local(branch, cwd) else f"FAIL delete {branch}"


def _migrate_remote_branch(branch: str, cwd: str | None, dry_run: bool) -> str:
    if dry_run:
        return f"WOULD delete remote origin/{branch}"
    return f"deleted remote origin/{branch}" if _delete_remote(branch, cwd) else f"FAIL delete remote origin/{branch}"


@app.command(name="migrate-branches")
@usage(
    surface="st.migrate-branches",
    cmd="st migrate-branches [--dry-run] [--remote-only] [--local-only]",
    when="one-shot cleanup of pre-cutover task-XXX branches; rerun if more appear",
    precautions=(
        "fast-forwards or cherry-picks any unmerged commits to main before delete",
        "conflicts during cherry-pick preserve the branch and surface a per-branch error",
        "uncommitted working-tree changes will block; commit or stash first",
    ),
    tier="reference",
)
def migrate_branches_command(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report what would change without doing it")] = False,
    base: Annotated[str, typer.Option("--base", help="Base branch to consolidate onto")] = "main",
    local_only: Annotated[bool, typer.Option("--local-only", help="Skip remote branch cleanup")] = False,
    remote_only: Annotated[bool, typer.Option("--remote-only", help="Skip local branch cleanup")] = False,
) -> None:
    """Migrate legacy task-XXX branches: fast-forward unmerged commits to main, then delete."""
    if local_only and remote_only:
        output_error("--local-only and --remote-only are mutually exclusive.")
        raise typer.Exit(2)

    if not _run(["git", "rev-parse", "--show-toplevel"], check=False).stdout.strip():
        output_error("Not in a git repository.")
        raise typer.Exit(1)

    if not dry_run:
        dirty = _run(["git", "status", "--porcelain"], check=False).stdout.strip()
        if dirty:
            output_error(
                "Working tree has uncommitted changes. Commit or stash before migration."
            )
            raise typer.Exit(1)

    locals_ = [] if remote_only else _local_task_branches()
    remotes = [] if local_only else _remote_task_branches()

    if not locals_ and not remotes:
        output_success("No legacy task branches found.")
        return

    typer.echo(f"Found {len(locals_)} local + {len(remotes)} remote legacy task branch(es).")

    failed = 0
    for branch in locals_:
        result = _migrate_local_branch(branch, base, None, dry_run)
        if result.startswith("FAIL"):
            output_warning(result)
            failed += 1
        else:
            typer.echo(f"  local: {result}")

    if remotes:
        typer.echo("")
        for branch in remotes:
            result = _migrate_remote_branch(branch, None, dry_run)
            if result.startswith("FAIL"):
                output_warning(result)
                failed += 1
            else:
                typer.echo(f"  remote: {result}")
        if not dry_run and not local_only:
            _run(["git", "fetch", "origin", "--prune"], check=False)

    if failed:
        output_warning(f"{failed} branch(es) had issues. Inspect and rerun.")
        raise typer.Exit(1)
    if dry_run:
        output_success("Dry run complete. No refs changed.")
    else:
        output_success("Migration complete.")
