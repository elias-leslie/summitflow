"""Tests for Alembic migrations that must tolerate bootstrap-schema installs."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock


def _load_migration_module(filename: str, module_name: str) -> ModuleType:
    migration_path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subtask_type_upgrade_skips_existing_column(mocker) -> None:
    module = _load_migration_module(
        "c1496ead682c_add_subtask_type_column.py",
        "add_subtask_type_column_migration",
    )
    inspector = MagicMock()
    inspector.get_columns.return_value = [{"name": "subtask_type"}]
    execute = mocker.patch.object(module.op, "execute")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    execute.assert_not_called()


def test_drop_qa_columns_upgrade_skips_absent_columns(mocker) -> None:
    module = _load_migration_module(
        "c10104d259a0_drop_qa_status_qa_signoff_at_qa_signoff_.py",
        "drop_qa_columns_migration",
    )
    inspector = MagicMock()
    inspector.get_columns.return_value = [{"name": "id"}]
    drop_column = mocker.patch.object(module.op, "drop_column")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    drop_column.assert_not_called()


def test_retention_days_upgrade_skips_missing_legacy_backup_schedules(mocker) -> None:
    module = _load_migration_module(
        "233ad1b1d50d_retention_count_to_retention_days.py",
        "retention_count_to_retention_days_migration",
    )
    inspector = MagicMock()
    inspector.has_table.side_effect = lambda table_name: table_name == "backups"
    execute = mocker.patch.object(module.op, "execute")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    inspector.get_columns.assert_not_called()
    execute.assert_not_called()


def test_retention_days_downgrade_skips_missing_legacy_backup_schedules(mocker) -> None:
    module = _load_migration_module(
        "233ad1b1d50d_retention_count_to_retention_days.py",
        "retention_count_to_retention_days_migration",
    )
    inspector = MagicMock()
    inspector.has_table.return_value = False
    execute = mocker.patch.object(module.op, "execute")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.downgrade()

    inspector.get_columns.assert_not_called()
    execute.assert_not_called()


def test_remove_pr_fields_upgrade_skips_absent_pull_request_url(mocker) -> None:
    module = _load_migration_module(
        "a3b7c1d2e4f5_remove_pr_created_and_pull_request_url.py",
        "remove_pr_fields_migration",
    )
    inspector = MagicMock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [{"name": "id"}]
    drop_column = mocker.patch.object(module.op, "drop_column")
    execute = mocker.patch.object(module.op, "execute")
    create_check_constraint = mocker.patch.object(module.op, "create_check_constraint")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    drop_column.assert_not_called()
    execute.assert_called_once_with("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check")
    create_check_constraint.assert_called_once()


def test_remove_pr_fields_upgrade_skips_missing_tasks_table(mocker) -> None:
    module = _load_migration_module(
        "a3b7c1d2e4f5_remove_pr_created_and_pull_request_url.py",
        "remove_pr_fields_migration",
    )
    inspector = MagicMock()
    inspector.has_table.return_value = False
    execute = mocker.patch.object(module.op, "execute")
    create_check_constraint = mocker.patch.object(module.op, "create_check_constraint")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    inspector.get_columns.assert_not_called()
    execute.assert_not_called()
    create_check_constraint.assert_not_called()


def test_remove_pr_fields_downgrade_skips_missing_tasks_table(mocker) -> None:
    module = _load_migration_module(
        "a3b7c1d2e4f5_remove_pr_created_and_pull_request_url.py",
        "remove_pr_fields_migration",
    )
    inspector = MagicMock()
    inspector.has_table.return_value = False
    add_column = mocker.patch.object(module.op, "add_column")
    execute = mocker.patch.object(module.op, "execute")
    create_check_constraint = mocker.patch.object(module.op, "create_check_constraint")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.downgrade()

    inspector.get_columns.assert_not_called()
    add_column.assert_not_called()
    execute.assert_not_called()
    create_check_constraint.assert_not_called()


def test_explorer_symbols_upgrade_skips_existing_table(mocker) -> None:
    module = _load_migration_module(
        "5e4422dac9ad_add_explorer_symbols_table.py",
        "add_explorer_symbols_table_migration",
    )
    inspector = MagicMock()
    inspector.has_table.return_value = True
    create_table = mocker.patch.object(module.op, "create_table")
    execute = mocker.patch.object(module.op, "execute")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    create_table.assert_not_called()
    assert execute.call_count == 2
    assert all("IF NOT EXISTS" in call.args[0] for call in execute.call_args_list)


def test_explorer_symbols_downgrade_uses_idempotent_drops(mocker) -> None:
    module = _load_migration_module(
        "5e4422dac9ad_add_explorer_symbols_table.py",
        "add_explorer_symbols_table_migration",
    )
    execute = mocker.patch.object(module.op, "execute")

    module.downgrade()

    assert execute.call_count == 3
    assert all("IF EXISTS" in call.args[0] for call in execute.call_args_list)


def test_task_execution_mode_upgrade_skips_existing_column_and_constraint(mocker) -> None:
    module = _load_migration_module(
        "d1cd35b5b946_add_task_execution_mode.py",
        "add_task_execution_mode_migration",
    )
    inspector = MagicMock()
    inspector.get_columns.return_value = [{"name": "execution_mode"}]
    inspector.get_check_constraints.return_value = [{"name": "ck_tasks_execution_mode"}]
    add_column = mocker.patch.object(module.op, "add_column")
    create_check_constraint = mocker.patch.object(module.op, "create_check_constraint")
    execute = mocker.patch.object(module.op, "execute")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    add_column.assert_not_called()
    create_check_constraint.assert_not_called()
    execute.assert_called_once()


def test_project_category_upgrade_skips_existing_columns_and_constraints(mocker) -> None:
    module = _load_migration_module(
        "70872a5bb120_add_project_category_and_sidebar_rank.py",
        "add_project_category_and_sidebar_rank_migration",
    )
    inspector = MagicMock()
    inspector.get_columns.return_value = [{"name": "category"}, {"name": "sidebar_rank"}]
    inspector.get_check_constraints.return_value = [
        {"name": "projects_category_check"},
        {"name": "projects_sidebar_rank_check"},
    ]
    add_column = mocker.patch.object(module.op, "add_column")
    create_check_constraint = mocker.patch.object(module.op, "create_check_constraint")
    execute = mocker.patch.object(module.op, "execute")
    mocker.patch.object(module.op, "get_bind", return_value=object())
    mocker.patch.object(module.sa, "inspect", return_value=inspector)

    module.upgrade()

    add_column.assert_not_called()
    create_check_constraint.assert_not_called()
    assert execute.call_count == 2
