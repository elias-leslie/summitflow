"""Startup system brief: what is already broken, told once to the agents it concerns.

One producer for two consumers: the shared SessionStart path (``lease-hook
session`` -> ``coord.session_start``, used by Claude Code, Codex and Pi) and
``st pulse --brief``. Sources are local only: Nightshift's status file (open
findings), the newest deploy receipt and acceptance record per project, and the
current project's publication health (local DB).

Items are host-wide or belong to one project (a finding's ``details.owner``
names the project). Who sees what is policy in ``startup_brief.json``:
coordinators get host-wide items first, then every project's; other agents get
their project's items, then host-wide; coordinator-launched lanes only their
project's blocking items; native subagents nothing. A ledger keyed by
(audience, item key, first_seen) holds each shown item back for the re-show
window, so a project's items reach the first agent entering it per window and
host-wide items once per role. Silent when nothing is new. Never raises.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_DEFAULTS = Path(__file__).with_suffix(".json")
_HOST_OVERRIDE = Path("~/.config/summitflow/startup-brief.json")
_LABEL = {"critical": "CRIT", "warning": "WARN"}


@dataclass(frozen=True)
class Item:
    scope: str  # "host" or a project id
    key: str
    first_seen: str
    severity: str
    text: str
    blocking: bool = False


class _Deadline(Exception):
    pass


def load_config() -> dict[str, Any]:
    cfg = json.loads(_DEFAULTS.read_text())
    override = Path(os.environ.get("ST_STARTUP_BRIEF_CONFIG") or _HOST_OVERRIDE).expanduser()
    with suppress(OSError, ValueError):
        cfg.update(json.loads(override.read_text()))
    return cfg


# ---------------------------------------------------------------- time

def _parse(stamp: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _age(delta: timedelta) -> str:
    minutes = max(int(delta.total_seconds() // 60), 0)
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    return f"{days}d{hours}h" if days else f"{hours}h" if hours else f"{mins}m"


def _open_for(first_seen: datetime | None, now: datetime, cfg: dict[str, Any]) -> str:
    if first_seen is None:
        return ""
    delta = now - first_seen
    if delta < timedelta(days=1):
        return f" (open {_age(delta)})"
    stuck = ", stuck" if delta >= timedelta(hours=cfg["stuck_after_hours"]) else ""
    return f" (open {_age(delta)} since {first_seen.astimezone().strftime('%b %d')}{stuck})"


# ---------------------------------------------------------------- sources

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _state_root() -> Path:
    return Path(os.environ.get("SUMMITFLOW_SERVICE_STATE_ROOT") or Path.home() / ".summitflow/services")


def known_projects() -> set[str]:
    with suppress(OSError):
        return {p.name for p in (_state_root() / "projects").iterdir() if p.is_dir()}
    return set()


def finding_scope(finding: dict[str, Any], cfg: dict[str, Any], projects: set[str]) -> str:
    """The project a finding's ``details.owner`` names ("SummitFlow (backups)" -> summitflow), else "host"."""
    owner = str((finding.get("details") or {}).get("owner") or "")
    lead = _norm(owner.split("(")[0])
    if not lead or lead in {_norm(o) for o in cfg["host_wide_owners"]}:
        return "host"
    by_norm = {_norm(p): p for p in projects}
    return cfg["owner_projects"].get(lead) or by_norm.get(lead) or "host"


def nightshift_items(cfg: dict[str, Any], now: datetime, projects: set[str]) -> list[Item]:
    path = Path(cfg["nightshift_status"])
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return [Item("host", "nightshift:status-unreadable", "", "warning",
                     f"Nightshift status unreadable ({path}); host findings unknown.")]
    items: list[Item] = []
    generated = _parse(doc.get("generated_at"))
    if generated and now - generated > timedelta(minutes=cfg["nightshift_status_max_age_minutes"]):
        items.append(Item("host", "nightshift:status-stale", str(doc.get("generated_at")), "warning",
                          f"Nightshift status is {_age(now - generated)} old; findings may be out of date."))
    for f in doc.get("findings") or []:
        severity = str(f.get("severity") or "")
        if severity not in cfg["severities"] or f.get("stale"):
            continue
        scope = finding_scope(f, cfg, projects)
        if scope in cfg["skip_projects"]:
            continue
        owner = str((f.get("details") or {}).get("owner") or "")
        message = str(f.get("message") or f.get("code") or "")
        if owner and f" {owner}:" in message:  # drop the routing tail; the brief says what is broken
            message = message.split(f" {owner}:")[0]
        first_seen = str(f.get("first_seen") or "")
        tail = _open_for(_parse(first_seen), now, cfg)
        if _norm(owner.split("(")[0]) in {_norm(o) for o in cfg["owner_call_owners"]}:
            tail += " [owner's call]"
        text = f"{f.get('host') or '?'}: {message.strip()}"
        room = cfg["max_item_chars"] - len(tail)  # the age and owner tag survive truncation
        text = text if len(text) <= room else text[: room - 1] + "…"
        items.append(Item(scope, str(f.get("key") or f.get("code")), first_seen, severity, text + tail,
                          blocking=severity in cfg["lane_severities"]))
    return items


def _newest_json(directory: Path) -> dict[str, Any] | None:
    try:
        newest = max(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
        return json.loads(newest.read_text())
    except (OSError, ValueError):
        return None


def deploys_remotely(project: str) -> bool:
    """A project placed in a Proxmox guest ships through its own release path, so ST receipts say nothing."""
    from app.project_identity import get_project_identity

    with suppress(Exception):
        return bool(((get_project_identity(project) or {}).get("runtime") or {}).get("deployment"))
    return False


def deploy_item(project: str, now: datetime) -> Item | None:
    receipt = _newest_json(_state_root() / "projects" / project / "receipts")
    if not receipt or not (receipt.get("failed_phase") or receipt.get("state") == "failed"):
        return None
    if deploys_remotely(project):
        return None
    when = datetime.fromtimestamp(float(receipt.get("completed_at") or 0), UTC)
    serving = "" if receipt.get("previous_usable_release") else "; no earlier usable release"
    return Item(project, f"deploy:{project}", str(receipt.get("build_id") or ""), "critical",
                f"last deploy failed at {receipt.get('failed_phase') or 'unknown phase'} "
                f"{_age(now - when)} ago{serving}; see st service status {project}", blocking=True)


def acceptance_item(project: str, root: Path, cfg: dict[str, Any], now: datetime) -> Item | None:
    record = _newest_json(root / ".git/st/acceptance")
    if not record or record.get("state") in {"success", "reused"}:
        return None
    done = _parse(record.get("completed_at"))
    if done is None or now - done < timedelta(minutes=cfg["acceptance_failed_after_minutes"]):
        return None  # someone is likely iterating on it right now
    commit = str((record.get("source") or {}).get("commit") or "")[:10]
    return Item(project, f"acceptance:{project}", str(record.get("acceptance_id") or ""), "warning",
                f"newest acceptance ({commit or 'unknown commit'}) {record.get('state')} {_age(now - done)} ago: "
                f"{record.get('reason') or 'see st check'}", blocking=True)


def publication_item(project: str, cfg: dict[str, Any], now: datetime) -> Item | None:
    from app.services.publication_health import get_project_publication_health

    health = get_project_publication_health(project)
    observed = _parse(health.get("observed_at"))
    if "remote_authentication_unavailable" in {health.get("reason"), health.get("observed_reason")}:
        return Item("host", "github-login", str(health.get("observed_at") or ""), "warning",
                    "GitHub login on this host is broken, so no repo publishes: run `gh auth login --web` and "
                    "approve it in the signed-in Chrome (the owner only confirms GitHub's phone prompt)")
    stale = observed is not None and now - observed > timedelta(hours=cfg["publication_stale_hours"])
    if health.get("state") != "blocked" and not stale:
        return None
    repair = f"; repair task {health['repair_task_id']}" if health.get("repair_task_id") else ""
    what = (f"publication blocked ({health.get('reason')})" if health.get("state") == "blocked"
            else f"last publication observed {_age(now - observed)} ago ({health.get('state')})")  # type: ignore[operator]
    return Item(project, f"publication:{project}",
                f"{health.get('source_commit')}:{health.get('state')}:{health.get('reason')}", "warning",
                what + repair)


# ---------------------------------------------------------------- role and selection

def session_role(payload: dict[str, Any]) -> str:
    """coordinator | lane (launched by a coordinator) | subagent (native worker thread) | agent."""
    if payload.get("agent_id") or payload.get("hook_event_name") == "SubagentStart":
        return "subagent"
    widget = os.environ.get("AICO_WIDGET_ID")
    if not widget:
        return "agent"
    from . import coordinators

    desc = coordinators.sessions().get(widget) or {}
    if desc.get("coordinator"):
        return "coordinator"
    return "lane" if desc.get("coordinatorId") else "agent"


def select(items: list[Item], role: str, project: str | None, cfg: dict[str, Any]) -> list[tuple[str, Item]]:
    """(audience, item) pairs this role may see, in display order."""
    policy = cfg["roles"].get(role) or {}
    order = {"critical": 0, "warning": 1}
    items = sorted(items, key=lambda i: order.get(i.severity, 2))
    host = [("role:" + role, i) for i in items if i.scope == "host"] if policy.get("host") else []
    # Only an agent working in the project spends its first-entry brief; a coordinator's overview does not.
    mine = "role:" + role if policy.get("projects") == "all" else "project:" + (project or "")
    own = [(mine, i) for i in items if project and i.scope == project
           and (i.blocking or not policy.get("blocking_only"))] if policy.get("projects") in {"own", "all"} else []
    other = [("role:" + role, i) for i in items if i.scope not in {"host", project}] \
        if policy.get("projects") == "all" else []
    return host + own + other if policy.get("host_first") else own + host + other


@contextmanager
def _ledger(cfg: dict[str, Any]) -> Iterator[dict[str, str]]:
    path = Path(cfg["ledger"]).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            doc = {}
        yield doc
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, sort_keys=True))
        tmp.replace(path)


def fit(chosen: list[tuple[str, Item]], cfg: dict[str, Any]) -> list[tuple[str, Item]]:
    """The items that fit the line budget (header and a "+N more" line included)."""
    room = cfg["max_lines"] - 1
    return chosen if len(chosen) <= room else chosen[: room - 1]


def render(chosen: list[tuple[str, Item]], cfg: dict[str, Any]) -> list[str]:
    if not chosen:
        return []
    limit = cfg["max_item_chars"]
    shown = fit(chosen, cfg)
    lines = ["System brief (new since this window; `st pulse --brief` repeats it):"]
    for _, item in shown:
        text = item.text if len(item.text) <= limit else item.text[: limit - 1] + "…"
        lines.append(f"- {_LABEL.get(item.severity, item.severity)} {item.scope}: {text}")
    if len(shown) < len(chosen):
        lines.append(f"- +{len(chosen) - len(shown)} more: st pulse --brief")
    return lines


# ---------------------------------------------------------------- entry points

def collect(project: str | None, root: Path | None, role: str, cfg: dict[str, Any], now: datetime,
            publication: Callable[[str, dict[str, Any], datetime], Item | None] = publication_item) -> list[Item]:
    projects = known_projects() | ({project} if project else set())
    items = nightshift_items(cfg, now, projects)
    scope = cfg["roles"].get(role, {}).get("projects")
    deploys = sorted(projects) if scope == "all" else [project] if project and scope == "own" else []
    items += [i for p in deploys if p not in cfg["skip_projects"] and (i := deploy_item(p, now))]
    if project and root and scope in {"own", "all"}:
        items += [i for i in (acceptance_item(project, root, cfg, now),) if i]
        if not cfg["roles"].get(role, {}).get("blocking_only"):
            with suppress(Exception):  # the DB may be down; the rest of the brief still stands
                items += [i for i in (publication(project, cfg, now),) if i]
    return items


def brief(payload: dict[str, Any], *, record: bool = True, now: datetime | None = None) -> list[str]:
    """Brief lines for one session start (``record``: hold shown items back for the window)."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return []
    now = now or datetime.now(UTC)
    role = session_role(payload)
    if cfg["roles"].get(role, {}).get("projects") == "none" and not cfg["roles"].get(role, {}).get("host"):
        return []
    from .coord import project_for_path

    resolved = project_for_path(str(payload.get("cwd") or os.getcwd()))
    project, root = resolved if resolved else (None, None)
    chosen = select(collect(project, root, role, cfg, now), role, project, cfg)
    if not record:
        return render(chosen, cfg)
    window = timedelta(hours=cfg["reshow_hours"])
    with _ledger(cfg) as ledger:
        for key in [k for k, v in ledger.items() if (_parse(v) or now) < now - window]:
            del ledger[key]
        fresh = [(aud, i) for aud, i in chosen if f"{aud}|{i.key}|{i.first_seen}" not in ledger]
        lines = render(fresh, cfg)
        for aud, i in fit(fresh, cfg):  # an item cut by the line limit stays new
            ledger[f"{aud}|{i.key}|{i.first_seen}"] = now.isoformat()
    return lines


def hook_lines(payload: dict[str, Any]) -> list[str]:
    """SessionStart entry: within the time budget or nothing; startup never fails on the brief."""

    def expire(*_: Any) -> None:
        raise _Deadline

    try:
        budget = float(load_config().get("budget_seconds") or 1.0)
        previous = signal.signal(signal.SIGALRM, expire)
    except Exception:  # unreadable policy, or not the main thread
        return []
    signal.setitimer(signal.ITIMER_REAL, budget)
    try:
        return brief(payload)
    except Exception:  # deadline, missing sources, a broken ledger: all stay silent
        return []
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
