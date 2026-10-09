"""Portable frequency migration keeps source identity and retention untouched."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/9c4e2b107a63_four_hourly_backups.py"
    spec = importlib.util.spec_from_file_location("four_hourly_backups", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_permits_frequency_without_activating_sources(monkeypatch):
    migration = _migration()
    execute = Mock()
    monkeypatch.setattr(migration.op, "execute", execute)
    migration.upgrade()
    statements = [call.args[0] for call in execute.call_args_list]
    assert len(statements) == 2
    assert "'four_hourly'" in statements[1]
    assert "retention_days" not in "\n".join(statements)
    assert "DELETE" not in "\n".join(statements)
    assert "UPDATE" not in "\n".join(statements)


def test_downgrade_recalculates_four_hour_sources_before_constraint(monkeypatch):
    migration = _migration()
    execute = Mock()
    monkeypatch.setattr(migration.op, "execute", execute)
    migration.downgrade()
    statements = [call.args[0] for call in execute.call_args_list]
    assert "WHERE frequency = 'four_hourly'" in statements[0]
    assert "INTERVAL '1 day'" in statements[0]
    assert "'four_hourly'" not in statements[-1]


def test_upgrade_preserves_all_34_enabled_schedules_and_disabled_source(db_schema_initialized, monkeypatch):
    from app.storage.connection import get_connection

    migration = _migration()
    prefix = "test-four-hour-" + uuid4().hex
    # DDL and data changes stay in this test DB's rolled-back transaction.
    with get_connection() as connection, connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.executemany("""INSERT INTO backup_sources
            (id, name, path, source_type, enabled, frequency, retention_days, last_run_at, next_run_at)
            VALUES (%s, 'Fixture', '/tmp/synthetic-fixture', 'config', %s, 'weekly', %s,
                    NOW() - INTERVAL '5 hours', NOW() + INTERVAL '1 week')""",
            [(f"{prefix}-{i}", i < 34, i + 1) for i in range(35)])
        query = "SELECT enabled, frequency, retention_days, last_run_at, next_run_at FROM backup_sources WHERE id LIKE %s ORDER BY retention_days"
        cursor.execute(query, (prefix + "%",))
        original = cursor.fetchall()
        monkeypatch.setattr(migration.op, "execute", cursor.execute)
        migration.upgrade()
        cursor.execute(query, (prefix + "%",))
        rows = cursor.fetchall()
        assert len(rows) == 35
        assert rows == original
        cursor.execute("UPDATE backup_sources SET frequency = 'four_hourly' WHERE id = %s", (prefix + "-0",))
        cursor.execute("SELECT frequency FROM backup_sources WHERE id = %s", (prefix + "-0",))
        assert cursor.fetchone() == ("four_hourly",)
        assert rows[34][0] is False
        assert rows[34][1:3] == ("weekly", 35)
