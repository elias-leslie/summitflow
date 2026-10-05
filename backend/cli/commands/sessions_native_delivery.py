"""One-shot local native delivery with reservations in SummitFlow's existing events."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.services.fleet_sessions import sanitized_instruction
from app.storage.fleet_events import append_fleet_event, read_fleet_page
from app.storage.projects import get_project_root_path

from ..lib.native_session_delivery import (
    NativeQueueError,
    queue_native_thread,
    verify_thread_binding,
)


def send_native_instruction(thread: str, instruction: str, *, project: str, source_key: str) -> dict[str, Any]:
    """Only the durable reservation winner dispatches; retained retries never resend."""
    project_root = get_project_root_path(project)
    if not project_root:
        raise ValueError("Native delivery requires a registered project root")
    identity = verify_thread_binding(thread, project, project_root)
    prompt = sanitized_instruction(instruction)
    if not source_key or len(source_key) > 256:
        raise ValueError("Native delivery requires a stable source key of 1-256 characters")
    # A separate trace in the same events table bounds reconciliation to this
    # exact source revision; no provider replay or second queue is introduced.
    address = f"{project}:{thread}:{source_key}"
    trace = "native-send:" + hashlib.sha256(address.encode()).hexdigest()
    client_id = str(uuid5(NAMESPACE_URL, "summitflow:" + trace))
    reserved = append_fleet_event(project, trace, source_key="request", event_type="native.delivery.reserved", attributes={
        "thread_id": identity["thread_id"], "project_id": project,
        "project_root": project_root, "source_key": source_key,
        "instruction_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "client_user_message_id": client_id, "capability": "native-thread",
    }, return_created=True)
    base = {"project_id": project, "thread_id": thread, "source_key": source_key,
            "request_id": reserved["id"], "client_user_message_id": client_id,
            "capability": "native-thread", "address_scope": "durable-thread", "retained": True, "observed": False}
    if not reserved["created"]:
        events = read_fleet_page(project, trace, limit=3)
        result = next((event for event in events if event["event_type"] == "native.delivery.result"), None)
        return {**base, **(result["attributes"] if result else {"delivery": "pending-or-uncertain"}), "replayed": False}
    try:
        receipt = queue_native_thread(thread, prompt, client_id, project_root)
        result = {**receipt, "delivery": "queued", "observed": False}
    except NativeQueueError as exc:
        result = {"delivery": "uncertain" if exc.uncertain else "failed", "reason": str(exc), "observed": False}
    append_fleet_event(project, trace, source_key="result", event_type="native.delivery.result", attributes=result)
    return {**base, **result, "replayed": False}
