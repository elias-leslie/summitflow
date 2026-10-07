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
    exact_uuid,
    inspect_native_delivery,
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


def verify_native_instruction(thread: str, *, project: str, source_key: str,
                              request_id: str | None = None, queue_id: str | None = None,
                              client_id: str | None = None, timeout: float = 5) -> dict[str, Any]:
    """Resolve the exact retained send reservation; verification never writes or dispatches."""
    exact_uuid(thread)
    if not source_key or len(source_key) > 256:
        raise ValueError("Verification requires the prior stable source key")
    project_root = get_project_root_path(project)
    if not project_root:
        raise ValueError("Native verification requires a registered project root")
    verify_thread_binding(thread, project, project_root)
    address = f"{project}:{thread}:{source_key}"
    trace = "native-send:" + hashlib.sha256(address.encode()).hexdigest()
    events = read_fleet_page(project, trace, limit=3)
    requests = [event for event in events if event["event_type"] == "native.delivery.reserved"]
    results = [event for event in events if event["event_type"] == "native.delivery.result"]
    if len(requests) != 1 or len(results) > 1:
        raise ValueError("Retained native delivery receipt is unavailable or ambiguous")
    request = requests[0]
    attributes = request["attributes"]
    expected_client = str(uuid5(NAMESPACE_URL, "summitflow:" + trace))
    if (attributes.get("thread_id") != thread or attributes.get("project_id") != project
            or attributes.get("project_root") != project_root or attributes.get("source_key") != source_key
            or attributes.get("client_user_message_id") != expected_client
            or (request_id is not None and str(request["id"]) != request_id)
            or (client_id is not None and client_id != expected_client)):
        raise ValueError("Receipt identity does not match the retained native request")
    retained = results[0]["attributes"] if results else {}
    retained_queue = retained.get("queue_id")
    if retained_queue is not None:
        exact_uuid(retained_queue)
    if (retained.get("thread_id", thread) != thread
            or retained.get("client_user_message_id", expected_client) != expected_client
            or (queue_id is not None and retained_queue is not None and queue_id != retained_queue)):
        raise ValueError("Receipt identity does not match the retained native result")
    selected_queue = queue_id or retained_queue
    if selected_queue is not None:
        exact_uuid(selected_queue)
    base = {"schema_version": "native-delivery-verification.v1", "project_id": project,
            "thread_id": thread, "source_key": source_key, "request_id": request["id"],
            "queue_id": selected_queue, "client_user_message_id": expected_client,
            "generation_fenced": False, "resent": False}
    if retained.get("delivery") == "failed":
        return {**base, "delivery": "failed", "execution": "not_observed", "observed": False,
                "thread_state": "unknown", "reason": "retained_send_failed"}
    return {**base, **inspect_native_delivery(thread, expected_client, selected_queue,
                                              project_root, timeout=timeout)}
