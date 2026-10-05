"""Local Codex queue transport: durable thread addressing, never terminal input."""

from __future__ import annotations

import hashlib
import json
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


def queue_native_thread(thread: str, instruction: str, client_id: str, project_root: str) -> dict[str, str]:
    """Submit once using native typed RPC and verify its correlated queued response.

    The queue persists across process exits. A receipt attests queue acceptance,
    never a process generation, agent execution, or native deduplication.
    """
    transcript_library()  # Make the existing protocol/launcher helpers importable.
    binary = import_module("codex_managed_capture").codex_binary()
    inputs = [{"type": "text", "text": instruction, "text_elements": []}]
    try:
        proc = subprocess.Popen(
            [binary, "app-server", "--listen", "stdio://"], cwd=project_root,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise NativeQueueError("native_server_unavailable", uncertain=False) from exc
    assert proc.stdin is not None and proc.stdout is not None
    # The RPC peer can stall indefinitely; use one request deadline without retries.
    deadline = time.monotonic() + RPC_TIMEOUT_SECONDS
    dispatched = False
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    pending = bytearray()

    def send(wire: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(wire) + "\n").encode())
        proc.stdin.flush()

    def receive(identifier: int) -> dict[str, Any]:
        import os

        while True:
            if time.monotonic() >= deadline:
                raise NativeQueueError("native_rpc_timeout", uncertain=dispatched)
            while b"\n" in pending:
                if time.monotonic() >= deadline:
                    raise NativeQueueError("native_rpc_timeout", uncertain=dispatched)
                line, _, rest = pending.partition(b"\n")
                if len(line) > MAX_RECEIPT_BYTES:
                    raise NativeQueueError("native_rpc_receipt_oversized", uncertain=dispatched)
                pending[:] = rest
                wire = json.loads(line)
                if isinstance(wire, dict) and wire.get("id") == identifier:
                    return wire
            if not selector.select(max(0, deadline - time.monotonic())):
                raise NativeQueueError("native_rpc_timeout", uncertain=dispatched)
            chunk = os.read(proc.stdout.fileno(), 65536)  # type: ignore[union-attr]
            if not chunk:
                raise NativeQueueError("native_rpc_closed", uncertain=dispatched)
            pending.extend(chunk)
            if len(pending) > MAX_RECEIPT_BYTES and (b"\n" not in pending or pending.find(b"\n") > MAX_RECEIPT_BYTES):
                raise NativeQueueError("native_rpc_receipt_oversized", uncertain=dispatched)

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "summitflow-native-delivery", "version": "1"},
            "capabilities": {"experimentalApi": True},
        }})
        if "error" in receive(1):
            raise NativeQueueError("native_initialize_rejected", uncertain=False)
        send({"method": "initialized", "params": {}})
        dispatched = True
        send({"id": 2, "method": "thread/queue/add", "params": {
            "threadId": thread, "input": inputs, "clientUserMessageId": client_id,
        }})
        response = receive(2)
        if "error" in response:
            # Do not retain arbitrary native error text or assume the rejection
            # proves a transactional rollback after dispatch.
            raise NativeQueueError("native_queue_rejected")
        queued = response.get("result", {}).get("queuedSubmission", {})
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
        raise NativeQueueError("native_rpc_outcome_unavailable", uncertain=dispatched) from exc
    finally:
        selector.close()
        with suppress(OSError):
            proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        proc.stdout.close()
