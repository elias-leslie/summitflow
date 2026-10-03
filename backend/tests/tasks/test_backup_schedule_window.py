"""Optional nightly scheduling respects local time without advancing due sources."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.tasks import backup_scheduler as scheduler


@pytest.mark.parametrize(
    ("start", "end", "instant", "expected"),
    [
        (None, None, "2026-07-01T18:00:00", True),
        (2, 6, "2026-07-01T05:59:59", False),
        (2, 6, "2026-07-01T06:00:00", True),
        (2, 6, "2026-07-01T09:59:59", True),
        (2, 6, "2026-07-01T10:00:00", False),
        (2, 6, "2026-01-01T06:59:59", False),
        (2, 6, "2026-01-01T07:00:00", True),
        (2, 6, "2026-01-01T11:00:00", False),
        (22, 2, "2026-07-02T02:00:00", True),
        (22, 2, "2026-07-02T05:59:59", True),
        (22, 2, "2026-07-02T06:00:00", False),
        # Spring skips 02:00 and fall repeats 01:00; use local wall time.
        (2, 6, "2026-03-08T07:00:00", True),
        (1, 2, "2026-11-01T05:30:00", True),
        (1, 2, "2026-11-01T06:30:00", True),
    ],
)
def test_local_schedule_window(
    monkeypatch: pytest.MonkeyPatch, start: int | None, end: int | None,
    instant: str, expected: bool,
) -> None:
    settings = SimpleNamespace(
        backup_schedule_start_hour=start, backup_schedule_end_hour=end,
        backup_schedule_timezone="America/New_York",
        backup_publish_before_backup=False,
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    assert scheduler._scheduled_backup_window_open(datetime.fromisoformat(instant).replace(tzinfo=UTC)) is expected


def test_outside_window_skips_scheduled_work_without_changing_due_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "_scheduled_backup_window_open", lambda _now: False)

    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Scheduled work or bookkeeping ran outside the configured window")

    for name in ("_fail_stale_running_records", "_cleanup_stale_records", "_cleanup_expired_records",
                 "_cleanup_local_archives", "run_scheduled_drills", "create_backup"):
        monkeypatch.setattr(scheduler, name, unexpected)
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: [])
    monkeypatch.setattr(scheduler.backup_store, "update_source_last_run", unexpected)
    monkeypatch.setattr(scheduler.maintenance_store, "record_maintenance_run", unexpected)

    assert scheduler.run_scheduled_backups() == {
        "status": "skipped", "reason": "outside-backup-window", "count": 0, "results": [],
    }


@pytest.mark.parametrize(
    "window",
    [
        {"backup_schedule_start_hour": 2},
        {"backup_schedule_end_hour": 6},
        {"backup_schedule_start_hour": 2, "backup_schedule_end_hour": 2},
        {"backup_schedule_start_hour": -1, "backup_schedule_end_hour": 6},
        {"backup_schedule_start_hour": 2, "backup_schedule_end_hour": 24},
        {"backup_schedule_timezone": "not/a-timezone"},
    ],
)
def test_schedule_configuration_rejects_invalid_window(
    monkeypatch: pytest.MonkeyPatch, window: dict[str, Any],
) -> None:
    for name in ("BACKUP_SCHEDULE_START_HOUR", "BACKUP_SCHEDULE_END_HOUR", "BACKUP_SCHEDULE_TIMEZONE"):
        monkeypatch.delenv(name, raising=False)
    values: dict[str, Any] = {"_env_file": None, "database_url": "postgresql://localhost/fixture", **window}
    with pytest.raises(ValidationError):
        Settings(**values)


def test_schedule_settings_load_requested_window_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKUP_SCHEDULE_START_HOUR", "2")
    monkeypatch.setenv("BACKUP_SCHEDULE_END_HOUR", "6")
    monkeypatch.setenv("BACKUP_SCHEDULE_TIMEZONE", "America/New_York")
    values: dict[str, Any] = {"_env_file": None, "database_url": "postgresql://localhost/fixture"}
    settings = Settings(**values)
    assert settings.backup_schedule_start_hour == 2
    assert settings.backup_schedule_end_hour == 6
    assert settings.backup_schedule_timezone == "America/New_York"


@pytest.fixture
def nightly_window(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        backup_schedule_start_hour=2, backup_schedule_end_hour=6,
        backup_schedule_timezone="America/New_York",
        backup_publish_before_backup=False,
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("2026-07-01T16:00:00+00:00", "2026-07-01T10:00:00+00:00"),
        ("2026-07-02T05:00:00+00:00", "2026-07-01T10:00:00+00:00"),
        ("2026-03-08T12:00:00+00:00", "2026-03-08T10:00:00+00:00"),
        ("2026-11-01T12:00:00+00:00", "2026-11-01T11:00:00+00:00"),
    ],
)
def test_latest_finished_window_uses_local_day_and_dst(
    nightly_window: None, instant: str, expected: str,
) -> None:
    assert scheduler._latest_finished_window_end(datetime.fromisoformat(instant)) == datetime.fromisoformat(expected)


def test_overnight_window_finished_end(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        backup_schedule_start_hour=22, backup_schedule_end_hour=2,
        backup_schedule_timezone="America/New_York",
        backup_publish_before_backup=False,
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    assert scheduler._latest_finished_window_end(datetime.fromisoformat("2026-07-01T16:00:00+00:00")) == datetime.fromisoformat("2026-07-01T06:00:00+00:00")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"next_run_at": "2026-07-01T06:00:00+00:00"}, True),
        ({"next_run_at": "2026-07-01T10:00:00+00:00"}, False),
        ({"next_run_at": "2026-07-01T12:00:00+00:00"}, False),
        ({"next_run_at": "2026-07-01T06:00:00+00:00", "enabled": False}, False),
        ({"next_run_at": None, "created_at": "2026-06-30T06:00:00+00:00"}, True),
        ({"next_run_at": None, "created_at": "2026-07-01T12:00:00+00:00"}, False),
        ({"next_run_at": None, "last_run_at": "2026-06-30T06:00:00+00:00", "frequency": "daily"}, True),
    ],
)
def test_catchup_does_not_capture_fresh_daytime_work(source: dict[str, Any], expected: bool) -> None:
    assert scheduler._catchup_source(source, datetime.fromisoformat("2026-07-01T10:00:00+00:00")) is expected


@pytest.mark.parametrize(
    ("next_run", "now", "expected"),
    [
        ("2026-07-02T16:00:00+00:00", "2026-07-01T16:00:00+00:00", "2026-07-02T06:00:00+00:00"),
        ("2026-07-08T16:00:00+00:00", "2026-07-01T16:00:00+00:00", "2026-07-08T06:00:00+00:00"),
        ("2026-07-31T16:00:00+00:00", "2026-07-01T16:00:00+00:00", "2026-07-31T06:00:00+00:00"),
        ("2026-03-08T17:00:00+00:00", "2026-03-07T17:00:00+00:00", "2026-03-08T07:00:00+00:00"),
        ("2026-11-01T16:00:00+00:00", "2026-10-31T16:00:00+00:00", "2026-11-01T07:00:00+00:00"),
    ],
)
def test_catchup_next_run_aligns_to_future_nightly_start(
    nightly_window: None, next_run: str, now: str, expected: str,
) -> None:
    assert scheduler._align_next_run_to_window(
        datetime.fromisoformat(next_run), datetime.fromisoformat(now),
    ) == datetime.fromisoformat(expected)


def test_daytime_restart_catches_up_only_missed_sources_and_preserves_failures(
    monkeypatch: pytest.MonkeyPatch, nightly_window: None,
) -> None:
    monkeypatch.setattr(scheduler, "_scheduled_backup_window_open", lambda _now: False)
    monkeypatch.setattr(scheduler, "_latest_finished_window_end", lambda _now: datetime.fromisoformat("2026-07-01T10:00:00+00:00"))
    sources = [
        {"id": "offline", "frequency": "daily", "next_run_at": "2026-07-01T06:00:00+00:00"},
        {"id": "failed", "frequency": "daily", "next_run_at": "2026-07-01T06:00:00+00:00"},
        {"id": "fresh", "frequency": "daily", "next_run_at": "2026-07-01T12:00:00+00:00"},
    ]
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: sources)
    monkeypatch.setattr(scheduler, "_fail_stale_running_records", lambda: 0)
    captured: list[str] = []
    advanced: list[str] = []

    def capture(**kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs["source_id"])
        return {"status": "completed_pending_upload" if kwargs["source_id"] == "offline" else "failed"}

    def advance(source_id: str, next_run: datetime) -> None:
        advanced.append(source_id)
        next(source for source in sources if source["id"] == source_id)["next_run_at"] = next_run.isoformat()

    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Routine maintenance ran during daytime catch-up")

    for name in ("_cleanup_stale_records", "_cleanup_expired_records", "_cleanup_local_archives", "run_scheduled_drills"):
        monkeypatch.setattr(scheduler, name, unexpected)
    monkeypatch.setattr(scheduler, "create_backup", capture)
    monkeypatch.setattr(scheduler.backup_store, "update_source_last_run", advance)
    monkeypatch.setattr(scheduler.maintenance_store, "record_maintenance_run", lambda *_args, **_kwargs: None)

    result = scheduler.run_scheduled_backups()
    assert result["catch_up"] is True
    assert result["status"] == "partial"
    assert captured == ["offline", "failed"]
    assert advanced == ["offline"]
    assert result["succeeded"] == 1
    assert result["failed"] == 1

    # The next poll retries the failure, but does not capture the locally
    # completed source again merely because its offsite upload is queued.
    scheduler.run_scheduled_backups()
    assert captured == ["offline", "failed", "failed"]
    assert advanced == ["offline"]


@pytest.mark.parametrize("publication_raises", [False, True])
def test_failed_publication_does_not_block_local_capture_and_stays_retryable(
    monkeypatch: pytest.MonkeyPatch, publication_raises: bool,
) -> None:
    from app.tasks import backup_publish

    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(
        backup_publish_before_backup=True, backup_schedule_start_hour=None,
    ))
    events: list[str] = []
    recorded: list[dict[str, Any]] = []

    def publish(_source: dict[str, Any]) -> dict[str, Any]:
        events.append("publish")
        if publication_raises:
            raise OSError("private remote diagnostic must not be retained")
        return {"status": "failed", "reason": "offline", "backup_can_continue": True}

    def capture(**_kwargs: Any) -> dict[str, Any]:
        events.append("capture")
        return {"status": "completed", "backup_id": "saved-local-point"}

    def record(backup_id: str, verification: dict[str, Any]) -> None:
        assert backup_id == "saved-local-point"
        recorded.append(verification)

    monkeypatch.setattr(backup_publish, "publish_source_before_backup", publish)
    monkeypatch.setattr(scheduler, "create_backup", capture)
    monkeypatch.setattr(scheduler.backup_store, "merge_backup_verification_json", record)
    monkeypatch.setattr(scheduler.backup_store, "update_source_last_run", lambda *_: None)
    result = scheduler._process_due_source({"id": "project", "frequency": "daily"})

    assert events == ["publish", "capture"]
    assert result["status"] == "completed"
    assert recorded[0]["publication"]["status"] == "failed"
    assert "private remote" not in str(recorded)


def test_publication_observation_survives_failed_archive(monkeypatch):
    from app.services import publication_health
    from app.tasks import backup_publish

    publication = {"status": "failed", "head": "a" * 40, "reason": "outgoing_verification_failed",
                   "publication_complete": False, "backup_can_continue": True}
    recorded = []
    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(backup_publish_before_backup=True))
    monkeypatch.setattr(backup_publish, "publish_source_before_backup", lambda _: publication)
    monkeypatch.setattr(publication_health, "record_publication_observation", lambda project, result: recorded.append((project, result)))
    monkeypatch.setattr(scheduler, "create_backup", lambda **_: {"status": "failed", "error": "archive unavailable"})
    result = scheduler._process_due_source({"id": "source", "project_id": "project", "source_type": "project", "frequency": "daily"})
    assert result["status"] == "failed"
    assert recorded == [("project", publication)]


def test_health_ingestion_failure_does_not_block_archive(monkeypatch):
    from app.services import publication_health
    from app.tasks import backup_publish

    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(backup_publish_before_backup=True, backup_schedule_start_hour=None))
    monkeypatch.setattr(backup_publish, "publish_source_before_backup", lambda _: {"status": "failed", "reason": "offline"})
    def unavailable(*_):
        raise RuntimeError("private database diagnostic")
    monkeypatch.setattr(publication_health, "record_publication_observation", unavailable)
    monkeypatch.setattr(scheduler, "create_backup", lambda **_: {"status": "completed", "backup_id": "saved"})
    monkeypatch.setattr(scheduler.backup_store, "merge_backup_verification_json", lambda *_: {})
    monkeypatch.setattr(scheduler.backup_store, "update_source_last_run", lambda *_: None)
    result = scheduler._process_due_source({"id": "source", "project_id": "project", "source_type": "project", "frequency": "daily"})
    assert result["status"] == "completed"
