"""Cancellation is one atomic, active-attempt-scoped update."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("returned_row,expected", [(None, False), (("backup-1",), True)])
def test_cancel_signal_is_atomic_and_does_not_change_backup_completion(
    monkeypatch: pytest.MonkeyPatch, returned_row: tuple[str] | None, expected: bool,
) -> None:
    from app.storage.backups import crud

    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = returned_row
    context = MagicMock()
    context.__enter__.return_value = connection
    monkeypatch.setattr(crud, "get_connection", lambda: context)

    assert crud.request_backup_cancellation("backup-1", "run-current") is expected

    cursor.execute.assert_called_once()
    sql, parameters = cursor.execute.call_args.args
    normalized = " ".join(sql.split())
    assert "WHERE id = %s" in normalized
    assert "verification_json #>> '{activity,run_id}' = %s" in normalized
    assert "verification_json #>> '{activity,active}' = 'true'" in normalized
    assert "'{activity,cancel_requested}'" in normalized
    assert "SET status" not in normalized
    assert parameters == ("backup-1", "run-current")
    connection.commit.assert_called_once()
