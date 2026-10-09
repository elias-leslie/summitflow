"""Local Codex queue transport: durable thread addressing, never terminal input."""

from __future__ import annotations

import hashlib
import json
import math
import re
import select
import selectors
import subprocess
import time
from contextlib import suppress
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID

from ..commands.sessions_native_inspection import transcript_library

RPC_TIMEOUT_SECONDS = 30  # Existing fleet host RPC timeout.
MAX_RECEIPT_BYTES = 16384  # Existing fleet compact-event payload quota.


class NativeQueueError(ValueError):
    """A native rejection, or an outcome that must never be automatically replayed."""

    def __init__(self, reason: str, *, uncertain: bool = True) -> None:
        self.uncertain = uncertain
        super().__init__(reason)


def exact_uuid(value: str) -> str:
    try:
        normalized = str(UUID(value))
    except ValueError as exc:
        raise ValueError("An exact canonical Codex thread UUID is required") from exc
    if value != normalized:
        raise ValueError("An exact canonical Codex thread UUID is required")
    return normalized


def verify_thread_binding(thread: str, project: str, project_root: str) -> dict[str, str]:
    """Reuse immutable sync bindings and exact local native provenance, including offline threads."""
    exact_uuid(thread)
    library = transcript_library()
    bindings = import_module("codex_sync_bindings").load_snapshot()
    binding = bindings.get(thread)
    root = Path(project_root).resolve()
    if binding is not None and (binding.project_id != project or Path(binding.project_root).resolve() != root):
        raise ValueError("Native thread immutable binding conflicts with registered project")
    snapshot = library.discover_open_transcripts()
    matches = [
        info for path in library.TRANSCRIPTS_ROOT.rglob(f"*{thread}.jsonl")
        if (info := library.read_transcript_info(path, open_snapshot=snapshot)) is not None and info.session_id == thread
    ]
    if len(matches) != 1:
        raise ValueError("Native thread provenance is unavailable or ambiguous")
    info = matches[0]
    if info.identity_error or info.ownership_ambiguous:
        raise ValueError("Native thread provenance is ambiguous")
    if (binding is not None and binding.parent_session_id) or info.parent_session_id or info.agent_path not in (None, "/root"):
        raise ValueError("Direct native delivery to spawned subagents is unsupported")
    runner = import_module("codex_sync_runner")
    context, _, _, git_verified = runner._resolve_project_context(info, binding)
    if (context is None or context.get("project_id") != project
            or Path(str(context.get("repo_root") or "")).resolve() != root):
        raise ValueError("Native transcript has no matching registered canonical project")
    mapping, _ = runner._project_mapping_state(info, context, explicitly_bound=binding is not None, transcript_git_verified=git_verified)
    if mapping not in {"matched", "explicit_binding", "git_only"}:
        raise ValueError("Native thread owner conflicts with registered project")
    if binding is None and not info.cwd.resolve().is_relative_to(root):
        raise ValueError("Native transcript directory conflicts with registered project binding")
    fingerprint = binding.fingerprint if binding is not None else hashlib.sha256(json.dumps({"project_id": project, "project_root": str(root)}, sort_keys=True).encode()).hexdigest()
    return {"thread_id": thread, "project_id": project, "binding_fingerprint": fingerprint}


class NativeRPC:
    """The existing local stdio transport, with one deadline and bounded receipts."""

    def __init__(self, project_root: str, timeout: float):
        transcript_library()
        binary = import_module("codex_managed_capture").codex_binary()
        try:
            self.proc = subprocess.Popen(
                [binary, "app-server", "--listen", "stdio://"], cwd=project_root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise NativeQueueError("native_server_unavailable", uncertain=False) from exc
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.deadline = time.monotonic() + timeout
        self.dispatched = False
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.pending = bytearray()
        self.identifier = 0

    def __enter__(self) -> NativeRPC:
        return self

    def __exit__(self, *_args: object) -> None:
        self.selector.close()
        assert self.proc.stdin is not None and self.proc.stdout is not None
        with suppress(OSError):
            self.proc.stdin.close()
        # Shutdown is bounded separately, never wait indefinitely for an RPC peer.
        try:
            self.proc.wait(timeout=.25)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=.25)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()

    def send(self, wire: dict[str, Any]) -> None:
        import os

        assert self.proc.stdin is not None
        output = memoryview((json.dumps(wire) + "\n").encode())
        fd = self.proc.stdin.fileno()
        os.set_blocking(fd, False)
        while output:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [fd], [], max(0, remaining))[1]:
                raise NativeQueueError("native_rpc_timeout", uncertain=self.dispatched)
            try:
                output = output[os.write(fd, output):]
            except BlockingIOError:
                continue

    def receive(self, identifier: int) -> dict[str, Any]:
        import os

        while True:
            if time.monotonic() >= self.deadline:
                raise NativeQueueError("native_rpc_timeout", uncertain=self.dispatched)
            while b"\n" in self.pending:
                if time.monotonic() >= self.deadline:
                    raise NativeQueueError("native_rpc_timeout", uncertain=self.dispatched)
                line, _, rest = self.pending.partition(b"\n")
                if len(line) > MAX_RECEIPT_BYTES:
                    raise NativeQueueError("native_rpc_receipt_oversized", uncertain=self.dispatched)
                self.pending[:] = rest
                wire = json.loads(line)
                if isinstance(wire, dict) and wire.get("id") == identifier:
                    return wire
            if not self.selector.select(max(0, self.deadline - time.monotonic())):
                raise NativeQueueError("native_rpc_timeout", uncertain=self.dispatched)
            assert self.proc.stdout is not None
            chunk = os.read(self.proc.stdout.fileno(), MAX_RECEIPT_BYTES + 1)
            if not chunk:
                raise NativeQueueError("native_rpc_closed", uncertain=self.dispatched)
            self.pending.extend(chunk)
            if len(self.pending) > MAX_RECEIPT_BYTES and (b"\n" not in self.pending or self.pending.find(b"\n") > MAX_RECEIPT_BYTES):
                raise NativeQueueError("native_rpc_receipt_oversized", uncertain=self.dispatched)

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.identifier += 1
        self.send({"id": self.identifier, "method": method, "params": params})
        response = self.receive(self.identifier)
        if "error" in response:
            error = response["error"]
            reason = "native_method_unavailable" if isinstance(error, dict) and error.get("code") == -32601 else "native_read_rejected"
            raise NativeQueueError(reason, uncertain=self.dispatched)
        result = response.get("result")
        if not isinstance(result, dict):
            raise NativeQueueError("native_rpc_receipt_mismatch", uncertain=self.dispatched)
        return result

    def initialize(self) -> None:
        try:
            self.call("initialize", {
                "clientInfo": {"name": "summitflow-native-delivery", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
        except NativeQueueError as exc:
            if str(exc) in {"native_method_unavailable", "native_read_rejected"}:
                raise NativeQueueError("native_initialize_rejected", uncertain=False) from exc
            raise
        self.send({"method": "initialized", "params": {}})


def queue_native_thread(thread: str, instruction: str, client_id: str, project_root: str) -> dict[str, str]:
    """Submit once; correlated acceptance is neither consumption nor a generation fence."""
    inputs = [{"type": "text", "text": instruction, "text_elements": []}]
    rpc: NativeRPC | None = None
    try:
        with NativeRPC(project_root, RPC_TIMEOUT_SECONDS) as rpc:
            rpc.initialize()
            rpc.dispatched = True
            try:
                result = rpc.call("thread/queue/add", {
                    "threadId": thread, "input": inputs, "clientUserMessageId": client_id,
                })
            except NativeQueueError as exc:
                if str(exc) in {"native_method_unavailable", "native_read_rejected"}:
                    raise NativeQueueError("native_queue_rejected") from exc
                raise
            queued = result.get("queuedSubmission", {})
            if queued.get("input") != inputs or queued.get("clientUserMessageId") != client_id:
                raise NativeQueueError("native_queue_receipt_mismatch")
            try:
                queue_id = exact_uuid(queued.get("id", ""))
            except (ValueError, TypeError, AttributeError) as exc:
                raise NativeQueueError("native_queue_receipt_mismatch") from exc
            return {"thread_id": thread, "queue_id": queue_id, "client_user_message_id": client_id}
    except NativeQueueError:
        raise
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise NativeQueueError("native_rpc_outcome_unavailable", uncertain=rpc.dispatched if rpc else False) from exc


def _native_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise NativeQueueError("native_identity_mismatch", uncertain=False)
    return value


def _pages(rpc: NativeRPC, method: str, params: dict[str, Any]):
    """Bound pagination by the invocation deadline; cursors/content never escape."""
    cursor = None
    seen = set()
    while True:
        result = rpc.call(method, {**params, **({"cursor": cursor} if cursor else {})})
        data = result.get("data")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise NativeQueueError("native_rpc_receipt_mismatch", uncertain=False)
        yield from data
        cursor = result.get("nextCursor")
        if cursor is None:
            return
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise NativeQueueError("native_rpc_receipt_mismatch", uncertain=False)
        seen.add(cursor)


def _thread_status(rpc: NativeRPC, thread: str) -> tuple[str, list[str]]:
    result = rpc.call("thread/read", {"threadId": thread, "includeTurns": False})
    metadata = result.get("thread")
    if not isinstance(metadata, dict) or metadata.get("id") != thread:
        raise NativeQueueError("native_identity_mismatch", uncertain=False)
    status = metadata.get("status")
    if not isinstance(status, dict):
        raise NativeQueueError("native_status_unavailable", uncertain=False)
    kind = status.get("type")
    states = {"notLoaded": "offline_unloaded", "idle": "idle", "active": "active", "systemError": "system_error"}
    if kind not in states:
        raise NativeQueueError("native_status_unavailable", uncertain=False)
    flags = status.get("activeFlags", [])
    if (not isinstance(flags, list) or any(flag not in {"waitingOnApproval", "waitingOnUserInput"} for flag in flags)
            or (kind == "active" and "activeFlags" not in status)):
        raise NativeQueueError("native_status_unavailable", uncertain=False)
    return states[kind], flags


def inspect_native_delivery(thread: str, client_id: str, queue_id: str | None,
                            project_root: str, *, timeout: float = 5) -> dict[str, Any]:
    """Read typed queue/history; only exact user-message clientId proves consumption.

    Installed 0.160.1 schema reference: thread/read.status, queue/list.data,
    items/list.data[].item.clientId + turnId, turns/list.data[].status.
    Missing methods/fields fail closed; no resume, start, queue mutation or resend.
    """
    exact_uuid(thread)
    exact_uuid(client_id)
    if queue_id is not None:
        exact_uuid(queue_id)
    if not math.isfinite(timeout) or not 0 < timeout <= RPC_TIMEOUT_SECONDS:
        raise ValueError("Verification timeout must be >0 and <=30 seconds")
    result: dict[str, Any] = {"delivery": "unknown", "execution": "unknown", "observed": False,
                              "thread_state": "unknown", "queue_id": queue_id, "generation_fenced": False}
    try:
        with NativeRPC(project_root, timeout) as rpc:
            rpc.initialize()
            state, _flags = _thread_status(rpc, thread)
            result["thread_state"] = state
            queued = None
            for row in _pages(rpc, "thread/queue/list", {"threadId": thread, "limit": 1}):
                if row.get("clientUserMessageId") == client_id:
                    candidate = exact_uuid(row.get("id", ""))
                    if queued is not None or (queue_id is not None and candidate != queue_id):
                        raise NativeQueueError("native_identity_mismatch", uncertain=False)
                    if not isinstance(row.get("input"), list):
                        raise NativeQueueError("native_rpc_receipt_mismatch", uncertain=False)
                    queued = candidate
                elif queue_id is not None and row.get("id") == queue_id:
                    raise NativeQueueError("native_identity_mismatch", uncertain=False)
            if queued is not None:
                return {**result, "delivery": "queued", "execution": "offline_unloaded" if state == "offline_unloaded" else "not_observed",
                        "queue_id": queued}
            match = None
            for entry in _pages(rpc, "thread/items/list", {"threadId": thread, "limit": 1, "sortDirection": "desc"}):
                item = entry.get("item")
                if not isinstance(item, dict):
                    raise NativeQueueError("native_rpc_receipt_mismatch", uncertain=False)
                if item.get("type") == "userMessage" and item.get("clientId") == client_id:
                    if match is not None:
                        raise NativeQueueError("native_consumption_ambiguous", uncertain=False)
                    match = (_native_id(entry.get("turnId")), _native_id(item.get("id")))
            if match is None:
                return {**result, "delivery": "deleted-or-unknown",
                        "execution": "offline_unloaded" if state == "offline_unloaded" else "unknown",
                        "reason": "queue_absent_without_correlated_item"}
            turn_id, item_id = match
            result.update(delivery="consumed", observed=True, turn_id=turn_id, item_id=item_id)
            turn_status = None
            latest = None
            for turn in _pages(rpc, "thread/turns/list", {
                "threadId": thread, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
            }):
                identity = _native_id(turn.get("id"))
                status = turn.get("status")
                if status not in {"completed", "failed", "interrupted", "inProgress"}:
                    raise NativeQueueError("native_status_unavailable", uncertain=False)
                if latest is None:
                    latest = identity
                if identity == turn_id:
                    turn_status = status
                    break
            state, flags = _thread_status(rpc, thread)
            result["thread_state"] = state
            if turn_status in {"completed", "failed", "interrupted"}:
                result["execution"] = turn_status
            elif state == "offline_unloaded":
                result["execution"] = "offline_unloaded"
            elif turn_status == "inProgress" and state == "active" and latest == turn_id:
                # Bracket runtime flags with the correlated current turn. A
                # later unrelated active turn must not inherit this receipt.
                current = rpc.call("thread/turns/list", {
                    "threadId": thread, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
                }).get("data")
                if (isinstance(current, list) and len(current) == 1 and isinstance(current[0], dict)
                        and current[0].get("id") == turn_id and current[0].get("status") == "inProgress"):
                    result["execution"] = ("waiting_approval" if "waitingOnApproval" in flags else
                                           "waiting_user_input" if "waitingOnUserInput" in flags else "active")
                else:
                    result["reason"] = "correlated_turn_changed_during_inspection"
            else:
                result["reason"] = "correlated_turn_not_current_or_status_unknown"
            return result
    except NativeQueueError as exc:
        return {**result, "execution": "unknown", "reason": str(exc)}
    except (OSError, ValueError, TypeError, AttributeError):
        return {**result, "execution": "unknown", "reason": "native_rpc_outcome_unavailable"}
