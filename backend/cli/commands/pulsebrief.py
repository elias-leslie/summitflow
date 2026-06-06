"""Pulse briefing management surface."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from ..lib.usage import usage

app = typer.Typer(help="Manage Pulse briefing persistence, history, feedback, and improvement proposals.")
proposal_app = typer.Typer(help="Manage Pulse improvement proposals.")
app.add_typer(proposal_app, name="proposal")

PULSE_DB_SCRIPT = Path.home() / ".hermes" / "scripts" / "pulse_db.py"


def _run_pulse_db(args: list[str]) -> dict[str, Any] | list[Any]:
    result = subprocess.run(
        [sys.executable, str(PULSE_DB_SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "pulse_db.py failed").strip()
        typer.echo(f"PULSEBRIEF:ERROR:{message}", err=True)
        raise typer.Exit(result.returncode)
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        typer.echo(result.stdout)
        return {}


@app.command("schema")
@usage(
    surface="st.pulsebrief.schema",
    cmd="st pulsebrief schema",
    when="initialize or verify Pulse PostgreSQL briefing tables through the managed st surface",
    precautions=("uses approved PULSE_DB_URL or AGENT_HUB_DB_URL from shared env files",),
    task_types=("database", "verification", "briefing"),
    tier="mandate",
)
def schema() -> None:
    """Ensure Pulse DB tables exist."""
    payload = _run_pulse_db(["ensure-schema"])
    status = payload.get("status") if isinstance(payload, dict) else "unknown"
    print(f"PULSE_SCHEMA:status={status}")


@app.command("context")
@usage(
    surface="st.pulsebrief.context",
    cmd="st pulsebrief context --cadence daily --limit 7",
    when="inspect sampled prior Pulse briefs and pending process proposals before briefing work",
    precautions=("compact summary only; do not dump full raw brief history",),
    task_types=("briefing", "verification"),
    tier="mandate",
)
def context(
    cadence: Annotated[str, typer.Option("--cadence", help="Brief cadence to sample")] = "daily",
    limit: Annotated[int, typer.Option("--limit", min=1, max=30, help="Recent brief sample size")] = 7,
) -> None:
    """Show sampled recent Pulse context."""
    payload = _run_pulse_db(["context", "--cadence", cadence, "--limit", str(limit)])
    recent = payload.get("recent_briefs", []) if isinstance(payload, dict) else []
    proposals = payload.get("pending_improvement_proposals", []) if isinstance(payload, dict) else []
    print(f"PULSE_CONTEXT:{cadence}|recent={len(recent)}|pending_proposals={len(proposals)}")
    for brief in recent[:limit]:
        print(f"- {brief.get('brief_id')}|items={len(brief.get('items') or [])}|status={brief.get('status')}")


@proposal_app.command("list")
@usage(
    surface="st.pulsebrief.proposal.list",
    cmd="st pulsebrief proposal list --limit 10",
    when="inspect pending Pulse process improvement proposals",
    task_types=("briefing", "verification"),
    tier="reference",
)
def proposal_list(
    limit: Annotated[int, typer.Option("--limit", min=1, max=30)] = 10,
) -> None:
    """List pending Pulse improvement proposals."""
    proposals = _run_pulse_db(["proposals", "--limit", str(limit)])
    rows = proposals if isinstance(proposals, list) else []
    print(f"PULSE_PROPOSALS[{len(rows)}]")
    for proposal in rows:
        print(f"- {proposal.get('proposal_id')}|{proposal.get('status')}|{proposal.get('risk_level')}|{proposal.get('title')}")


def _proposal_status(proposal_id: str, status: str) -> None:
    payload = _run_pulse_db(["proposal-status", proposal_id, status])
    actual = payload.get("status") if isinstance(payload, dict) else status
    print(f"PROPOSAL:{proposal_id}|status={actual}")


@proposal_app.command("approve")
@usage(
    surface="st.pulsebrief.proposal.approve",
    cmd="st pulsebrief proposal approve <proposal-id>",
    when="approve a Pulse process improvement proposal so the agent can apply the safe follow-up work",
    precautions=("approval records status only; code or source changes still require normal verification",),
    task_types=("briefing", "database", "workflow"),
    tier="mandate",
)
def proposal_approve(proposal_id: str) -> None:
    """Approve a Pulse improvement proposal."""
    _proposal_status(proposal_id, "approved")


@proposal_app.command("reject")
@usage(
    surface="st.pulsebrief.proposal.reject",
    cmd="st pulsebrief proposal reject <proposal-id>",
    when="reject a Pulse process improvement proposal",
    task_types=("briefing", "workflow"),
    tier="reference",
)
def proposal_reject(proposal_id: str) -> None:
    """Reject a Pulse improvement proposal."""
    _proposal_status(proposal_id, "rejected")
