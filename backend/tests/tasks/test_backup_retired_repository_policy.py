"""Keep retired recovery points readable without recurring maintenance."""
from unittest.mock import Mock


def test_retired_repository_skips_automatic_maintenance_but_stays_registered(monkeypatch) -> None:
    from app.tasks import backup_repository_runtime as runtime
    monkeypatch.setattr(runtime.backup_store, "list_backends", lambda **_: [{"id": "retired", "enabled": True, "backend_type": "local", "config": {"engine": "restic", "restic_automatic_maintenance": False}}])
    maintain = Mock(side_effect=AssertionError("Retired repository must not be scanned"))
    monkeypatch.setattr(runtime, "maintain_repository", maintain)
    assert runtime.run_repository_maintenance() == {}
    maintain.assert_not_called()
