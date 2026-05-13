from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous._escalation_helpers import (
    SUPERVISOR_GUIDANCE_TIMEOUT_SECONDS,
    call_supervisor,
)


@patch("app.tasks.autonomous._escalation_helpers.get_sync_client")
def test_call_supervisor_uses_bounded_control_plane_timeout(mock_get_client: MagicMock) -> None:
    """Supervisor guidance must not hang the autonomous worker indefinitely."""
    client = MagicMock()
    client.complete.return_value.content = "continue with a concrete fix"
    mock_get_client.return_value = client

    guidance = call_supervisor("Issue: no work product", "summitflow")

    assert guidance == "continue with a concrete fix"
    mock_get_client.assert_called_once_with(timeout=SUPERVISOR_GUIDANCE_TIMEOUT_SECONDS)
