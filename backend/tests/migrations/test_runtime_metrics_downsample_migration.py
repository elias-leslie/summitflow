"""Tests for the one-time runtime-metric retention migration."""

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
        / "c935fa8c0398_downsample_runtime_metrics_history.py"
    )
    spec = importlib.util.spec_from_file_location(
        "runtime_metrics_downsample_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_downsamples_and_reclaims_runtime_metric_storage(mocker) -> None:
    module = _load_migration_module()
    execute = mocker.patch.object(module.op, "execute")
    context = MagicMock()
    mocker.patch.object(module.op, "get_context", return_value=context)

    module.upgrade()

    statements = [str(call.args[0]) for call in execute.call_args_list]
    assert len(statements) == 3
    assert "INTERVAL '14 days'" in statements[0]
    assert "ROW_NUMBER() OVER" in statements[1]
    assert "EXTRACT(EPOCH FROM sampled_at) / 300" in statements[1]
    assert statements[2] == "VACUUM (FULL, ANALYZE) runtime_metric_samples"
    context.autocommit_block.assert_called_once_with()


def test_downgrade_does_not_fabricate_deleted_history(mocker) -> None:
    module = _load_migration_module()
    execute = mocker.patch.object(module.op, "execute")

    module.downgrade()

    execute.assert_not_called()
