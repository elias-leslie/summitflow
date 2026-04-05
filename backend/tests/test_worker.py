"""Tests for Hatchet worker registration."""

from __future__ import annotations


def test_main_registers_all_scheduled_workflows(mocker) -> None:
    """The worker should register every scheduled workflow defined by the app."""
    from app import worker
    from app.workflows import scheduled

    fake_runner = mocker.Mock()
    worker_factory = mocker.patch.object(worker.hatchet, "worker", return_value=fake_runner)

    worker.main()

    workflows = worker_factory.call_args.kwargs["workflows"]
    expected = {
        value
        for name, value in vars(scheduled).items()
        if name.endswith("_wf")
    }

    assert expected.issubset(set(workflows))
    fake_runner.start.assert_called_once()
