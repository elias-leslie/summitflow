"""Retired autonomous agent_configs keys are stripped; live schedule and publication keys stay."""

import importlib.util
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/6537e645f71c_drop_retired_autonomous_agent_config_keys.py"
    spec = importlib.util.spec_from_file_location("drop_retired_autonomous_agent_config_keys", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LIVE = {
    "reset_claims_enabled": False,
    "health_monitor_enabled": True,
    "publication_mode": "nightly",
    "publication_hold": {"through": None, "reason": "fixture", "set_at": "2026-10-28T00:00:00Z"},
}
_RETIRED = {
    "autonomous_enabled": True,
    "autonomous_max_concurrent": 2,
    "autonomous_external_origins": ["github"],
    "upkeep_batch_limit": 9,
    "work_pickup_enabled": True,
    "task_generation_enabled": True,
    "quality_gate_mode": "check",
    "claude_model": "sonnet",
    "default_agent": "claude",
    "component_source": "pages",
    "pending_drain_enabled": True,
    "memory_enabled": True,
    "extraction_rpm_limit": 10,
}


def _configs(cursor, project_id: str) -> dict:
    cursor.execute("SELECT agent_configs FROM projects WHERE id = %s", (project_id,))
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _column_default(cursor) -> str:
    cursor.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'projects' AND column_name = 'agent_configs'"
    )
    return cursor.fetchone()[0]


def _fence_table_exists(cursor) -> bool:
    cursor.execute("SELECT to_regclass('automation_clock_fences') IS NOT NULL")
    return cursor.fetchone()[0]


def test_upgrade_strips_retired_keys_and_downgrade_restores_defaults(db_schema_initialized, monkeypatch):
    from app.storage.connection import get_connection

    migration = _migration()
    project_id = "test-retired-agent-config-" + uuid4().hex
    # DDL and data changes stay in this test DB's rolled-back transaction.
    with get_connection() as connection, connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS automation_clock_fences (project_id TEXT)")
        cursor.execute(
            "INSERT INTO projects (id, name, base_url, agent_configs) VALUES (%s, 'Fixture', 'http://fixture', %s)",
            (project_id, Jsonb({**_LIVE, **_RETIRED})),
        )
        monkeypatch.setattr(migration.op, "execute", cursor.execute)

        migration.upgrade()
        assert _configs(cursor, project_id) == _LIVE
        assert _column_default(cursor) == "'{}'::jsonb"
        assert not _fence_table_exists(cursor)

        migration.downgrade()
        restored = _configs(cursor, project_id)
        assert {key: restored[key] for key in _LIVE} == _LIVE
        assert restored["autonomous_enabled"] is False
        assert restored["default_agent"] == "gemini"
        assert restored["quality_gate_mode"] == "quick"
        assert "claude_enabled" in _column_default(cursor)
        assert _fence_table_exists(cursor)

        migration.upgrade()
        assert _configs(cursor, project_id) == _LIVE


def test_retired_keys_exclude_live_defaults():
    from app.storage.agent_configs import DEFAULT_AGENT_CONFIG

    migration = _migration()
    assert not set(migration._RETIRED_KEYS) & set(DEFAULT_AGENT_CONFIG)
    assert set(_RETIRED) <= set(migration._RETIRED_KEYS)
