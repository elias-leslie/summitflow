"""Friction line for `st pulse`: one canonical source per metric, read-only, nothing stored.

- commits, done calls: agent shell commands and results in Agent Hub session_events
- sweep refusals: the commit guard's ``_sweep_refusals.jsonl``
- rebuilds: the detached rebuild jobs store (refusals before a job are not recorded yet)
- handshakes: the coordination ledger (it keeps 24 h)
- unpublished: ``.git/st/publication`` receipts of each shown repo
Hook timings are not recorded anywhere, so they are not reported.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

WINDOW_DAYS = 7
_OID = re.compile(r"[0-9a-f]{40}")
_JOB = re.compile(r"[0-9a-f]{32}\.json")

_SESSION_SQL = r"""
WITH commits AS (
    SELECT substring(content from 'COMMIT\[1\]:status=([A-Z_]+)') AS status,
           substring(content from 'COMMIT\[1\]:status=BLOCKED pushed=[a-z]+ detail=([a-z_]+)') AS reason
    FROM session_events
    WHERE event_type = 'tool_result' AND created_at >= now() - make_interval(days => %(days)s)
      AND content LIKE '%%COMMIT[1]:status=%%'
), dones AS (
    SELECT substring(COALESCE(tool_input->>'cmd', tool_input->>'command')
                     from 'st done[^\n;&|]*?(task-[0-9a-f]{16})') AS task
    FROM session_events
    WHERE event_type = 'tool_use' AND tool_name IN ('Bash', 'bash', 'exec_command')
      AND created_at >= now() - make_interval(days => %(days)s)
      AND COALESCE(tool_input->>'cmd', tool_input->>'command') ~ '(^|[;&|]\s*)st done '
), per_task AS (
    SELECT task, count(*) AS calls FROM dones WHERE task IS NOT NULL GROUP BY task
)
SELECT
    (SELECT count(*) FROM commits)::int,
    (SELECT count(*) FROM commits WHERE status = 'SUCCESS')::int,
    (SELECT count(*) FROM commits WHERE reason = 'quality_gates_failed')::int,
    (SELECT count(*) FROM commits WHERE reason LIKE 'source_changed%%')::int,
    (SELECT count(*) FROM per_task)::int,
    (SELECT count(*) FROM per_task WHERE calls >= 2)::int
"""


def _session_metrics() -> str:
    import psycopg

    from .db import _db_url

    with psycopg.connect(_db_url("agent-hub"), application_name="st-pulse-friction", connect_timeout=3) as conn:
        conn.execute("SET statement_timeout = '5s'")
        row = conn.execute(_SESSION_SQL, {"days": WINDOW_DAYS}).fetchone()
    total, ok, gates, changed, tasks, repeat = row or (0, 0, 0, 0, 0, 0)
    return (f"commits={ok}/{total}ok|blocked_gates={gates}|blocked_source_changed={changed}"
            f"|done_2plus_calls={repeat}/{tasks}tasks")


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _sweep_refusals() -> str:
    from ..lib import leases

    cutoff = _since(WINDOW_DAYS)
    count = 0
    try:
        with (leases.LEASES_DIR / "_sweep_refusals.jsonl").open() as handle:
            for line in handle:
                try:
                    if datetime.fromisoformat(json.loads(line)["at"]) >= cutoff:
                        count += 1
                except (ValueError, KeyError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    return f"sweep_refusals={count}"


def _rebuilds() -> str:
    from ..lib.service_release import jobs_root

    cutoff = time.time() - WINDOW_DAYS * 86400
    ok = failed = 0
    for path in jobs_root().glob("*.json"):
        if not _JOB.fullmatch(path.name):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                continue
            state = json.loads(path.read_text()).get("state")
        except (OSError, ValueError, AttributeError):
            continue
        ok += state == "succeeded"
        failed += state == "failed"
    return f"rebuilds={ok}ok/{failed}failed"


def _handshakes() -> str:
    from ..lib import coord

    return f"handshakes_24h={len(coord._load_ledger())}"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip())
    return result.stdout.strip()


def _last_published(repo: Path, project_id: str) -> str | None:
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    newest: tuple[str, str] | None = None
    for path in (common / "st" / "publication").glob("*.json"):
        if not _OID.fullmatch(path.stem):
            continue
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(value, dict) or value.get("project_id") != project_id:
            continue
        if (value.get("observation") or {}).get("status") != "published":
            continue
        observed = str(value.get("observed_at") or "")
        if newest is None or observed > newest[0]:
            newest = (observed, str(value.get("source_commit") or ""))
    return newest[1] if newest else None


def unpublished(repo: Path, project_id: str) -> str:
    """Commits on HEAD since the last published receipt, and the oldest one's age."""
    try:
        published = _last_published(repo, project_id)
        if not published:
            return f"unpublished[{project_id}]=no-receipt"
        times = _git(repo, "log", "--format=%ct", f"{published}..HEAD").split()
    except (OSError, ValueError):
        return f"unpublished[{project_id}]=unknown"
    if not times:
        return f"unpublished[{project_id}]=0"
    age_hours = (time.time() - int(times[-1])) / 3600
    return f"unpublished[{project_id}]={len(times)}commits/oldest_{age_hours:.0f}h"


def friction_line(repos: Iterable[tuple[str, Path]] = ()) -> str:
    """One line; each metric degrades to ``unavailable`` on its own."""
    parts: list[str] = []
    metrics = (("commits", _session_metrics), ("sweep_refusals", _sweep_refusals),
               ("rebuilds", _rebuilds), ("handshakes_24h", _handshakes))
    for label, metric in metrics:
        try:
            parts.append(metric())
        except Exception:
            parts.append(f"{label}=unavailable")
    parts.extend(unpublished(path, project_id) for project_id, path in repos)
    return f"FRICTION[host,{WINDOW_DAYS}d]:" + "|".join(parts)


def worktree_lines(repo: Path) -> list[str]:
    """Informal worktrees vcs doctor flags (missing, outside /srv/workspaces, dirty or unlanded)."""
    from .vcs import _worktree_rows

    lines: list[str] = []
    for tree in _worktree_rows([repo]):
        if tree["prunable"]:
            lines.append(f"WORKTREE:{tree['repo']}|{tree['path']}|missing|action=git-worktree-prune")
        elif tree["outside_workspace"] or tree["dirty"] or tree["unlanded"]:
            where = "|outside_workspace" if tree["outside_workspace"] else ""
            lines.append(f"WORKTREE:{tree['repo']}|{tree['path']}|branch={tree['branch']}|dirty={tree['dirty']}"
                         f"|unlanded={tree['unlanded']}{where}|action=land-or-hand-off-then-git-worktree-remove")
    return lines


def payload_repo(payload: dict[str, Any]) -> tuple[str, Path] | None:
    root = (payload.get("cleanup") or {}).get("path")
    path = Path(str(root)) if root else None
    return (str(payload.get("project_id") or "?"), path) if path and path.is_dir() else None
