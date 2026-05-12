from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


class ToolResultLike:
    def model_dump(self) -> dict[str, Any]:
        return {"id": "tool-1", "content": {"ok": True}}


def test_emit_lifecycle_event_jsonifies_tool_output(mocker) -> None:
    from app.tasks.autonomous.exec_modules import ah_events

    mocker.patch.object(ah_events, "_get_session_ids", return_value=["sess-1"])
    post = mocker.patch.object(ah_events.httpx, "post", return_value=MagicMock())

    ah_events.emit_lifecycle_event(
        "task-1",
        "tool_result",
        "Tool result",
        tool_name="bash",
        tool_output={"result": ToolResultLike()},
    )

    payload = post.call_args.kwargs["json"]
    assert payload["tool_output"] == {
        "result": {"id": "tool-1", "content": {"ok": True}}
    }
