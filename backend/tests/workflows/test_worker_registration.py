"""Verify the Agent Hub owner workflows run in SummitFlow's worker."""

from app.worker import _registered_workflows
from app.workflows.automation_dispatch import (
    automation_outbox_reconcile_wf,
    automation_owner_run_wf,
)


def test_agent_hub_owner_and_outbox_tasks_are_registered() -> None:
    registered = _registered_workflows()

    assert automation_owner_run_wf in registered
    assert automation_outbox_reconcile_wf in registered
