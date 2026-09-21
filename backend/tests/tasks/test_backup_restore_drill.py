from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock


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
    assert '[[ "$ARCHIVE_PATH" == *.age ]]' in script
    assert "umask 077" in script


def test_drill_materializes_encrypted_archive_before_script(monkeypatch) -> None:
    from app.tasks import backup_restore_drill

    encrypted = Path("/tmp/infrastructure.tar.gz.age")
    plaintext = Path("/tmp/infrastructure.tar.gz")
    run_script = MagicMock(return_value={"ok": True, "components": [], "duration_ms": 1})
    monkeypatch.setattr(
        backup_restore_drill,
        "_find_infra_source",
        lambda: {"id": "infrastructure"},
    )
    monkeypatch.setattr(
        backup_restore_drill.backup_store,
        "get_latest_backup",
        lambda **_kwargs: {
            "id": "backup-1",
            "location": str(encrypted),
            "name": encrypted.name,
        },
    )
    monkeypatch.setattr(
        backup_restore_drill,
        "_locate_drill_archive",
        lambda *_args: str(encrypted),
    )
    monkeypatch.setattr(
        backup_restore_drill,
        "materialize_plaintext_archive",
        lambda _path: nullcontext(plaintext),
    )
    monkeypatch.setattr(backup_restore_drill, "_run_drill_script", run_script)
    monkeypatch.setattr(backup_restore_drill, "_record_drill_result", MagicMock())
    monkeypatch.setattr(backup_restore_drill, "_cleanup_temp", MagicMock())

    assert backup_restore_drill.run_infra_drill()["ok"] is True
    run_script.assert_called_once_with(str(plaintext), "backup-1")
