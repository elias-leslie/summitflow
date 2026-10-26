"""`st backup`: what is backed up, how fresh it is, and how to get it back.

btrbk keeps the local points on the T7; one daily restic job copies those snapshots to Google Drive.
Every command here reads that state or restores from it; nothing is scheduled per source.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from ..lib.usage import usage
from ..output import output_error
from ..output_context import OutputContext
from .backup_formatters import (
    format_size,
    local_time,
    render_contents,
    render_job_record,
    render_old_snapshots,
    render_snapshots,
    render_status,
)
from .backup_native_host import app as native_host_app

app = typer.Typer(
    help="Backup health, Google Drive snapshots, run-now and restore.",
    epilog=(
        "btrbk keeps points on the T7 every 4 hours; one daily copy goes to Google Drive. Start with 'st backup status'. "
        "The old per-source commands (create, sources, schedule, storage, infra, testbed) are gone; 'st backup old' reads what they left."
    ),
    no_args_is_help=True,
)
old_app = typer.Typer(help="Backups from before the daily job. They age out on their own.", no_args_is_help=True)
app.add_typer(native_host_app, name="host")
app.add_typer(old_app, name="old")

SELECTOR_HELP = "A project name, postgres, redis or an absolute path"
JSON_HELP = "Print raw JSON"


@app.callback()
def backup_callback(ctx: typer.Context) -> None:
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _fail(message: str) -> typer.Exit:
    output_error(message)
    return typer.Exit(1)


def _emit(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _plain(message: str) -> str:
    """restic reports errors as JSON lines; show just its sentence."""
    match = re.search(r'"message":"(.*?)(?:\\n|")', message)
    return f"{message.split('{', 1)[0].strip()} {match.group(1)}".strip() if match else message


def _guard(action):
    """Run ``action``; a Google Drive problem becomes one plain error line."""
    from app.tasks.backup_offsite import OffsiteError

    try:
        return action()
    except OffsiteError as exc:
        raise _fail(_plain(str(exc))) from exc


@app.command("status")
@usage(
    surface="st.backup.status",
    cmd="st backup status",
    when="check that backups are current, or see what the T7 and Google Drive hold and when they last worked",
    precautions=(
        "the first line says 'All backups current.' or lists the real problems",
        "btrbk keeps 7 days on the T7; the daily Google Drive job is the offsite copy",
    ),
    examples=("st backup status", "st backup status --json"),
    task_types=("devops", "backup"),
    tier="reference",
)
def status(json_output: Annotated[bool, typer.Option("--json", help=JSON_HELP)] = False) -> None:
    """Are backups current? Then the T7 points and space, then the Google Drive job."""
    from app.tasks import backup_overview

    try:
        overview = backup_overview.overview(points=True)
    except Exception:
        overview = backup_overview.overview()
    if json_output:
        _emit(overview)
    else:
        typer.echo(render_status(overview))
    if overview["problems"]:
        raise typer.Exit(1)


@app.command("list")
def list_snapshots(
    selector: Annotated[str | None, typer.Argument(help=SELECTOR_HELP + "; without it, the latest snapshot of each job")] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Most snapshots to show")] = 20,
    json_output: Annotated[bool, typer.Option("--json", help=JSON_HELP)] = False,
) -> None:
    """Google Drive snapshots, newest first."""
    from app.tasks import backup_offsite_restore as restore_tasks

    def fetch() -> list[dict[str, Any]]:
        if selector:
            return restore_tasks.snapshots(selector, limit=limit)
        newest: dict[str, dict[str, Any]] = {}
        for row in restore_tasks.snapshots(limit=1000):
            newest.setdefault(row.get("job") or row["id"], row)
        return sorted(newest.values(), key=lambda row: row["time"], reverse=True)[:limit]

    rows = _guard(fetch)
    if json_output:
        _emit(rows)
    else:
        typer.echo(render_snapshots(rows))


def _job_names() -> set[str]:
    from app.tasks import backup_offsite

    return set(backup_offsite.read_state().get("jobs") or {})


def _entries(selector: str, snapshot: dict[str, Any], resolved: dict[str, str]) -> tuple[list[dict[str, Any]], str | None]:
    """What sits directly under the selected path in the snapshot. A project is listed in full so folder sizes add up."""
    from app.tasks import backup_offsite_restore as restore_tasks
    from app.tasks.backup_offsite import _env, _restic_args
    from app.tasks.backup_proc import run_process

    repo = restore_tasks.open_repo()
    base = resolved["path"]
    recursive = resolved["kind"] == "project"
    args = ["ls", "--long", *(["--recursive"] if recursive else []), snapshot["full_id"], base]
    result = run_process(_restic_args(repo.target, repo.runtime, *args), env=_env(repo.target, repo.runtime, root=False), timeout=900, capture=True)
    if result.returncode:
        return [], "The listing did not finish; the snapshot details above still hold."
    prefix = base.rstrip("/") + "/"
    totals: dict[str, dict[str, Any]] = {}
    own: dict[str, Any] | None = None
    for line in result.stdout.splitlines():
        try:
            node = json.loads(line)
        except ValueError:
            continue
        if node.get("struct_type") != "node":
            continue
        path = str(node.get("path") or "")
        if path == base:
            own = node
            continue
        if not path.startswith(prefix):
            continue
        name = path[len(prefix):].split("/", 1)[0]
        entry = totals.setdefault(name, {"name": name, "bytes": 0, "files": 0 if recursive else None})
        entry["bytes"] += int(node.get("size") or 0)
        if recursive and node.get("type") == "file":
            entry["files"] += 1
    if not totals and own is not None and own.get("type") == "file":
        return [{"name": Path(base).name, "bytes": int(own.get("size") or 0), "files": None}], None
    note = None if recursive else "Folder sizes are listed only for a project; ask for a project name to see them."
    return list(totals.values()), note


@app.command("show")
def show(
    selector: Annotated[str | None, typer.Argument(help=SELECTOR_HELP + ", or a job (workspaces, home, root, pve-*); without it, every job's last good run")] = None,
    json_output: Annotated[bool, typer.Option("--json", help=JSON_HELP)] = False,
) -> None:
    """What the latest Google Drive snapshot holds: tags, sizes and the top-level contents."""
    from app.tasks import backup_offsite
    from app.tasks import backup_offsite_restore as restore_tasks

    jobs = backup_offsite.read_state().get("jobs") or {}
    if selector is None or selector in jobs:
        chosen = {selector: jobs[selector]} if selector else jobs
        if not chosen:
            raise _fail("The Google Drive job has not made a snapshot yet. Run 'st backup status'.")
        if json_output:
            _emit(chosen)
        else:
            typer.echo("\n".join(line for name, job in sorted(chosen.items()) for line in render_job_record(name, job)))
        return

    def fetch() -> dict[str, Any]:
        resolved = restore_tasks.resolve(selector)
        rows = restore_tasks.snapshots(selector, limit=1)
        if not rows:
            raise backup_offsite.OffsiteError(f"No Google Drive snapshot has {selector}. Run 'st backup list' to see what is there.")
        repo = restore_tasks.open_repo()
        detail = repo.json("snapshots", rows[0]["full_id"])
        tags = (detail[0].get("tags") if detail else None) or []
        entries, note = _entries(selector, rows[0], resolved)
        return {"snapshot": {**rows[0], "tags": tags}, "path": resolved["path"], "entries": entries, "note": note}

    found = _guard(fetch)
    if json_output:
        _emit(found)
    else:
        typer.echo(render_contents(found["snapshot"], found["entries"], base=found["path"], note=found["note"]))


@app.command("run")
def run(
    offsite: Annotated[bool, typer.Option("--offsite", help="Also make today's Google Drive copy now, even if one is done")] = False,
) -> None:
    """Start a backup run now, the same one the timer starts. It runs in the background."""
    from app.tasks import backup_run

    result = backup_run.request_run(with_offsite=offsite)
    if not result["started"]:
        raise _fail(f"The backup run did not start: {result.get('error') or 'unknown error'}")
    typer.echo(f"Started {result['unit']}" + (" with the Google Drive copy" if offsite else "") + ". Follow it with 'st backup status'.")


def _parse_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _fail(f"--at needs a date or time like 2026-10-25 or 2026-10-25T14:30, not {value!r}") from exc
    return when if when.tzinfo else when.astimezone()


@app.command("restore")
@usage(
    surface="st.backup.restore",
    cmd="st backup restore SELECTOR --to DIR",
    when="get a project, postgres or redis dump, or a path back from the Google Drive backup",
    precautions=(
        "restores only into a new or empty directory, never over the live path",
        "start with --dry-run to see which snapshot would be used",
        "the restore is read back and verified before it reports success",
    ),
    examples=("st backup restore aico --to /srv/scratch/aico-back --dry-run", "st backup restore postgres --to /srv/scratch/pg --at 2026-10-25"),
    task_types=("devops", "backup", "restore"),
    tier="reference",
)
def restore(
    selector: Annotated[str, typer.Argument(help=SELECTOR_HELP)],
    to: Annotated[Path, typer.Option("--to", help="New or empty directory to restore into")],
    snapshot: Annotated[str | None, typer.Option("--snapshot", help="Snapshot ID from 'st backup list'")] = None,
    at: Annotated[str | None, typer.Option("--at", help="Newest snapshot at or before this time")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show which snapshot would be restored; write nothing")] = False,
    json_output: Annotated[bool, typer.Option("--json", help=JSON_HELP)] = False,
) -> None:
    """Restore a project, a database dump or a path from Google Drive into a new directory."""
    from app.tasks import backup_offsite_restore as restore_tasks

    if snapshot and at:
        raise _fail("Use --snapshot or --at, not both.")
    result = _guard(lambda: restore_tasks.restore(selector, to.expanduser(), snapshot=snapshot, at=_parse_at(at), dry_run=dry_run))
    if json_output:
        _emit(result)
        return
    source = f"snapshot {result['snapshot']} from {local_time(result['snapshot_time'])}"
    if dry_run:
        typer.echo(f"Would restore {selector} from {source} into {result['target']}. Nothing written.")
        return
    typer.echo(f"Restored {selector} from {source}, checked against Google Drive.")
    typer.echo(f"Files are at {result['restored']}" + (f" ({format_size(result['bytes'])})" if result.get("bytes") else ""))


@app.command("safety")
def safety() -> None:
    """Deletion breakers: retention runs that were refused for removing too much, and any owner approvals."""
    from app.tasks.backup_safety import read_status

    _emit(read_status())


@app.command("approve-deletion")
def approve_deletion(
    kind: Annotated[str, typer.Argument(help="Breaker kind from 'st backup safety', like btrbk-target")],
    target: Annotated[str, typer.Option("--target", help="Target of the refused run, from 'st backup safety'")],
    owner_approved: Annotated[str, typer.Option("--owner-approved", help="The owner's approval from chat, in their words, with the date")],
) -> None:
    """Let the next run of one refused oversized deletion through, once. Ask the owner in chat first."""
    from app.tasks.backup_safety import approve_deletion as approve

    try:
        _emit(approve(kind, target=target, owner_approved=owner_approved))
    except ValueError as exc:
        raise _fail(str(exc)) from exc


# ---- old backups ---------------------------------------------------------------------------------------------------

@old_app.command("list")
def old_list(
    source: Annotated[str | None, typer.Argument(help="Old source ID, like the project name; without it, all")] = None,
    where: Annotated[str, typer.Option("--where", help="drive (Google Drive) or local (the old restic repository on the T7)")] = "drive",
    limit: Annotated[int, typer.Option("--limit", "-l", help="Most snapshots to show")] = 30,
    json_output: Annotated[bool, typer.Option("--json", help=JSON_HELP)] = False,
) -> None:
    """Old per-source snapshots. The first read of the Drive index can take minutes."""
    from app.tasks import backup_offsite
    from app.tasks import backup_offsite_restore as restore_tasks

    rows = _guard(lambda: restore_tasks.legacy_snapshots(source, where=where, limit=limit))
    if json_output:
        _emit(rows)
        return
    legacy = backup_offsite.read_state().get("legacy") or {}
    if where == "local":
        typer.echo(f"This is the old restic repository on the T7: {legacy.get('local_repository_path') or '-'}, "
                   f"{format_size(legacy.get('local_repository_bytes'))}. Nothing writes to it any more; the owner can delete it.")
    else:
        typer.echo("Old Google Drive snapshots from before the daily job. They age out on their own.")
    typer.echo(render_old_snapshots(rows))


@old_app.command("restore")
def old_restore(
    snapshot: Annotated[str, typer.Argument(help="Snapshot ID from 'st backup old list'")],
    to: Annotated[Path, typer.Option("--to", help="New or empty directory to restore into")],
    where: Annotated[str, typer.Option("--where", help="drive or local")] = "drive",
    include: Annotated[str | None, typer.Option("--include", help="Restore only this path inside the snapshot")] = None,
) -> None:
    """Restore an old snapshot as it was stored, into a new directory."""
    from app.tasks import backup_offsite_restore as restore_tasks

    result = _guard(lambda: restore_tasks.restore_legacy(snapshot, to.expanduser(), where=where, include=include))
    typer.echo(f"Restored old snapshot {result['snapshot']} ({result['where']}) into {result['target']}, checked against the repository.")

