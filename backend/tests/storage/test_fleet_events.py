"""PostgreSQL ordering, retention, idempotency and asymmetric failure coverage."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
import redis

from app.storage import fleet_events as fleet
from app.storage.connection import get_connection


@pytest.fixture
def trace(ensure_test_project, monkeypatch):
    root = "root-" + uuid.uuid4().hex
    monkeypatch.setattr(fleet, "get_redis", lambda: MagicMock())
    yield ensure_test_project, root
    with get_connection() as conn:
        conn.execute("DELETE FROM events WHERE trace_id = %s", (root,))
        conn.commit()


def _append(trace, key, **kwargs):
    return fleet.append_fleet_event(*trace, source_key=key, event_type="source.changed", attributes={"revision": key}, **kwargs)


def test_retry_returns_identity_and_rejects_changed_content(trace):
    first = _append(trace, "revision:1")
    retry = _append(trace, "revision:1")
    assert first == retry
    assert first["sequence"] == 1
    with pytest.raises(fleet.SourceKeyConflict):
        fleet.append_fleet_event(*trace, source_key="revision:1", event_type="source.changed", attributes={"revision": "changed"})
    with pytest.raises(fleet.SourceKeyConflict):
        _append(trace, "revision:2", digest="0" * 64)
    assert len(fleet.read_fleet_page(*trace)) == 1


def test_earlier_writer_holds_allocation_until_commit(trace):
    """A later writer cannot commit sequence 2 before sequence 1 is visible."""
    project, root = trace
    entered = threading.Event()
    with get_connection() as conn, conn.cursor() as cur, ThreadPoolExecutor(max_workers=1) as executor:
        fleet._lock(cur, root)
        cur.execute(
            "INSERT INTO events (project_id, trace_id, source, level, visibility, event_type, "
            "stream_sequence, source_key, source_digest, timestamp) "
            "VALUES (%s, %s, 'fleet', 'info', 'internal', 'source.changed', 1, 'first', 'first', NOW() + INTERVAL '1 day')",
            trace,
        )

        def later():
            entered.set()
            return _append(trace, "second")

        future = executor.submit(later)
        assert entered.wait(2)
        assert not future.done()
        assert fleet.read_fleet_page(project, root) == []
        conn.commit()
        assert future.result(timeout=5)["sequence"] == 2
    # Deliberately reversed timestamps still read in commit-safe stream order.
    rows = fleet.read_fleet_page(*trace)
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[0]["timestamp"] > rows[1]["timestamp"]


def test_pruning_preserves_high_water_and_reports_gap(trace):
    for i in range(4):
        _append(trace, f"revision:{i}")
    with get_connection() as conn:
        conn.execute("UPDATE events SET timestamp = NOW() - INTERVAL '60 days' WHERE trace_id = %s", (trace[1],))
        conn.commit()
    assert fleet.cleanup_fleet_events(max_age_days=30) >= 3
    assert _append(trace, "revision:next")["sequence"] == 5
    with pytest.raises(fleet.StaleCursor) as stale:
        fleet.read_fleet_page(*trace, cursor=1)
    assert stale.value.next_sequence == 4
    assert [event["sequence"] for event in fleet.read_fleet_page(*trace, cursor=3)] == [4, 5]


def test_redis_failure_keeps_committed_history(trace, monkeypatch):
    client = MagicMock()
    client.publish.side_effect = redis.ConnectionError("fixture unavailable")
    monkeypatch.setattr(fleet, "get_redis", lambda: client)
    event = _append(trace, "revision:committed")
    assert fleet.read_fleet_page(*trace)[0]["id"] == event["id"]


def test_database_failure_does_not_publish(monkeypatch):
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = RuntimeError("database unavailable")
    client = MagicMock()
    monkeypatch.setattr(fleet, "get_connection", lambda: connection)
    monkeypatch.setattr(fleet, "get_redis", lambda: client)
    with pytest.raises(RuntimeError):
        _append(("fixture", "root-fixture"), "revision:failed")
    client.publish.assert_not_called()


def test_commit_failure_does_not_publish(monkeypatch):
    manager = MagicMock()
    connection = manager.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [None, (1,), ("id", "project", "root", 1, "key", "digest", "source.changed", {}, None)]
    connection.commit.side_effect = RuntimeError("commit unavailable")
    client = MagicMock()
    monkeypatch.setattr(fleet, "get_connection", lambda: manager)
    monkeypatch.setattr(fleet, "get_redis", lambda: client)
    with pytest.raises(RuntimeError, match="commit unavailable"):
        _append(("project", "root"), "key")
    client.publish.assert_not_called()


def test_publish_observes_committed_event(trace, monkeypatch):
    client = MagicMock()

    def wake(_channel, sequence):
        assert fleet.read_fleet_page(*trace)[-1]["sequence"] == int(sequence)

    client.publish.side_effect = wake
    monkeypatch.setattr(fleet, "get_redis", lambda: client)
    _append(trace, "revision:1")
    client.publish.assert_called_once()
