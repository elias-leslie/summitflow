from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


class ToolResultLike:
    def model_dump(self) -> dict[str, Any]:
        return {"id": "tool-1", "content": {"ok": True}}


def test_emit_lifecycle_event_jsonifies_tool_output(mocker) -> None:
    from app.tasks.autonomous.exec_modules import ah_events

    mocker.patch.object(ah_events, "_get_session_ids", return_value=["sess-1"])
    client = MagicMock()
    client.__enter__.return_value = client
    mocker.patch.object(ah_events, "get_sync_client", return_value=client)

    ah_events.emit_lifecycle_event(
        "task-1",
        "tool_result",
        "Tool result",
        tool_name="bash",
        tool_output={"result": ToolResultLike()},
    )

    session_id, payload = client.append_session_event.call_args.args
    assert session_id == "sess-1"
    assert payload["tool_output"] == {
        "result": {"id": "tool-1", "content": {"ok": True}}
    }
