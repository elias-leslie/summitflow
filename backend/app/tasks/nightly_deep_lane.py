"""Nightly deep lane: ``st check --deep`` once per day per managed project.

It is the safety net for per-stage reuse (the gate reruns with no reuse) and
the home of tests the gate excludes (see ``cli.lib.deep_lane`` for opt-in).
It shares the publication night window, runs one project at a time, skips a
project with a live writer or a busy heavy lane until the next hourly run, and
skips a head that already passed within a week. Failures surface once per day
as a SummitFlow notification.

``clean_env_green_since`` in each repo's deep-lane state is the first night of
the current unbroken run of passing clean-env stages (fresh clone, fresh deps,
empty CI database). Once every repo that has it shows 14 or more days, the
private repos' GitHub Actions runs can be turned off; their workflow YAML stays,
because ``cli.lib.ci_parity`` reads it.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from .nightly_publication import WINDOW_ZONE, _git, _projects, busy_reason

logger = get_logger(__name__)

WINDOW_START_HOUR, WINDOW_END_HOUR = 1, 7
DEEP_TIMEOUT_SECONDS = 5 * 60 * 60  # gate, slow stages and the clean-env gate
PASS_VALID_DAYS = 7


def deep_window_open(now: datetime) -> bool:
    return WINDOW_START_HOUR <= now.astimezone(WINDOW_ZONE).hour < WINDOW_END_HOUR


def _state_path(root: Path) -> Path | None:
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) / "st" / "deep-lane.json" if common else None


def _read_state(path: Path | None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def skip_reason(prior: dict[str, Any], head: str, today: date) -> str | None:
    """Why this project needs no deep run today, or None to run it."""
    if prior.get("date") == today.isoformat():
        return "ran_today"
    try:
        last = date.fromisoformat(str(prior.get("date")))
    except ValueError:
        return None
    if prior.get("state") == "pass" and prior.get("sha") == head and today - last < timedelta(days=PASS_VALID_DAYS):
        return "head_passed_recently"
    return None


def _run_deep(root: Path) -> dict[str, Any]:
    environment = {key: os.environ[key] for key in ("HOME", "USER", "LOGNAME", "LANG", "XDG_RUNTIME_DIR")
                   if key in os.environ}
    environment["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    try:
        completed = subprocess.run(
            ["bash", "-lc", "exec st check --deep --json"], cwd=root, env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors="replace", timeout=DEEP_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"state": "fail", "reason": "deep_lane_timeout"}
    except OSError:
        return {"state": "unavailable", "reason": "deep_lane_unavailable"}
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith("DEEP_EVIDENCE:"):
            result = json.loads(line.removeprefix("DEEP_EVIDENCE:"))
            failed = [stage for stage in result.get("stages", []) if stage.get("state") != "pass"]
            clean_env = next((stage.get("state") for stage in result.get("stages", []) if stage.get("id") == "clean-env"), None)
            return {"state": result.get("state"), "reason": ",".join(stage["id"] for stage in failed) or "passed",
                    "failures": [line for stage in failed for line in stage.get("failures", [])][:5],
                    **({"clean_env": clean_env} if clean_env else {})}
    return {"state": "unavailable", "reason": f"no_deep_evidence_exit_{completed.returncode}"}


def clean_env_green_since(prior: dict[str, Any], outcome: dict[str, Any], today: date) -> str | None:
    """Start of the current clean-env pass streak; a clean-env failure restarts it."""
    if outcome.get("clean_env") == "pass":
        return str(prior.get("clean_env_green_since") or today.isoformat())
    if outcome.get("clean_env") is None:
        return prior.get("clean_env_green_since")
    return None


def _notify(rows: list[dict[str, Any]], today: date) -> None:
    failed = [row for row in rows if row.get("state") == "fail"]
    if not failed:
        return
    from ..storage.notifications import create_notification

    try:
        create_notification(
            project_id="summitflow", notification_type="system", severity="warning",
            title=f"Nightly deep lane: {len(failed)} project(s) failed",
            message="\n".join(f"{row['project_id']}: {row['reason']} source={row['sha'][:12]} (rerun: st check --deep)"
                              + "".join(f"\n  {line}" for line in row.get("failures", [])) for row in failed),
            metadata={"nightly_deep_lane": True},
            dedupe_key=f"nightly-deep-lane-{today.isoformat()}",
        )
    except Exception:
        logger.warning("nightly_deep_lane_notification_failed")


def run_nightly_deep_lane(*, now: datetime | None = None, project_ids: list[str] | None = None,
                          ignore_window: bool = False) -> dict[str, Any]:
    def window_open() -> bool:
        return ignore_window or deep_window_open(datetime.now(UTC) if now is None else now)

    if not window_open():
        return {"status": "outside_window"}
    today = (now or datetime.now(UTC)).astimezone(WINDOW_ZONE).date()
    rows: list[dict[str, Any]] = []
    for project_id, root in _projects(project_ids):
        head = _git(root, "rev-parse", "HEAD")
        if not head:
            continue
        path = _state_path(root)
        prior = _read_state(path)
        reason = skip_reason(prior, head, today) or busy_reason(project_id, root)
        if reason is None and not window_open():
            reason = "window_closed"
        if reason:
            rows.append({"project_id": project_id, "sha": head, "state": "skip", "reason": reason})
            continue
        try:
            outcome = _run_deep(root)
        except Exception:
            logger.warning("nightly_deep_lane_failed", project_id=project_id)
            outcome = {"state": "unavailable", "reason": "deep_lane_unavailable"}
        row = {"project_id": project_id, "sha": head, **outcome}
        rows.append(row)
        if path is not None and outcome["state"] in {"pass", "fail"}:
            path.parent.mkdir(parents=True, exist_ok=True)
            since = clean_env_green_since(prior, outcome, today)
            path.write_text(json.dumps({"date": today.isoformat(), "sha": head, **outcome,
                                        **({"clean_env_green_since": since} if since else {})}))
    _notify(rows, today)
    return {"status": "completed", "projects": rows}
