"""Tests for idempotent backup verification migration behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock


def _load_migration_module() -> ModuleType:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "1c2176c7fa7a_add_backup_verification_columns.py"
    )
    spec = importlib.util.spec_from_file_location(
        "backup_verification_columns_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_skips_columns_present_in_bootstrap_schema(mocker) -> None:
    module = _load_migration_module()
    inspector = MagicMock()
    inspector.get_columns.return_value = [
        {"name": "verified"},
        {"name": "verified_at"},
        {"name": "checksum"},
        {"name": "total_files"},
        {"name": "verification_json"},
    ]
    add_column = mocker.patch.object(module.op, "add_column")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    add_column.assert_not_called()


def test_downgrade_skips_missing_columns(mocker) -> None:
    module = _load_migration_module()
    inspector = MagicMock()
    inspector.get_columns.return_value = []
    drop_column = mocker.patch.object(module.op, "drop_column")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.downgrade()

    drop_column.assert_not_called()
