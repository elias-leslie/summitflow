"""One rolling publication/security repair task per project, in existing task storage."""
from __future__ import annotations

import os
import re
import subprocess
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ...config import DATABASE_URL
from ...utils import safe_subprocess
from .columns import TASK_COLUMNS_WITH_SPIRIT
from .core import create_task
from .mapping import row_to_dict_with_spirit

REPAIR_LABEL = "publication-repair"
_POLICY_APPROVER = "owner-approved-nightly-repair-policy"
_SOURCE_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _ensure_policy_plan(task_id: str) -> None:
    """Recover interrupted factory setup without rewriting an owner's later plan."""
    from ..subtasks import create_subtask, get_subtasks_for_task
    from ..task_spirit import approve_plan, get_task_spirit

    spirit = get_task_spirit(task_id) or {}
    if not (spirit.get("context") or {}).get("publication_repair"):
        return
    fresh = not spirit.get("plan_history")
    if not fresh and not (spirit.get("plan_status") == "approved" and spirit.get("plan_approved_by") == _POLICY_APPROVER):
        return
    if not get_subtasks_for_task(task_id):
        create_subtask(
            task_id, "1.1",
            "Inspect retained source-bound findings, repair their causes and any demonstrated workflow gaps, "
            "add focused regression coverage, and run canonical local acceptance. Submit the accepted "
            "repair for nightly confirmation without holding a claim, checkpoint, or checkout lease.",
            display_order=0, phase="implementation",
        )
    if fresh and spirit.get("plan_status") != "approved":
        approve_plan(task_id, approved_by=_POLICY_APPROVER)


def unresolved_repair(task: dict[str, Any]) -> list[str]:
    if REPAIR_LABEL not in (task.get("labels") or []):
        return []
    findings = (task.get("verification_result") or {}).get("publication_repair") or {}
    return [key for key, finding in findings.items()
            if isinstance(finding, dict) and finding.get("state") != "resolved"]


def get_repair_task(project_id: str, *, connection: psycopg.Connection | None = None) -> dict[str, Any] | None:
    from ..connection import get_cursor
    with (connection.cursor() if connection else get_cursor()) as cur:
        cur.execute(f"""SELECT {TASK_COLUMNS_WITH_SPIRIT} FROM tasks t
                       LEFT JOIN task_spirit ts ON ts.task_id = t.id
                       WHERE t.project_id = %s AND t.labels @> %s::text[]
                       AND t.status NOT IN ('completed', 'cancelled') ORDER BY t.created_at, t.id LIMIT 1""",
                    (project_id, [REPAIR_LABEL]))
        row = cur.fetchone()
    return row_to_dict_with_spirit(row) if row else None


def _resolution_includes_failure(project_id: str, previous: dict[str, Any], observation: dict[str, Any],
                                 connection: psycopg.Connection) -> bool:
    """Prove inclusion of the actual failed source, never a current-HEAD guess."""
    failed = previous.get("source_commit")
    verified = observation.get("source_commit")
    if (not isinstance(failed, str) or not isinstance(verified, str)
            or not _SOURCE_OID.fullmatch(failed) or not _SOURCE_OID.fullmatch(verified)):
        return False
    if failed == verified:
        return True
    from ..projects import get_project_root_path

    root = get_project_root_path(project_id, connection=connection)
    if not root:
        return False
    # Remote merge objects may not exist locally. Missing proof retains the
    # finding; this read must not fetch or inspect another ambient Git repo.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        return safe_subprocess.run(
            ["git", "--no-replace-objects", "-C", root, "merge-base", "--is-ancestor", failed, verified],
            env=environment, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=10,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def record_finding(project_id: str, category: str, observation: dict[str, Any], *, resolved: bool,
                   resolution_reasons: frozenset[str] | None = None) -> str | None:
    """Serialize task creation and merge a category without overwriting independent evidence."""
    # Do not hold a pooled slot while the canonical task/spirit APIs use the
    # pool: concurrent project observations would exhaust it and deadlock.
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("publication-repair:" + project_id,))
        task = get_repair_task(project_id, connection=conn)
        if task is None:
            if resolved:
                return None
            task = create_task(
                project_id=project_id, title="Repair nightly publication and verified code health",
                description=("Resolve the retained, source-bound nightly publication/CI/security findings. "
                             "Use normal ST pickup and local checkpoints; preserve backups and unrelated work. "
                             "Do not weaken checks, disable hooks, change visibility, or enable autonomous execution. "
                             "Repair process defects that caused the failure. Closure requires local acceptance "
                             "and remote confirmation that includes the accepted repair source."),
                priority=1, task_type="bug", complexity="STANDARD", execution_mode="manual",
                labels=[REPAIR_LABEL], initial_spirit={
                    "complexity": "STANDARD", "context": {"publication_repair": True},
                    "done_when": ["All retained actionable findings are resolved with evidence.",
                                  "Canonical local acceptance passes for the repair source.",
                                  "Nightly remote checks confirm the accepted repair source; no gate was bypassed."],
                },
            )
        _ensure_policy_plan(task["id"])
        observed_at = observation.get("observed_at")
        try:
            timestamp = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("observation timezone required")
        except (TypeError, ValueError):
            if resolved:
                raise ValueError("Resolution requires a timestamped observation") from None
            timestamp = datetime.now(UTC)
        previous = ((task.get("verification_result") or {}).get("publication_repair") or {}).get(category) or {}
        # A narrow cause-specific resolution must not clear other policy or
        # coverage findings sharing the category. The exact previous category
        # remains covered by the source proof and compare-and-swap below.
        if resolved and resolution_reasons is not None and previous.get("reason") not in resolution_reasons:
            return str(task["id"])
        if previous.get("observed_at"):
            previous_time = datetime.fromisoformat(previous["observed_at"])
            # Equal timestamps prefer the failure: callbacks can arrive in
            # either order and an older success must never clear a newer defect.
            if timestamp < previous_time or (timestamp == previous_time and resolved and previous.get("state") != "resolved"):
                return str(task["id"])
        if (resolved and previous and previous.get("state") != "resolved"
                and not _resolution_includes_failure(project_id, previous, observation, conn)):
            return str(task["id"])
        # The advisory lock serializes observer callbacks. Compare the exact
        # category too: another task writer may replace it while Git proves
        # ancestry, and that replacement must not inherit the old proof.
        cur.execute("""UPDATE tasks SET verification_result = jsonb_set(
                       COALESCE(verification_result, '{}'::jsonb), '{publication_repair}',
                       COALESCE(verification_result->'publication_repair', '{}'::jsonb) || %s::jsonb),
                       updated_at = NOW() WHERE id = %s AND project_id = %s
                       AND COALESCE(verification_result->'publication_repair'->%s, '{}'::jsonb) = %s::jsonb""",
                    (Jsonb({category: {**observation, "observed_at": timestamp.astimezone(UTC).isoformat(),
                                      "state": "resolved" if resolved else "unresolved"}}),
                     task["id"], project_id, category, Jsonb(previous)))
        return str(task["id"])
