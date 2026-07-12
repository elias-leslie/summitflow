from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.tasks.autonomous import pickup, pickup_dispatch


def test_immediate_dispatch_without_callback_fails_before_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_task = MagicMock()
    monkeypatch.setattr(pickup.task_store, "get_task", get_task)

    result = pickup.dispatch_task_immediate("task-1", "summitflow")

    assert result == {
        "status": "error",
        "task_id": "task-1",
        "reason": "dispatch_callback_required",
    }
    get_task.assert_not_called()


def test_execution_enqueue_failure_releases_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    claim = MagicMock(return_value={"id": "task-1", "claimed_by": "pickup-summitflow"})
    release = MagicMock()
    enqueue = MagicMock(side_effect=RuntimeError("hatchet unavailable"))
    monkeypatch.setattr(pickup_dispatch, "_execution_preflight_ok", lambda *_args: True)
    monkeypatch.setattr(pickup_dispatch, "claim_task", claim)
    monkeypatch.setattr(pickup_dispatch, "release_task", release)

    with pytest.raises(RuntimeError, match="hatchet unavailable"):
        pickup_dispatch.dispatch_to_execution(
            "task-1",
            "summitflow",
            enqueue,
        )

    claimed_worker_id = claim.call_args.args[1]
    assert claimed_worker_id.startswith("pickup-summitflow-")
    claim.assert_called_once_with(
        "task-1",
        claimed_worker_id,
        lock_duration_minutes=60,
    )
    release.assert_called_once_with(
        "task-1",
        expected_worker_id=claimed_worker_id,
    )


def test_claim_release_failure_preserves_enqueue_error(monkeypatch: pytest.MonkeyPatch) -> None:
    claim = MagicMock(return_value={"id": "task-1", "claimed_by": "pickup-summitflow"})
    enqueue = MagicMock(side_effect=RuntimeError("hatchet unavailable"))
    monkeypatch.setattr(pickup_dispatch, "_execution_preflight_ok", lambda *_args: True)
    monkeypatch.setattr(pickup_dispatch, "claim_task", claim)
    monkeypatch.setattr(
        pickup_dispatch,
        "release_task",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )

    with pytest.raises(RuntimeError, match="hatchet unavailable"):
        pickup_dispatch.dispatch_to_execution("task-1", "summitflow", enqueue)


def test_successful_execution_enqueue_keeps_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    claim = MagicMock(return_value={"id": "task-1", "claimed_by": "pickup-summitflow"})
    release = MagicMock()
    enqueue = MagicMock()
    monkeypatch.setattr(pickup_dispatch, "_execution_preflight_ok", lambda *_args: True)
    monkeypatch.setattr(pickup_dispatch, "claim_task", claim)
    monkeypatch.setattr(pickup_dispatch, "release_task", release)

    assert pickup_dispatch.dispatch_to_execution("task-1", "summitflow", enqueue)

    enqueue.assert_called_once_with("execute", "task-1", "summitflow")
    release.assert_not_called()


def test_repeated_pickups_use_unique_claim_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    claim = MagicMock(
        side_effect=lambda task_id, worker_id, **_kwargs: {
            "id": task_id,
            "claimed_by": worker_id,
        }
    )
    monkeypatch.setattr(pickup_dispatch, "_execution_preflight_ok", lambda *_args: True)
    monkeypatch.setattr(pickup_dispatch, "claim_task", claim)

    assert pickup_dispatch.dispatch_to_execution("task-1", "summitflow", MagicMock())
    assert pickup_dispatch.dispatch_to_execution("task-1", "summitflow", MagicMock())

    first_owner = claim.call_args_list[0].args[1]
    second_owner = claim.call_args_list[1].args[1]
    assert first_owner.startswith("pickup-summitflow-")
    assert second_owner.startswith("pickup-summitflow-")
    assert first_owner != second_owner
