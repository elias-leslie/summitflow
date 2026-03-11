"""Tests for scheduled workflow task scanning."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.explorer.types.tasks import TaskScanner


def test_task_scanner_reads_hatchet_scheduled_workflows(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    scheduled = root / "backend" / "app" / "workflows" / "scheduled.py"
    scheduled.parent.mkdir(parents=True)
    scheduled.write_text(
        """
from app.hatchet_app import hatchet


@hatchet.task(
    name="summitflow-refresh-precision-indexes",
    execution_timeout="1200s",
    retries=2,
    on_crons=["*/15 * * * *"],
)
async def refresh_precision_indexes_wf(input, ctx):
    return {"status": "ok"}


@hatchet.task(
    name="summitflow-scan-projects",
    execution_timeout="1800s",
    retries=3,
    on_crons=["0 */6 * * *"],
)
async def scan_projects_wf(input, ctx):
    return {"status": "ok"}
""",
        encoding="utf-8",
    )

    with patch(
        "app.services.explorer.types.tasks.get_project_config",
        return_value={"root_path": str(root), "backend_dir": "backend"},
    ):
        entries = TaskScanner("summitflow").scan()

    assert [entry.path for entry in entries] == [
        "summitflow-refresh-precision-indexes",
        "summitflow-scan-projects",
    ]
    assert entries[0].metadata["scheduler"] == "hatchet"
    assert entries[0].metadata["schedule_type"] == "cron"
    assert entries[0].metadata["schedule_value"] == "*/15 * * * *"
    assert entries[0].metadata["execution_timeout"] == "1200s"
    assert entries[0].metadata["retries"] == 2
    assert entries[0].metadata["source_file"] == "backend/app/workflows/scheduled.py"
