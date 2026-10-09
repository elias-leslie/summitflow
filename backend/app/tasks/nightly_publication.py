"""Overnight catch-up publication of committed local sources.

The owner selects a mode per project (``agent_configs.publication_mode``):
``nightly`` publishes the newest committed default-branch head once it has a
full acceptance receipt, running acceptance at night when it is missing;
``mirror`` publishes that head with outgoing history/secret verification only,
for repositories without checks; ``manual`` (the default) never runs here.

Daytime work is untouched: nothing is committed, no checkout changes, one
project runs at a time inside a quiet local window, and a project with a live
writer or a busy heavy lane is skipped until the next hourly run. A source that
failed is not retried until its head changes; it surfaces once in the morning
summary and the existing publication repair task instead.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..logging_config import get_logger
from ..storage.agent_configs import AgentConfig, get_agent_config, update_agent_config

logger = get_logger(__name__)

MODES = ("nightly", "mirror", "manual")
WINDOW_ZONE = ZoneInfo("America/New_York")
WINDOW_START_HOUR, WINDOW_END_HOUR = 1, 6
ACCEPTANCE_TIMEOUT_SECONDS = 90 * 60
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# Pending reasons worth a morning line; only workflow authority stops retries,
# because no overnight attempt can supply it.
_OWNER_REASONS = {"workflow_effects_authorization_required", "remote_authentication_unavailable"}


def publication_window_open(now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(WINDOW_ZONE)
    return WINDOW_START_HOUR <= local.hour < WINDOW_END_HOUR


def final_window_run(now: datetime | None = None) -> bool:
    return (now or datetime.now(UTC)).astimezone(WINDOW_ZONE).hour == WINDOW_END_HOUR - 1


def publication_mode(project_id: str) -> str:
    value = get_agent_config(project_id).get("publication_mode", "manual")
    return value if value in MODES else "manual"


def set_publication_mode(project_id: str, mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"publication mode must be one of {', '.join(MODES)}")
    update_agent_config(project_id, AgentConfig(publication_mode=mode))
    return mode


def publication_hold(project_id: str) -> dict[str, Any] | None:
    value = get_agent_config(project_id).get("publication_hold")
    return value if isinstance(value, dict) else None


def set_publication_hold(project_id: str, *, through: str | None, reason: str) -> dict[str, Any]:
    """Keep later commits local; ``through`` caps publication at an exact source."""
    if through is not None and not _OID.fullmatch(through):
        raise ValueError("--through requires a full commit OID")
    hold = {"through": through, "reason": reason[:200], "set_at": datetime.now(UTC).isoformat()}
    update_agent_config(project_id, AgentConfig(publication_hold=hold))
    return hold


def release_publication_hold(project_id: str) -> None:
    update_agent_config(project_id, AgentConfig(publication_hold=None))


def _git(root: Path, *arguments: str) -> str | None:
    from .backup_publish import _git as guarded_git

    result = guarded_git(root, *arguments)
    return result.stdout.strip() if result.returncode == 0 else None


def nightly_state_path(root: Path) -> Path | None:
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) / "st" / "publication" / "nightly.json" if common else None


def read_nightly_state(root: Path) -> dict[str, Any] | None:
    path = nightly_state_path(root)
    try:
        value = json.loads(path.read_text()) if path and path.is_file() and not path.is_symlink() else None
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_nightly_state(root: Path, value: dict[str, Any]) -> None:
    path = nightly_state_path(root)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".nightly-{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def select_candidate(project_id: str, root: Path, mode: str, hold: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decide what tonight would do for one project without side effects."""
    row: dict[str, Any] = {"project_id": project_id, "mode": mode, "action": "skip"}
    if mode == "manual":
        return {**row, "reason": "manual_mode"}
    if not (root / ".git").exists():
        return {**row, "reason": "not_git_repository"}
    branches = [name for name in ("main", "master") if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")]
    if len(branches) != 1:
        return {**row, "reason": "default_branch_ambiguous"}
    branch = branches[0]
    sha = _git(root, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
    upstream = _git(root, "rev-parse", "--verify", f"{branch}@{{upstream}}^{{commit}}")
    if not sha or not _OID.fullmatch(sha):
        return {**row, "reason": "source_unavailable"}
    if hold is not None:
        through = hold.get("through")
        if not through:
            return {**row, "sha": sha, "reason": "held", "detail": hold.get("reason")}
        # Publish exactly the released source; later local commits stay local.
        if _git(root, "merge-base", "--is-ancestor", str(through), sha) is None:
            return {**row, "sha": sha, "reason": "hold_source_not_on_branch", "detail": through}
        sha = str(through)
        row["held_through"] = sha
    row.update(sha=sha, branch=branch)
    if not upstream:
        return {**row, "reason": "no_upstream"}
    counts = _git(root, "rev-list", "--left-right", "--count", f"{upstream}...{sha}")
    if counts is None:
        return {**row, "reason": "ancestry_unavailable"}
    behind, ahead = map(int, counts.split())
    row.update(ahead=ahead, behind=behind)
    if behind:
        # Remote work this checkout lacks needs a person (or `st vcs reconcile`
        # for identical-tree merges); never publish around it.
        return {**row, "reason": "diverged_from_remote"}
    if not ahead:
        return {**row, "reason": "up_to_date"}
    from .backup_manual_publish import read_publication_receipt

    try:
        receipt = read_publication_receipt(root, sha)
    except (OSError, ValueError):
        return {**row, "reason": "publication_receipt_unreadable"}
    observation = (receipt or {}).get("observation") or {}
    if observation.get("publication_complete") is True:
        return {**row, "reason": "published"}
    status = str(observation.get("status") or "").lower()
    if receipt and status in {"failed", "blocked"}:
        return {**row, "reason": "awaiting_repair", "detail": observation.get("reason")}
    if receipt and observation.get("reason") == "workflow_effects_authorization_required":
        return {**row, "reason": "owner_action_required", "detail": observation.get("reason"),
                "unauthorized_workflows": observation.get("unauthorized_workflows") or []}
    state = read_nightly_state(root) or {}
    if state.get("sha") == sha and state.get("outcome") == "acceptance_failed":
        return {**row, "reason": "acceptance_failed", "detail": state.get("evidence")}
    row["resume"] = bool(receipt)
    if mode == "mirror":
        return {**row, "action": "publish", "reason": "mirror"}
    from .backup_publish import _acceptance_for_head

    accepted = _acceptance_for_head(root, sha).get("state") == "reused"
    if not accepted and row.get("held_through"):
        # Full acceptance runs only for a checkout's HEAD; an older released
        # source needs a valid receipt already (or the hold moved forward).
        return {**row, "reason": "held_source_needs_acceptance"}
    return {**row, "action": "publish" if accepted else "accept_then_publish",
            "reason": "accepted" if accepted else "acceptance_missing"}


RECENT_EDIT_SECONDS = 30 * 60


def _recently_edited(root: Path, now: float) -> bool:
    """Uncommitted edits made minutes ago mean someone is working, registered or not."""
    from .backup_publish import _git as guarded_git

    status = guarded_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    for entry in (status.stdout if status.returncode == 0 else "").split("\0"):
        if len(entry) > 3:
            try:
                if now - (root / entry[3:]).lstat().st_mtime < RECENT_EDIT_SECONDS:
                    return True
            except OSError:
                continue
    return False


def busy_reason(project_id: str, root: Path | None = None) -> str | None:
    """Defer while someone works on the project or heavy work is running."""
    import time

    from ..utils.heavy_work import HeavyWorkError, lane_activity

    if root is not None and _recently_edited(root, time.time()):
        return "recent_edits"

    try:
        if lane_activity("heavy"):
            return "heavy_lane_busy"
    except HeavyWorkError:
        return "heavy_lane_unavailable"
    from ..services.project_pulse import count_active_writers

    try:
        writers = asyncio.run(count_active_writers(project_id))
    except Exception:
        return "activity_unknown"
    return "active_writers" if writers else None


def _run_acceptance(root: Path, sha: str) -> dict[str, Any]:
    """Run canonical acceptance like an owner shell would, under its own admission."""
    environment = {key: os.environ[key] for key in ("HOME", "USER", "LOGNAME", "LANG", "XDG_RUNTIME_DIR")
                   if key in os.environ}
    environment["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    try:
        completed = subprocess.run(
            ["bash", "-lc", 'exec st check --acceptance --sha "$1"', "st-nightly-acceptance", sha],
            cwd=root, env=environment, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=ACCEPTANCE_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"state": "failed", "reason": "acceptance_timeout"}
    except OSError:
        return {"state": "failed", "reason": "acceptance_unavailable"}
    evidence = re.findall(r"acceptance evidence: (\S+\.(?:json|log))", completed.stdout + completed.stderr)
    if completed.returncode == 0:
        return {"state": "pass", "reason": "acceptance_passed", "evidence": evidence[-1] if evidence else None}
    # Only failed checks are a source finding. Inputs changing underneath the
    # run (another session editing, dependency sync) are retried next hour.
    failed = _checks_failed(root, sha)
    return {"state": "failed" if failed else "unavailable",
            "reason": "acceptance_failed" if failed else "acceptance_unavailable",
            "evidence": evidence[-1] if evidence else None}


def _checks_failed(root: Path, sha: str) -> bool:
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return False
    receipts = sorted((Path(common) / "st" / "acceptance").glob("*.json"),
                      key=lambda path: path.stat().st_mtime_ns, reverse=True)[:16]
    for path in receipts:
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and (value.get("source") or {}).get("commit") == sha:
            return value.get("reason") == "acceptance_checks_failed"
    return False


def execute_candidate(candidate: dict[str, Any], root: Path) -> dict[str, Any]:
    from ..services.publication_health import record_publication_observation
    from .backup_manual_publish import publish_project_now
    from .backup_publish import _acceptance_for_head

    project_id, sha, mode = candidate["project_id"], candidate["sha"], candidate["mode"]
    observed = datetime.now(UTC).isoformat()
    if candidate["action"] == "accept_then_publish":
        acceptance = _run_acceptance(root, sha)
        if acceptance["state"] == "unavailable":
            return {**candidate, "outcome": "deferred", "reason": acceptance["reason"],
                    "evidence": acceptance.get("evidence"), "observed_at": observed}
        if acceptance["state"] != "pass" or _acceptance_for_head(root, sha).get("state") != "reused":
            outcome = {**candidate, "outcome": "acceptance_failed", "reason": acceptance["reason"],
                       "evidence": acceptance.get("evidence"), "observed_at": observed}
            _write_nightly_state(root, outcome)
            # A failed acceptance is a source finding for the rolling repair task.
            record_publication_observation(project_id, {"status": "failed", "reason": "nightly_acceptance_failed",
                                                        "head": sha, "observed_at": observed})
            return outcome
    result = publish_project_now(project_id, sha, publication_mode=mode)
    outcome = {**candidate, "outcome": str(result.get("status") or "unknown").lower(),
               "reason": result.get("reason"), "publication_complete": bool(result.get("publication_complete")),
               "merged_source": (result.get("delivery") or {}).get("merged_source"),
               "unauthorized_workflows": result.get("unauthorized_workflows") or [],
               "evidence": result.get("evidence"), "observed_at": datetime.now(UTC).isoformat()}
    _write_nightly_state(root, outcome)
    return outcome


def _projects(project_ids: list[str] | None) -> list[tuple[str, Path]]:
    from ..storage.projects import list_projects

    rows = []
    for project in list_projects():
        project_id, root = str(project["id"]), project.get("root_path")
        if root and (project_ids is None or project_id in project_ids):
            rows.append((project_id, Path(str(root))))
    return sorted(rows)


def summary_line(row: dict[str, Any]) -> str:
    sha = str(row.get("sha") or "-")[:12]
    detail = row.get("outcome") or row.get("action")
    text = f"{row['project_id']}: {detail} ({row.get('reason')}) mode={row['mode']} source={sha}"
    if row.get("unauthorized_workflows"):
        paths = " ".join(f"--authorize-workflow {path}" for path in row["unauthorized_workflows"])
        text += f" | st vcs publish --source {row['project_id']} --sha {row.get('sha')} --now {paths}"
    return text


def needs_attention(row: dict[str, Any]) -> bool:
    return (row.get("outcome") in {"failed", "blocked", "acceptance_failed"}
            or row.get("reason") in {"diverged_from_remote", "awaiting_repair", "owner_action_required",
                                     "acceptance_failed", "publication_receipt_unreadable", "hold_source_not_on_branch",
                                     "held_source_needs_acceptance"}
            or row.get("reason") in _OWNER_REASONS)


def _notify(rows: list[dict[str, Any]]) -> None:
    attention = [row for row in rows if needs_attention(row)]
    if not attention:
        return
    from ..storage.notifications import create_notification

    try:
        create_notification(
            project_id="summitflow", notification_type="system", severity="warning",
            title=f"Nightly publication: {len(attention)} project(s) need attention",
            message="\n".join(summary_line(row) for row in attention),
            metadata={"nightly_publication": True},
            dedupe_key=f"nightly-publication-{datetime.now(WINDOW_ZONE).date().isoformat()}",
        )
    except Exception:
        logger.warning("nightly_publication_notification_failed")


def run_nightly_publication(*, dry_run: bool = False, now: datetime | None = None,
                            project_ids: list[str] | None = None, ignore_window: bool = False) -> dict[str, Any]:
    """One sequential pass; hourly runs resume pending CI and pick up new heads."""
    def window_open() -> bool:
        return ignore_window or publication_window_open(now)

    if not dry_run and not window_open():
        return {"status": "outside_window"}
    rows: list[dict[str, Any]] = []
    for project_id, root in _projects(project_ids):
        try:
            candidate = select_candidate(project_id, root, publication_mode(project_id), publication_hold(project_id))
        except Exception:
            logger.warning("nightly_publication_selection_failed", project_id=project_id)
            candidate = {"project_id": project_id, "mode": "unknown", "action": "skip", "reason": "selection_failed"}
        if candidate["action"] != "skip":
            busy = busy_reason(project_id, root)
            if busy:
                candidate = {**candidate, "action": "skip", "reason": busy}
            elif not dry_run and not window_open():
                candidate = {**candidate, "action": "skip", "reason": "window_closed"}
            elif not dry_run:
                try:
                    candidate = execute_candidate(candidate, root)
                except Exception:
                    logger.warning("nightly_publication_failed", project_id=project_id)
                    candidate = {**candidate, "outcome": "failed", "reason": "nightly_publication_unavailable"}
        rows.append(candidate)
    if not dry_run and not ignore_window and final_window_run(now):
        _notify(rows)
    return {"status": "dry_run" if dry_run else "completed", "projects": rows}
