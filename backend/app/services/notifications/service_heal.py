"""Self-heal for managed project units, run with the 5-minute health monitor.

``st service heal --json`` restarts units users would see broken (running from
a removed release, left on an older release by the live deploy, or a page that
fails while /health passes) onto their live release, with no build. A fixed
problem is recorded in the project's restart log and needs nobody (Nightshift's
"auto" class). Only a project the restart could not fix reaches the owner, as
one Nightshift push per project; it resolves once the project is healthy again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, cast

from ...logging_config import get_logger
from ...tasks.backup_canaries import _nightshift
from ...utils import safe_subprocess
from ..redis_pool import get_redis

logger = get_logger(__name__)

HEAL_TIMEOUT_SECONDS = 170
PUSH_TIMEOUT_SECONDS = 20
_ALERTED_KEY = "service_heal:alerted"
_OWNER_STATUSES = frozenset({"failed", "needs_attention"})
_CLEAR_STATUSES = frozenset({"ok", "healed"})


def notice_key(project_id: str) -> str:
    return f"service-heal:{project_id}"


def build_notice(result: dict[str, Any]) -> dict[str, Any]:
    project_id = str(result.get("project") or "")
    problems = [p for p in result.get("problems") or () if isinstance(p, dict)]
    lines = [f"{p.get('unit')}: {p.get('detail')}" for p in problems]
    stuck = result.get("status") == "needs_attention"
    title = f"{project_id} is broken and was not restarted" if stuck else f"{project_id} is still broken after a restart"
    body = lines[0] if lines else str(result.get("detail") or "A unit is broken.")
    detail = "\n".join([*lines[1:], str(result.get("detail") or "")]).strip()
    return {
        "v": 1, "source": "summitflow", "kind": "alert", "severity": "warning",
        "title": title, "body": body, **({"detail": detail} if detail else {}),
        "key": notice_key(project_id), "command": f"st service heal {project_id}",
        "actions": ["look-into"], "primary": "look-into", "push": "phone",
    }


def _nightshift_call(arguments: list[str], stdin: str | None = None) -> bool:
    binary = _nightshift()
    if binary is None:
        return False
    try:
        result = safe_subprocess.run([binary, *arguments], input=stdin, capture_output=True, text=True,
                                     timeout=PUSH_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        logger.error("service_heal_nightshift_failed", command=arguments[0], error=result.stderr.strip()[:500])
    return result.returncode == 0


def _alerted() -> set[str]:
    try:
        members = cast(set[Any], get_redis().smembers(_ALERTED_KEY))
        return {m.decode() if isinstance(m, bytes) else str(m) for m in members}
    except Exception:
        logger.debug("service_heal_alerted_unreadable")
        return set()


def _mark(project_id: str, alerted: bool) -> None:
    try:
        redis = get_redis()
        (redis.sadd if alerted else redis.srem)(_ALERTED_KEY, project_id)
    except Exception:
        logger.debug("service_heal_alerted_unwritable")


def run_service_heal() -> dict[str, Any]:
    """Run one heal pass; push only for projects it could not fix, resolve those that recovered."""
    st = shutil.which("st")
    if st is None:
        logger.error("service_heal_unavailable", reason="st not on PATH")
        return {"status": "unavailable"}
    try:
        completed = safe_subprocess.run([st, "service", "heal", "--json"], capture_output=True, text=True,
                                        timeout=HEAL_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("service_heal_failed", error=str(exc)[:500])
        return {"status": "error"}
    results: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("project"):
            results.append(value)
    if not results:
        logger.error("service_heal_no_results", returncode=completed.returncode, error=completed.stderr.strip()[-500:])
        return {"status": "error"}
    alerted = _alerted()
    summary: dict[str, list[str]] = {"healed": [], "alerted": [], "resolved": []}
    for result in results:
        project_id, status = str(result["project"]), result.get("status")
        if status == "healed":
            summary["healed"].append(project_id)
            logger.info("service_heal_restarted", project=project_id, units=result.get("restarted"),
                        problems=result.get("problems"))
        if status in _OWNER_STATUSES:
            if _nightshift_call(["push", "--json"], json.dumps(build_notice(result))):
                _mark(project_id, True)
                summary["alerted"].append(project_id)
        elif status in _CLEAR_STATUSES and project_id in alerted:
            text = "Restarted onto its live release." if status == "healed" else "Healthy again."
            if _nightshift_call(["resolve", notice_key(project_id), "--text", text]):
                _mark(project_id, False)
                summary["resolved"].append(project_id)
    return {"status": "ok", "projects": len(results), **summary}
