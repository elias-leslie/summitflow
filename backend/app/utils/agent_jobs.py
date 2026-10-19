"""Run installed ST source jobs through the agent's existing Tether instance."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agent_execution import run_as_agent


def run_installed_agent_job(
    module: str, payload: dict[str, Any], *, project: Path,
    cancel_check: Callable[[], None] | None = None, timeout: float = 3600,
) -> dict[str, Any]:
    """Pass data to an agent job; never pass the owner's environment or interpreter."""
    response = run_as_agent(
        ["st", "checkout-job", module], cwd=project,
        input=json.dumps(payload), capture_output=True, text=True,
        timeout=timeout, cancel_check=cancel_check,
    )
    if response.returncode:
        raise RuntimeError("Agent checkout job failed")
    try:
        value = json.loads(response.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Agent checkout job returned an invalid result") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Agent checkout job returned an invalid result")
    return value
