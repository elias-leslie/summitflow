"""Single-source-of-truth preflight gate for claim/done/edit operations.

Replaces the duplicated `require_pulse_gate + _require_task_lane_clear +
require_claim_safe_tree` matrix that previously lived in `claim.py:70-82` and
`done.py:85,94`. One sequenced call, one error surface, op-specific extras.
"""

from __future__ import annotations

from typing import Literal

import typer

from app.services.task_lane_preflight import check_task_lane_conflicts

from ..output import output_error
from .claim_helpers import require_claim_safe_tree
from .pulse import require_pulse_gate

Operation = Literal["claim", "done", "edit"]


def _project_lane_clear(task_id: str, project_id: str | None) -> None:
    if not project_id:
        return
    lane_check = check_task_lane_conflicts(task_id, project_id)
    if lane_check.disposition != "block":
        return
    for issue in lane_check.issues:
        output_error(
            f"{issue}\n"
            f"Resolution: st pulse --gate, then coordinate with the holder or st abandon <conflicting-task-id>."
        )
    raise typer.Exit(2)


def preflight(task_id: str, project_id: str | None, *, op: Operation) -> None:
    """Run all preflight gates for `op` in a single sequenced call.

    - pulse gate (always)
    - task-lane conflict check (always, scoped to task_id)
    - working-tree safety check (claim only)

    Resolution hints are emitted by the gate helpers themselves.
    """
    require_pulse_gate(project_id, allow_task_id=task_id)
    _project_lane_clear(task_id, project_id)
    if op == "claim":
        require_claim_safe_tree()
