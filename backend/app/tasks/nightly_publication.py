"""Hourly publication of committed local sources by plain fast-forward push.

The owner selects a mode per project (``agent_configs.publication_mode``):
``nightly`` and ``mirror`` both publish hourly; ``manual`` (the default) never
runs here. A private repository publishes its committed default-branch head;
a public one (or any non-GitHub remote) publishes its newest commit with a
valid full acceptance receipt. The outgoing history/secret verifier and the
workflow-effects gate run before every push.

Nothing is committed and no checkout changes. Only an owner publication hold
defers a project; a push is cheap, so live editing, agent repo holds or heavy
work elsewhere never do. A source that failed is not retried until a newer
commit replaces it; it surfaces in the daily attention notification and the
existing publication repair task instead. Once a night each project also
checks that GitHub's branch still contains the last published local commit
and re-reads CodeQL for the commit GitHub now holds (analysis finishes well
after a push, so it is never read right after one).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..logging_config import get_logger
from ..storage.agent_configs import AgentConfig, get_agent_config, update_agent_config

logger = get_logger(__name__)

MODES = ("nightly", "mirror", "manual")
WINDOW_ZONE = ZoneInfo("America/New_York")
CONTAINMENT_HOUR = 3  # local hour of the nightly GitHub containment and CodeQL check
ACCEPTED_SEARCH_LIMIT = 64
STALE_UNACCEPTED_SECONDS = 24 * 3600  # public commits waiting this long on acceptance need attention
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_ATTENTION_REASONS = {"diverged_from_remote", "awaiting_repair", "owner_action_required",
                      "publication_receipt_unreadable", "hold_source_not_on_branch",
                      "remote_branch_missing", "remote_not_containing_published", "remote_containment_unverified",
                      "remote_authentication_unavailable", "remote_visibility_unknown",
                      "workflow_effects_authorization_required"}


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


def _newest_accepted(root: Path, upstream: str, sha: str) -> str | None:
    """Newest first-parent commit after ``upstream`` with a valid full acceptance receipt."""
    from .backup_publish import _acceptance_for_head

    for commit in (_git(root, "rev-list", "--first-parent", f"--max-count={ACCEPTED_SEARCH_LIMIT}",
                        f"{upstream}..{sha}") or "").split():
        if _acceptance_for_head(root, commit).get("state") == "reused":
            return commit
    return None


def _identity(root: Path, branch: str) -> tuple[str, int | None, str] | None:
    from ..services.git.utils import network_repository_identity

    remote = _git(root, "config", "--get", f"branch.{branch}.remote")
    url = remote and _git(root, "remote", "get-url", "--push", remote)
    return network_repository_identity(url) if url else None


def _public(root: Path, branch: str) -> tuple[bool | None, str | None]:
    """Repository visibility, or None with the reason it is unknown.

    Any non-GitHub remote counts as public.
    """
    from cli.lib.github_publish import GitHubError

    from .backup_publish import is_public, remote_repository

    identity = _identity(root, branch)
    if identity is None:
        return True, None
    try:
        return is_public(remote_repository(root, identity)), None
    except GitHubError as exc:
        return None, exc.reason
    except Exception:
        return None, "remote_visibility_unknown"


def _waiting_seconds(root: Path, upstream: str, sha: str) -> int | None:
    """How long the oldest unpublished commit has waited, by committer time."""
    import time

    times = (_git(root, "log", "--first-parent", "--format=%ct", f"{upstream}..{sha}") or "").split()
    return int(time.time()) - int(times[-1]) if times else None


def select_candidate(project_id: str, root: Path, mode: str, hold: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decide what this hour would publish for one project without side effects."""
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
        # Publish at most the released source; later local commits stay local.
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
        # Remote work this checkout lacks needs a person; never publish around it.
        return {**row, "reason": "diverged_from_remote"}
    if not ahead:
        return {**row, "reason": "up_to_date"}
    public, unknown = _public(root, branch)
    if public is None:
        return {**row, "reason": unknown or "remote_visibility_unknown"}
    row["visibility"] = "public" if public else "private"
    if public:
        accepted = _newest_accepted(root, upstream, sha)
        if accepted is None:
            return {**row, "reason": "no_accepted_commit", "waiting_seconds": _waiting_seconds(root, upstream, sha)}
        row.update(sha=accepted, unaccepted_later=sha != accepted)
    from .backup_manual_publish import read_publication_receipt

    try:
        receipt = read_publication_receipt(root, row["sha"])
    except (OSError, ValueError):
        return {**row, "reason": "publication_receipt_unreadable"}
    observation = (receipt or {}).get("observation") or {}
    if observation.get("publication_complete") is True:
        return {**row, "reason": "published"}
    # A source that failed is not retried until a new commit replaces it.
    if receipt and str(observation.get("status") or "").lower() in {"failed", "blocked"}:
        return {**row, "reason": "awaiting_repair", "detail": observation.get("reason")}
    if receipt and observation.get("reason") == "workflow_effects_authorization_required":
        return {**row, "reason": "owner_action_required", "detail": observation.get("reason"),
                "unauthorized_workflows": observation.get("unauthorized_workflows") or []}
    return {**row, "action": "publish", "reason": "accepted" if public else "private_head"}


def execute_candidate(candidate: dict[str, Any], root: Path) -> dict[str, Any]:
    from .backup_manual_publish import publish_project_now

    result = publish_project_now(candidate["project_id"], candidate["sha"])
    outcome = {**candidate, "outcome": str(result.get("status") or "unknown").lower(),
               "reason": result.get("reason"), "publication_complete": bool(result.get("publication_complete")),
               "unauthorized_workflows": result.get("unauthorized_workflows") or [],
               "evidence": result.get("evidence"), "observed_at": datetime.now(UTC).isoformat()}
    _write_nightly_state(root, outcome)
    return outcome


def remote_containment(project_id: str, root: Path, mode: str) -> dict[str, Any] | None:
    """Attention row when GitHub's branch no longer contains the last published local commit."""
    if mode == "manual" or not (root / ".git").exists():
        return None
    from .backup_publish import _git as guarded_git

    branch = next((name for name in ("main", "master")
                   if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")), None)
    remote = branch and _git(root, "config", "--get", f"branch.{branch}.remote")
    published = branch and _git(root, "rev-parse", "--verify", "--quiet", f"{branch}@{{upstream}}^{{commit}}")
    if not remote or not published:
        return None
    # The tracking ref moves only on a push or fetch. A fetched rewrite
    # surfaces hourly as diverged_from_remote and a fetched reset is
    # re-pushed, so the tracking ref is the published baseline here.
    row = {"project_id": project_id, "mode": mode, "action": "check", "sha": published}
    unverified = {**row, "reason": "remote_containment_unverified"}
    destination = f"refs/heads/{branch}"
    try:
        listed = guarded_git(root, "ls-remote", "--refs", remote, destination)
        if listed.returncode:
            return unverified
        rows = listed.stdout.split()
        if not rows:
            return {**row, "reason": "remote_branch_missing"}
        live = rows[0]
        if live == published:
            return None
        if guarded_git(root, "cat-file", "-e", f"{live}^{{commit}}").returncode and \
                guarded_git(root, "fetch", "--no-tags", remote, destination).returncode:
            return unverified
        ancestry = guarded_git(root, "merge-base", "--is-ancestor", published, live).returncode
    except Exception:
        return unverified
    if ancestry == 0:
        return None
    if ancestry != 1:
        return unverified
    return {**row, "reason": "remote_not_containing_published", "detail": live}


def observe_codeql(project_id: str, root: Path, mode: str) -> None:
    """Record CodeQL for the commit GitHub's default branch holds now.

    Runs once a night, long after the day's pushes were analyzed, so it can
    record success as well as open alerts. Pending or unavailable coverage
    records nothing and never clears a retained finding.
    """
    if mode == "manual" or not (root / ".git").exists():
        return
    branch = next((name for name in ("main", "master")
                   if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")), None)
    identity = _identity(root, branch) if branch else None
    if identity is None or identity[0] != "github.com" or identity[1] is not None:
        return
    from ..services.publication_security import observe_codeql as observe
    from ..services.publication_security import record_codeql_observation

    try:
        record_codeql_observation(root, observe(root, identity[2]), project_id=project_id)
    except Exception:
        logger.warning("nightly_publication_codeql_failed", project_id=project_id)


def _projects(project_ids: list[str] | None) -> list[tuple[str, Path]]:
    from ..project_identity import get_project_lifecycles
    from ..storage.projects import list_projects

    projects = list_projects()
    lifecycles = get_project_lifecycles([str(project["id"]) for project in projects])
    rows = []
    for project in projects:
        project_id, root = str(project["id"]), project.get("root_path")
        if lifecycles.get(project_id) == "retired":
            continue
        if root and (project_ids is None or project_id in project_ids):
            rows.append((project_id, Path(str(root))))
    return sorted(rows)


def summary_line(row: dict[str, Any]) -> str:
    sha = str(row.get("sha") or "-")[:12]
    detail = row.get("outcome") or row.get("action")
    text = f"{row['project_id']}: {detail} ({row.get('reason')}) mode={row['mode']} source={sha}"
    if row.get("unauthorized_workflows"):
        paths = " ".join(f"--authorize-workflow {path}" for path in row["unauthorized_workflows"])
        text += f" | st vcs publish --source {row['project_id']} --sha {row.get('sha')} {paths}"
    return text


def needs_attention(row: dict[str, Any]) -> bool:
    if row.get("reason") == "no_accepted_commit":
        return (row.get("waiting_seconds") or 0) >= STALE_UNACCEPTED_SECONDS
    return row.get("outcome") in {"failed", "blocked"} or row.get("reason") in _ATTENTION_REASONS


def _notify(rows: list[dict[str, Any]], now: datetime) -> None:
    """One notification per distinct attention set per day."""
    attention = [row for row in rows if needs_attention(row)]
    if not attention:
        return
    from ..storage.notifications import create_notification

    lines = [summary_line(row) for row in attention]
    digest = hashlib.sha256("\n".join(sorted(f"{row['project_id']}:{row.get('reason')}" for row in attention)).encode()).hexdigest()[:12]
    try:
        create_notification(
            project_id="summitflow", notification_type="system", severity="warning",
            title=f"Publication: {len(attention)} project(s) need attention",
            message="\n".join(lines), metadata={"nightly_publication": True},
            dedupe_key=f"publication-{now.astimezone(WINDOW_ZONE).date().isoformat()}-{digest}",
        )
    except Exception:
        logger.warning("nightly_publication_notification_failed")


def run_nightly_publication(*, dry_run: bool = False, now: datetime | None = None,
                            project_ids: list[str] | None = None) -> dict[str, Any]:
    """One sequential pass over the auto-published projects."""
    now = now or datetime.now(UTC)
    containment = now.astimezone(WINDOW_ZONE).hour == CONTAINMENT_HOUR
    rows: list[dict[str, Any]] = []
    for project_id, root in _projects(project_ids):
        mode = "unknown"
        try:
            mode = publication_mode(project_id)
            candidate = select_candidate(project_id, root, mode, publication_hold(project_id))
        except Exception:
            logger.warning("nightly_publication_selection_failed", project_id=project_id)
            candidate = {"project_id": project_id, "mode": mode, "action": "skip", "reason": "selection_failed"}
        if candidate["action"] != "skip" and not dry_run:
            try:
                candidate = execute_candidate(candidate, root)
            except Exception:
                logger.warning("nightly_publication_failed", project_id=project_id)
                candidate = {**candidate, "outcome": "failed", "reason": "nightly_publication_unavailable"}
        rows.append(candidate)
        if containment and not dry_run:
            check = remote_containment(project_id, root, mode)
            if check:
                rows.append(check)
            observe_codeql(project_id, root, mode)
    if not dry_run:
        _notify(rows, now)
    return {"status": "dry_run" if dry_run else "completed", "projects": rows}


# The nightly deep lane shares this busy check; publication itself never defers on it.
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
    """Defer deep-lane work while someone works on the project or heavy work is running."""
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
