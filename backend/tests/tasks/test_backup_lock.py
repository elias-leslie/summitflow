"""Tests for owner-safe backup lock leases."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

from app.tasks import backup_executor, backup_infra
from app.tasks.backup_lock import (
    BACKUP_LOCK_PREFIX,
    BACKUP_LOCK_TTL,
    BackupLockLeaseError,
    acquire_backup_lock,
    maintain_backup_lock,
    release_backup_lock,
    renew_backup_lock,
)


def test_acquire_backup_lock_stores_unique_owner_token() -> None:
    redis_client = MagicMock()
    redis_client.set.return_value = True
    owner = MagicMock(hex="owner-token")

    with (
        patch("app.tasks.backup_lock.get_redis", return_value=redis_client),
        patch("app.tasks.backup_lock.uuid4", return_value=owner),
    ):
        token = acquire_backup_lock("source-1")

    assert token == "owner-token"
    redis_client.set.assert_called_once_with(
        f"{BACKUP_LOCK_PREFIX}source-1",
        "owner-token",
        nx=True,
        ex=BACKUP_LOCK_TTL,
    )


def test_acquire_backup_lock_does_not_return_token_when_already_owned() -> None:
    redis_client = MagicMock()
    redis_client.set.return_value = None

    with patch("app.tasks.backup_lock.get_redis", return_value=redis_client):
        assert acquire_backup_lock("source-1") is None


def test_renew_backup_lock_compares_owner_before_extending_ttl() -> None:
    redis_client = MagicMock()
    redis_client.eval.return_value = 1

    with patch("app.tasks.backup_lock.get_redis", return_value=redis_client):
        assert renew_backup_lock("source-1", "owner-token") is True

    script, key_count, key, token, ttl = redis_client.eval.call_args.args
    assert "redis.call('get', KEYS[1]) == ARGV[1]" in script
    assert "redis.call('expire', KEYS[1], ARGV[2])" in script
    assert (key_count, key, token, ttl) == (
        1,
        f"{BACKUP_LOCK_PREFIX}source-1",
        "owner-token",
        BACKUP_LOCK_TTL,
    )


def test_release_backup_lock_compares_owner_before_delete() -> None:
    redis_client = MagicMock()
    redis_client.eval.return_value = 1

    with patch("app.tasks.backup_lock.get_redis", return_value=redis_client):
        assert release_backup_lock("source-1", "owner-token") is True

    script, key_count, key, token = redis_client.eval.call_args.args
    assert "redis.call('get', KEYS[1]) == ARGV[1]" in script
    assert "redis.call('del', KEYS[1])" in script
    assert (key_count, key, token) == (
        1,
        f"{BACKUP_LOCK_PREFIX}source-1",
        "owner-token",
    )


def test_maintain_backup_lock_renews_and_releases_owner() -> None:
    renewed = Event()

    def mark_renewed(_source_id: str, _owner_token: str) -> bool:
        renewed.set()
        return True

    with (
        patch("app.tasks.backup_lock.renew_backup_lock", side_effect=mark_renewed) as renew,
        patch("app.tasks.backup_lock.release_backup_lock", return_value=True) as release,
        maintain_backup_lock(
            "source-1", "owner-token", renewal_interval_seconds=0.001
        ),
    ):
        assert renewed.wait(timeout=1)

    renew.assert_called()
    release.assert_called_once_with("source-1", "owner-token")


def test_maintain_backup_lock_surfaces_lost_ownership() -> None:
    attempted = Event()

    def lose_ownership(_source_id: str, _owner_token: str) -> bool:
        attempted.set()
        return False

    with (
        patch("app.tasks.backup_lock.renew_backup_lock", side_effect=lose_ownership),
        patch("app.tasks.backup_lock.release_backup_lock", return_value=False),
        pytest.raises(BackupLockLeaseError, match="ownership lost"),
        maintain_backup_lock(
            "source-1", "owner-token", renewal_interval_seconds=0.001
        ),
    ):
        assert attempted.wait(timeout=1)


def test_maintain_backup_lock_does_not_mask_operation_failure() -> None:
    attempted = Event()

    def lose_ownership(_source_id: str, _owner_token: str) -> bool:
        attempted.set()
        return False

    with (
        patch("app.tasks.backup_lock.renew_backup_lock", side_effect=lose_ownership),
        patch("app.tasks.backup_lock.release_backup_lock", return_value=False),
        pytest.raises(ValueError, match="archive failed") as raised,
        maintain_backup_lock(
            "source-1", "owner-token", renewal_interval_seconds=0.001
        ),
    ):
        assert attempted.wait(timeout=1)
        raise ValueError("archive failed")

    assert any("Backup lock lease also failed" in note for note in raised.value.__notes__)


def test_project_backup_passes_acquired_owner_to_operation() -> None:
    result = {"status": "completed", "backup_id": "backup-1"}

    with (
        patch("app.tasks.backup_utils.get_source_type", return_value="project"),
        patch("app.tasks.backup_executor.get_project_root", return_value="/repo"),
        patch("app.tasks.backup_executor.acquire_backup_lock", return_value="owner-token"),
        patch(
            "app.tasks.backup_executor._run_backup",
            return_value=result,
        ) as run_backup,
    ):
        assert backup_executor.create_backup("project-1") == result

    assert run_backup.call_args.args[-1] == "owner-token"


def test_infrastructure_backup_passes_acquired_owner_to_operation() -> None:
    result = {"status": "completed", "backup_id": "backup-1"}

    with (
        patch("app.tasks.backup_infra.acquire_backup_lock", return_value="owner-token"),
        patch(
            "app.tasks.backup_infra._run_infra_backup",
            return_value=result,
        ) as run_backup,
    ):
        assert backup_infra.create_infra_backup("infrastructure") == result

    assert run_backup.call_args.args[-1] == "owner-token"


def test_lease_loss_marks_record_failed_before_success_persistence() -> None:
    @contextmanager
    def lost_lease(*_args: object, **_kwargs: object):
        yield
        raise BackupLockLeaseError("ownership lost")

    parsed = {
        "archive_name": "backup.tar.gz",
        "verification": {"verified": True},
    }
    with (
        patch(
            "app.tasks.backup_executor.backup_store.create_backup_record",
            return_value={"id": "backup-1"},
        ),
        patch("app.tasks.backup_executor.backup_store.update_backup_status"),
        patch("app.tasks.backup_executor.maintain_backup_lock", lost_lease),
        patch(
            "app.tasks.backup_executor.run_project_backup",
            return_value=parsed,
        ),
        patch(
            "app.tasks.backup_executor._handle_backup_failure",
            return_value={"status": "failed"},
        ) as handle_failure,
        patch("app.tasks.backup_executor._handle_backup_success") as handle_success,
    ):
        result = backup_executor._run_backup(
            "project-1",
            "/repo",
            None,
            "manual",
            False,
            False,
            source_id="project-1",
            owner_token="owner-token",
        )

    assert result == {"status": "failed"}
    handle_failure.assert_called_once_with(
        "backup-1",
        "ownership lost",
        "project-1",
    )
    handle_success.assert_not_called()
