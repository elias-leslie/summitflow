"""Tests for scheduled task discovery."""

from __future__ import annotations

from pathlib import Path

from app.services.explorer.types.task_schedule import (
    get_task_schedule,
    parse_hatchet_scheduled_workflows,
)


def test_parse_hatchet_scheduled_workflows_extracts_task_metadata(tmp_path: Path) -> None:
    workflow_file = tmp_path / "backend" / "app" / "workflows" / "scheduled.py"
    workflow_file.parent.mkdir(parents=True, exist_ok=True)
    workflow_file.write_text(
        """
from app.hatchet_app import hatchet

@hatchet.task(
    name="nightly-refresh",
    on_crons=["0 2 * * *"],
    retries=3,
    execution_timeout="5m",
)
async def refresh_reference_data(ctx):
    return None
""".strip()
    )

    schedule = parse_hatchet_scheduled_workflows(
        workflow_file.read_text(),
        workflow_file,
        tmp_path,
    )

    assert schedule == {
        "nightly-refresh": {
            "task": "refresh_reference_data",
            "workflow_name": "nightly-refresh",
            "scheduler": "hatchet",
            "schedule_crontab": "0 2 * * *",
            "execution_timeout": "5m",
            "retries": 3,
            "source_file": "backend/app/workflows/scheduled.py",
        }
    }


def test_get_task_schedule_scans_all_workflow_modules(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "backend" / "app" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text("")
    (workflows_dir / "maintenance.py").write_text(
        """
from app.hatchet_app import hatchet

@hatchet.task(name="daily-maintenance", on_crons=["0 4 * * *"])
async def run_daily_maintenance(ctx):
    return None
""".strip()
    )
    (workflows_dir / "watchlist.py").write_text(
        """
from app.hatchet_app import hatchet

@hatchet.task(name="watchlist-refresh", on_crons=["*/5 * * * *"])
async def refresh_watchlist(ctx):
    return None
""".strip()
    )

    schedule = get_task_schedule("portfolio-ai", None, tmp_path, "backend")

    assert set(schedule) == {"daily-maintenance", "watchlist-refresh"}
    assert schedule["daily-maintenance"]["source_file"] == "backend/app/workflows/maintenance.py"
    assert schedule["watchlist-refresh"]["source_file"] == "backend/app/workflows/watchlist.py"
    assert all(item["scheduler"] == "hatchet" for item in schedule.values())
