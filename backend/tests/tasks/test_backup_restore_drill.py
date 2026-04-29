from __future__ import annotations

from pathlib import Path


def test_drill_script_points_to_repo_script() -> None:
    from app.tasks import backup_restore_drill

    expected = Path(__file__).resolve().parents[3] / "scripts" / "infra-restore-drill.sh"

    assert expected == backup_restore_drill.DRILL_SCRIPT
    assert backup_restore_drill.DRILL_SCRIPT.exists()
    assert backup_restore_drill.DRILL_SCRIPT.is_file()
