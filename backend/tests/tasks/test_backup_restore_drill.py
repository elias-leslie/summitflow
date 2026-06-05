from __future__ import annotations

from pathlib import Path


def test_drill_script_points_to_repo_script() -> None:
    from app.tasks import backup_restore_drill

    expected = Path(__file__).resolve().parents[3] / "scripts" / "infra-restore-drill.sh"

    assert expected == backup_restore_drill.DRILL_SCRIPT
    assert backup_restore_drill.DRILL_SCRIPT.exists()
    assert backup_restore_drill.DRILL_SCRIPT.is_file()


def test_drill_script_keeps_restore_strict_but_skips_bootstrap_postgres_role() -> None:
    from app.tasks import backup_restore_drill

    script = backup_restore_drill.DRILL_SCRIPT.read_text(encoding="utf-8")

    assert "ON_ERROR_STOP=1" in script
    assert "/^CREATE ROLE postgres;$/d" in script
    assert "/^ALTER ROLE postgres /d" in script
