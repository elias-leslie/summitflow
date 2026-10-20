"""One read-only answer to "may I disrupt X?" for host-level actions (reboot, service restart, package run).

Collects, from SummitFlow's own stores: live agents (registered coordination identities whose harness is alive, plus
active Agent Hub sessions on this host), the handshake replies to the caller's requests (objections and ETAs), repo
holds and op marks (acceptance/deploy), file leases, and running backups (SummitFlow backup rows, backup units and
backup processes on this host). The verdict is advisory and conservative: a part that could not be read is reported
in ``unknown`` and keeps ``clear`` false. Nightshift's coordination precheck calls it as ``st sessions may-disrupt``.
"""

from __future__ import annotations

import re
import socket
import subprocess
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from . import coord, coord_lineage, leases

SCHEMA = "summitflow.may-disrupt.v1"
HOST_TARGET = "host"
# Backup work on this host. Rebuilds are covered by op marks; package runs are the caller's own host policy.
BACKUP_UNIT = re.compile(r"(backup|restic|vzdump|borg|btrbk|pbs-|blackbox-archive)", re.I)
BACKUP_PROC = re.compile(r"(^|[\s/])(restic|borg|vzdump|btrbk)(\s|$)|\bst backup\b")
SHELL_C = re.compile(r"^\S*/?(ba|da|z)?sh\s+(-\S+\s+)*-\S*c\b")
_PROVIDER_PREFIX = {"claude_code": "cc", "claude-code": "cc", "claude": "cc", "anthropic": "cc",
                    "codex": "codex", "codex_cli": "codex", "openai": "codex", "pi": "pi", "antigravity": "agy"}

Runner = Callable[[list[str]], tuple[int, str]]


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, type(exc).__name__
    return proc.returncode, proc.stdout


def in_scope(target: str, project: str) -> bool:
    """A host target covers every project; a project or unit target covers its own project (boundary-aware)."""
    if target == HOST_TARGET:
        return True
    return bool(project) and (target == project or (target.startswith(project) and target[len(project)] in "-@."))


def agent_id_for(provider: str, session_id: str) -> str:
    prefix = _PROVIDER_PREFIX.get(provider, provider)
    return f"{prefix}:{leases.short_id(session_id)}" if prefix and session_id else ""


def live_agents(sessions: Iterable[dict[str, Any]] | None, host: str) -> list[dict[str, Any]]:
    """Live registered identities, merged with active Agent Hub sessions on this host.

    A marked main thread represents its live anchor's workers and predecessors;
    the latest main registration is the current parent after a context reset.
    Only that verified parent carries ``pid`` (int) and ``pid_start`` (kernel
    start tick string). Unmarked families and unregistered Hub evidence remain
    separate, without a process claim.
    """
    out: dict[str, dict[str, Any]] = {}
    identities = coord_lineage.load_doc().get("identities") or {}
    families: dict[str, dict[str, dict[str, Any]]] = {}
    alive: dict[str, bool] = {}
    for aid, row in identities.items():
        if not isinstance(row, dict):
            continue
        anchor = row.get("anchor")
        if anchor not in alive:
            alive[anchor] = coord_lineage.anchor_alive(anchor)
        if alive[anchor]:
            families.setdefault(anchor, {})[aid] = row

    parents: dict[str, str] = {}
    for anchor, family in families.items():
        mains = [aid for aid, row in family.items() if row.get("main") is True]
        parent = max(mains, key=lambda aid: (family[aid].get("first") or "", aid)) if mains else None
        for aid, row in family.items():
            if parent:
                parents[aid] = parent
                if aid != parent:
                    continue
            out[aid] = {"agent": aid, "provider": row.get("provider"), "session": row.get("session"),
                        "project": None, "source": "coordination", "last_seen": row.get("last")}
            if parent:
                pid, _, start = anchor.partition(":")
                out[aid].update(pid=int(pid), pid_start=start)
    for s in sessions or ():
        if s.get("status") != "active" or s.get("host") not in (None, "", host):
            continue
        aid = agent_id_for(str(s.get("provider") or s.get("session_type") or ""), str(s.get("id") or ""))
        if not aid:
            continue
        aid = parents.get(aid, aid)
        row = out.setdefault(aid, {"agent": aid, "provider": s.get("provider"), "session": s.get("id"),
                                   "project": None, "source": "agent_hub", "last_seen": None})
        row["project"] = s.get("project_id") or row["project"]
        if row["source"] == "coordination":
            row["source"] = "coordination+agent_hub"
    return sorted(out.values(), key=lambda r: r["agent"])


def handshakes(request_ids: Iterable[str] | None, now: datetime, *, everyone: bool = False) -> list[dict[str, Any]]:
    """Requests by id, or every request the caller sent when none are named, with reply state.

    ``everyone`` (the Runtime page) lists every request still open or acked, whoever sent it.
    """
    wanted = {r for r in (request_ids or ()) if r}
    mine = leases.self_ids()
    with leases._lock("_coord"):
        rows = coord._load_ledger()
    out = []
    for row in rows:
        if wanted and row.get("id") not in wanted:
            continue
        if everyone and not wanted and row.get("state") == "closed":
            continue
        if not wanted and not everyone and row.get("from") not in mine:
            continue
        reply = "none"
        if row.get("state") == "closed" and row.get("withdrawn"):
            reply = "withdrawn"
        elif row.get("intent") in ("yes", "no"):
            reply = row["intent"]
        elif row.get("intent") == "eta":
            reply = "eta"
        eta_until = None
        if reply == "eta" and row.get("acked_at") and row.get("eta_min") is not None:
            eta_until = (datetime.fromisoformat(row["acked_at"]) + timedelta(minutes=int(row["eta_min"])))
        out.append({
            "id": row.get("id"), "to": row.get("to"), "from": row.get("from"), "state": row.get("state"),
            "reply": reply, "acked_by": row.get("acked_by"), "note": row.get("note"), "eta_min": row.get("eta_min"),
            "eta_until": eta_until.isoformat() if eta_until else None,
            "eta_running": bool(eta_until and eta_until > now), "created": row.get("created"),
            "acked_at": row.get("acked_at"),
        })
    return out


def marks_and_leases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    holds: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for project_id in leases.all_projects():
        try:
            live = leases.list_active(project_id, kinds=("op", "hold", "file"))
        except OSError:
            continue
        for lease in live:
            base = {"project": project_id, "holder": lease.agent_id, "since": lease.acquired_at,
                    "idle": leases.idle_string(lease)}
            if lease.kind in ("hold", "op"):
                purpose = None if lease.sensitive else lease.purpose
                holds.append({**base, "kind": lease.kind, "purpose": purpose})
            else:
                files.append({**base, "paths": len(lease.globs), "task": None if lease.sensitive else lease.task_id})
    return holds, files


def local_backup_work(run: Runner) -> tuple[list[str], list[str], list[str]]:
    """(active backup units, backup processes, unknowns) on this host."""
    unknown: list[str] = []
    rc, out = run(["systemctl", "list-units", "--type=service", "--state=active,activating", "--no-legend",
                   "--plain", "--no-pager"])
    units = [ln.split()[0] for ln in out.splitlines() if ln.split() and BACKUP_UNIT.search(ln.split()[0])] if rc == 0 else []
    if rc != 0:
        unknown.append("system units unreadable")
    urc, uout = run(["systemctl", "--user", "list-units", "--type=service", "--state=active,activating",
                     "--no-legend", "--plain", "--no-pager"])
    if urc == 0:
        units += [f"user:{ln.split()[0]}" for ln in uout.splitlines() if ln.split() and BACKUP_UNIT.search(ln.split()[0])]
    prc, ps = run(["ps", "-eo", "args="])
    procs = [ln.strip()[:120] for ln in ps.splitlines()
             if BACKUP_PROC.search(ln.strip()) and not SHELL_C.match(ln.strip())] if prc == 0 else []
    if prc != 0:
        unknown.append("process table unreadable")
    return units, procs[:20], unknown


def snapshot(
    target: str = HOST_TARGET,
    *,
    request_ids: Iterable[str] | None = None,
    everyone: bool = False,
    sessions: Callable[[], list[dict[str, Any]]] | None = None,
    running_backups: Callable[[], list[dict[str, Any]]] | None = None,
    run: Runner = _run,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    host = socket.gethostname()
    unknown: list[str] = []

    session_rows: list[dict[str, Any]] | None = None
    if sessions is not None:
        try:
            session_rows = sessions()
        except Exception as exc:  # SummitFlow API down: registered identities still answer
            unknown.append(f"agent hub sessions unavailable ({type(exc).__name__})")
    agents = live_agents(session_rows, host)

    replies = handshakes(request_ids, now, everyone=everyone)
    ready = {r["acked_by"] or r["to"] for r in replies if r["reply"] == "yes"}
    holds, files = marks_and_leases()

    backups_rows: list[dict[str, Any]] = []
    if running_backups is not None:
        try:
            backups_rows = running_backups()
        except Exception as exc:
            unknown.append(f"summitflow backup records unavailable ({type(exc).__name__})")
    units, procs, local_unknown = local_backup_work(run)
    unknown += local_unknown

    blocking: list[str] = []
    for r in replies:
        if r["reply"] == "no":
            blocking.append(f"{r['acked_by'] or r['to']} objected" + (f": {r['note']}" if r.get("note") else ""))
        elif r["eta_running"]:
            blocking.append(f"{r['acked_by'] or r['to']} asked to wait until {r['eta_until']}")
    for h in holds:
        if in_scope(target, h["project"]) and not (h["kind"] == "hold" and h["holder"] in ready):
            what = "deploy/acceptance running" if h["kind"] == "op" else f"repo hold ({h['purpose'] or 'busy'})"
            blocking.append(f"{h['project']}: {what} by {h['holder']}")
    blocking += [f"backup {b.get('source_id') or b.get('project_id') or b.get('id')} running" for b in backups_rows]
    blocking += [f"unit {u} running" for u in units]
    blocking += [f"process: {p}" for p in procs]

    pending = [r["to"] for r in replies if r["state"] == "open" and r["reply"] in ("none", "eta") and not r["eta_running"]]
    asked = {r["to"] for r in replies} | {r["acked_by"] for r in replies if r.get("acked_by")}
    return {
        "schema": SCHEMA,
        "target": target,
        "host": host,
        "generated_at": now.isoformat(),
        "clear": not blocking and not unknown,
        "blocking": blocking,
        "unknown": unknown,
        "agents": agents,
        "unasked": [a["agent"] for a in agents if a["agent"] not in asked],
        "handshakes": replies,
        "awaiting_reply": pending,
        "holds": holds,
        "leases": files,
        "backups": {
            "summitflow": [{k: b.get(k) for k in ("id", "source_id", "project_id", "status", "started_at", "created_at")}
                           for b in backups_rows],
            "units": units,
            "processes": procs,
        },
    }
