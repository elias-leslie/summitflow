"""Keep retired recovery points readable without recurring maintenance."""
from unittest.mock import Mock


def test_retired_repository_skips_automatic_maintenance_but_stays_registered(monkeypatch) -> None:
    from app.tasks import backup_repository_runtime as runtime
    monkeypatch.setattr(runtime.backup_store, "list_backends", lambda **_: [{"id": "retired", "enabled": True, "backend_type": "local", "config": {"engine": "restic", "restic_automatic_maintenance": False}}])
    maintain = Mock(side_effect=AssertionError("Retired repository must not be scanned"))
    monkeypatch.setattr(runtime, "maintain_repository", maintain)
    assert runtime.run_repository_maintenance() == {}
    maintain.assert_not_called()


def test_disabled_sources_retire_only_after_the_configured_age(monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    from app.tasks import backup_repository_runtime as runtime
    now = datetime(2026, 10, 24, tzinfo=UTC)
    restic = {"format": "restic-v1"}
    sources = [{"id": "live", "enabled": True}, {"id": "old", "enabled": False}, {"id": "recent", "enabled": False},
               {"id": "archive-only", "enabled": False}, {"id": "empty", "enabled": False}]
    rows = {
        "live": [{"created_at": (now - timedelta(days=90)).isoformat(), "verification_json": restic, "storage_backend_id": "stb"}],
        "old": [{"created_at": (now - timedelta(days=31)).isoformat(), "verification_json": restic, "storage_backend_id": "stb"}],
        "recent": [{"created_at": (now - timedelta(days=40)).isoformat(), "verification_json": restic, "storage_backend_id": "stb"},
                   {"created_at": (now - timedelta(days=5)).isoformat(), "verification_json": restic, "storage_backend_id": "stb"}],
        "archive-only": [{"created_at": (now - timedelta(days=90)).isoformat(), "verification_json": {}, "storage_backend_id": "stb"}],
        "empty": [],
    }
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: sources)
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda source_id, **_: (rows[source_id], len(rows[source_id])))
    retired = []
    monkeypatch.setattr(runtime, "retire_repository_source", lambda env, source_id, dry_run: retired.append((source_id, dry_run)) or {"status": "completed"})
    assert runtime.retire_disabled_sources({}, "stb", now=now) == {"old": {"status": "completed"}}
    assert retired == [("old", False)]
    assert runtime.retire_disabled_sources({}, "other-backend", now=now) == {}


def test_retirement_runs_only_after_healthy_qualified_maintenance(monkeypatch) -> None:
    from app.tasks import backup_repository_runtime as runtime
    monkeypatch.setattr(runtime.backup_store, "list_backends", lambda **_: [{"id": "stb", "enabled": True, "backend_type": "local", "config": {"engine": "restic"}}])
    monkeypatch.setattr("app.tasks.backup_utils.storage_config_env", lambda config: {})
    retire = Mock(return_value={"old": {"status": "completed"}})
    monkeypatch.setattr(runtime, "retire_disabled_sources", retire)
    for maintenance, expected in (({"dry_run": True}, 0), ({"dry_run": False, "local": {"status": "failed"}}, 0), ({"dry_run": False}, 1)):
        retire.reset_mock()
        monkeypatch.setattr(runtime, "maintain_repository", lambda env, dry_run, value=maintenance: dict(value))
        result = runtime.run_repository_maintenance()
        assert retire.call_count == expected
        assert ("retired_sources" in result["stb"]) is bool(expected)
