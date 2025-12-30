"""Server-Sent Events (SSE) utilities."""

import json
from typing import Any


def format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Events (SSE) event.

    Args:
        event_type: Event type identifier
        data: Event data dict to serialize as JSON

    Returns:
        Formatted SSE event string with event type and JSON data
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
