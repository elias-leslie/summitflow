"""Opt-in stdio execution owner. Observe the process we start, never another client."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from codex_managed_outbox import ManagedOutbox, OutboxFull
from jsonschema import Draft7Validator


def capture_enabled() -> bool:
    return os.environ.get("SUMMITFLOW_CODEX_MANAGED_CAPTURE", "0") == "1"


def conformance(binary: str, *, env: dict | None = None) -> tuple[str, str, dict]:
    from agent_hub.codex_protocol import SUPPORTED_VERSION, fingerprint, schemas

    version = subprocess.run([binary, "--version"], env=env, capture_output=True, check=True, text=True).stdout.strip()
    if version != SUPPORTED_VERSION:
        raise ValueError("unsupported_app_server_version")
    # Compare the actual binary's schema, not just its reported version string.
    with tempfile.TemporaryDirectory(prefix="codex-managed-protocol-") as directory:
        subprocess.run([binary, "app-server", "generate-json-schema", "--out", directory], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        installed = {name: json.loads(Path(directory, f"{name}.json").read_text()) for name in schemas()}
    actual = hashlib.sha256(json.dumps(installed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if actual != fingerprint():
        raise ValueError("unsupported_app_server_schema")
    return version, actual, {name: Draft7Validator(schema) for name, schema in installed.items()}


class ManagedCapture:
    """Wire routing and durable capture only; normalization belongs to Agent Hub."""

    def __init__(self, outbox: ManagedOutbox, *, project: str, namespace: str, version: str, fingerprint: str, validators: dict):
        self.outbox = outbox
        self.project = project
        self.namespace = namespace
        self.version = version
        self.fingerprint = fingerprint
        self.validators = validators
        self.pending: dict = {}
        self.approvals: dict = {}
        self.owned = {thread["id"] for thread in outbox.threads()}
        self.capturing = True
        self.failure: str | None = None
        self.connection_id = str(uuid4())

    def _retain(self, thread: str, kind: str, payload: dict, reference: dict | None = None):
        if not self.capturing:
            return
        try:
            return self.outbox.capture(thread, kind=kind, payload=payload, reference={"connection_id": self.connection_id, **(reference or {})})
        except (OSError, sqlite3.Error, OutboxFull):
            self.capturing = False
            self.failure = "outbox_full"
            with suppress(OSError, sqlite3.Error):
                self.outbox.health("outbox_full", gap=True)
            print("Managed Codex capture unavailable: durable outbox failed; rollout recovery required.", file=sys.stderr)

    def health_all(self, state: str, *, gap: bool = False):
        try:
            self.outbox.health(self.failure or state, gap=gap)
            for thread in self.owned:
                self._retain(thread, "capture_health", {"state": state, "capture_gaps": self.outbox.owner()["gaps"], "transport": "stdio", "provider_version": self.version})
        except (OSError, sqlite3.Error, OutboxFull):
            self.capturing = False
            self.failure = "outbox_full"

    def refresh_switch(self):
        if self.capturing and self.outbox.owner()["capture_disabled"]:
            self.health_all("disabled")
            self.capturing = False
            self.failure = "disabled"

    def own_thread(self, thread: str):
        if thread in self.owned:
            return
        owner = self.outbox.owner()
        self.outbox.add_thread(thread, self.project, {"namespace": self.namespace, "source_kind": "app_server", "producer_id": owner["producer"], "epoch": owner["epoch"], "collector_id": "summitflow/codex-managed", "provider_version": self.version, "schema_fingerprint": self.fingerprint, "thread_id": thread})
        self.owned.add(thread)
        self._retain(thread, "capture_health", {"state": "connected", "capture_gaps": owner["gaps"], "transport": "stdio", "provider_version": self.version})

    def client_message(self, wire: dict) -> dict | None:
        """Return a local rejection; capture never synthesizes approval responses."""
        self.refresh_switch()
        if self.failure == "disabled":
            return None
        method = wire.get("method")
        params = wire.get("params", {})
        if method:
            # Resume is restricted to our durable ownership registry. Forking an
            # external thread would be a takeover and is rejected as well.
            thread = params.get("threadId")
            if thread and thread not in self.owned:
                return {"id": wire.get("id"), "error": {"code": -32602, "message": "thread_is_not_owned_by_this_managed_session"}}
            if method == "initialize" and params.get("capabilities", {}).get("optOutNotificationMethods"):
                return {"id": wire.get("id"), "error": {"code": -32602, "message": "managed_capture_requires_notifications"}}
            if "id" in wire:
                # Keep only routing evidence in memory; never retain user prompts
                # or authentication RPCs in the capture spool.
                configuration = {key: params[key] for key in ("model", "effort", "reasoningEffort") if key in params}
                self.pending[wire["id"]] = (method, thread, configuration)
                if thread in self.owned and configuration:
                    self._retain(thread, "app_server_configuration", {"method": method, "direction": "request", "params": configuration}, {"rpc_id": wire["id"]})
        elif "id" in wire and wire["id"] in self.approvals:
            thread, request = self.approvals[wire["id"]]
            self._retain(thread, "approval_response", {"request_id": wire["id"], "response": wire.get("result"), "error": wire.get("error")}, {"request_id": wire["id"], "turn_id": request["params"].get("turnId"), "item_id": request["params"].get("itemId")})
        return None

    def server_message(self, wire: dict):
        self.refresh_switch()
        if not self.capturing:
            return
        if "method" not in wire:
            pending = self.pending.pop(wire.get("id"), None)
            if pending:
                method, parent, requested = pending
                thread = wire.get("result", {}).get("thread", {})
                if method in {"thread/start", "thread/fork"} and thread.get("id"):
                    self.own_thread(thread["id"])
                    if requested:
                        self._retain(thread["id"], "app_server_configuration", {"method": method, "direction": "request", "params": requested}, {"rpc_id": wire["id"]})
                subject = thread.get("id") or parent
                configured = {key: wire["result"][key] for key in ("model", "reasoningEffort") if key in wire.get("result", {})}
                if subject in self.owned and configured:
                    self._retain(subject, "app_server_configuration", {"method": method, "direction": "response", "params": configured}, {"rpc_id": wire["id"]})
                if method in {"thread/resume", "thread/read", "thread/fork"} and thread.get("id") in self.owned:
                    # Stored responses are explicitly snapshots, never synthesized
                    # live events or proof of complete missed notification history.
                    self._retain(thread["id"], "app_server_snapshot", {"method": method, "thread": thread}, {"parent_thread_id": parent if method == "thread/fork" else None})
            return
        params = wire.get("params", {})
        thread_obj = params.get("thread", {})
        thread = params.get("threadId") or thread_obj.get("id")
        if wire["method"] == "thread/started" and thread not in self.owned:
            source = thread_obj.get("source", {})
            subagent = source.get("subAgent", {}) if isinstance(source, dict) else {}
            parent = subagent.get("thread_spawn", {}).get("parent_thread_id") if isinstance(subagent, dict) else None
            starts = [method for method, _, _ in self.pending.values() if method in {"thread/start", "thread/fork"}]
            if thread and (parent in self.owned or starts):
                self.own_thread(thread)
        if thread not in self.owned:
            # Account/auth/global messages are deliberately outside session capture.
            # Unknown subject-bearing messages are a visible attribution limitation.
            if thread:
                self.health_all("capture_gap", gap=True)
                self.outbox.quarantine(wire)
            elif wire["method"] in {"applyPatchApproval", "execCommandApproval"} or not self.validators["ServerRequest" if "id" in wire else "ServerNotification"].is_valid(wire):
                # Legacy approval requests have no exact modern turn/item subject.
                # Validating their shape does not establish attribution; retain
                # them explicitly instead of silently treating them as globals.
                self.outbox.quarantine(wire)
                self.health_all("unsupported", gap=True)
                self.capturing = False
                self.failure = "unsupported"
            elif wire["method"].startswith(("thread/", "turn/", "item/", "process/", "command/")):
                self.outbox.quarantine(wire)
                self.health_all("capture_gap", gap=True)
            return
        schema = "ServerRequest" if "id" in wire else "ServerNotification"
        valid = self.validators[schema].is_valid(wire)
        position = self._retain(thread, "app_server_event", wire)
        if not valid:
            self.health_all("unsupported", gap=True)
            self.capturing = False
            self.failure = "unsupported"
            print("Managed Codex capture unavailable: unsupported notification shape; rollout recovery required.", file=sys.stderr)
        elif wire["method"].endswith("/requestApproval") and "id" in wire:
            self.approvals[wire["id"]] = (thread, wire)
        elif wire["method"] == "serverRequest/resolved":
            self.approvals.pop(params["requestId"], None)
        elif wire["method"] == "item/completed":
            item = params.get("item", {})
            if item.get("type") == "collabAgentToolCall" and item.get("tool") == "spawnAgent" and item.get("status") == "completed" and item.get("senderThreadId") == thread:
                for child in item["receiverThreadIds"]:
                    self.own_thread(child)
                    # Native children are owned by this process, but App Server
                    # does not imply live child subscription. The controlling
                    # client may explicitly resume its own child; never manufacture
                    # pre-subscription events from the parent's tool payload.
                    self.outbox.health("capture_gap", gap=True)
                    self._retain(child, "capture_health", {"state": "capture_gap", "capture_gaps": self.outbox.owner()["gaps"], "reason": "native_child_requires_subscription"}, {"parent_thread_id": thread, "parent_source_position": position})


def supervise(outbox: ManagedOutbox, *, project: str, namespace: str, binary: str, input_stream, output_stream, env: dict | None = None) -> int:
    """The controlling client supplies initialization, turns and approval decisions."""
    with outbox.lease():
        try:
            version, fingerprint, validators = conformance(binary, env=env)
        except ValueError:
            outbox.health("unsupported", gap=True)
            for thread in outbox.threads():
                outbox.capture(thread["id"], kind="capture_health", payload={"state": "unsupported", "reason": "installed_version_or_schema_unsupported"})
            raise
        capture = ManagedCapture(outbox, project=project, namespace=namespace, version=version, fingerprint=fingerprint, validators=validators)
        previous = outbox.owner()["health"]
        if capture.owned and previous != "new":
            # Restart/read/resume cannot recover omitted live notifications or
            # pending approvals. The gap survives even if rollout later recovers.
            capture.health_all("capture_gap", gap=True)
        proc = subprocess.Popen([binary, "app-server", "--listen", "stdio://"], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert proc.stdin is not None and proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(input_stream, selectors.EVENT_READ, "client")
        selector.register(proc.stdout, selectors.EVENT_READ, "server")
        buffers = {"client": b"", "server": b""}
        passthrough = False
        try:
            capture.health_all("connected")
            while selector.get_map():
                for key, _ in selector.select():
                    role = key.data
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        if role == "client":
                            proc.stdin.close()
                        else:
                            return proc.wait()
                        continue
                    if passthrough:
                        target = proc.stdin if role == "client" else output_stream
                        target.write(data)
                        target.flush()
                        continue
                    buffers[role] += data
                    if len(buffers[role]) > outbox.max_bytes:
                        capture.health_all("outbox_full", gap=True)
                        capture.capturing = False
                        capture.failure = "outbox_full"
                        # Bound an unterminated/oversized transport frame using
                        # the operator's quota. Do not retain a truncated payload.
                        # Once framing exceeds capture capacity, transparently
                        # forward both streams. Native execution must survive;
                        # rollout is the recovery source for this explicit gap.
                        passthrough = True
                        for buffered_role, pending_bytes in buffers.items():
                            target = proc.stdin if buffered_role == "client" else output_stream
                            target.write(pending_bytes)
                            target.flush()
                            buffers[buffered_role] = b""
                        continue
                    while b"\n" in buffers[role]:
                        line, buffers[role] = buffers[role].split(b"\n", 1)
                        try:
                            wire = json.loads(line)
                            if not isinstance(wire, dict):
                                raise ValueError("invalid_wire")
                            if role == "client":
                                rejection = capture.client_message(wire)
                                if rejection:
                                    output_stream.write(json.dumps(rejection).encode() + b"\n")
                                    output_stream.flush()
                                    continue
                                proc.stdin.write(line + b"\n")
                                proc.stdin.flush()
                            else:
                                # Local FULL commit precedes transport forwarding.
                                capture.server_message(wire)
                                output_stream.write(line + b"\n")
                                output_stream.flush()
                        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, OutboxFull) as error:
                            capture.health_all("outbox_full" if isinstance(error, (OSError, sqlite3.Error, OutboxFull)) else "unsupported", gap=True)
                            capture.capturing = False
                            # Preserve the native connection and its execution.
                            target = proc.stdin if role == "client" else output_stream
                            target.write(line + b"\n")
                            target.flush()
        finally:
            for pending in buffers.values():
                if pending:
                    capture.health_all("capture_gap", gap=True)
            capture.health_all("disconnected")
            selector.close()
            if not proc.stdin.closed:
                proc.stdin.close()
            if proc.poll() is None:
                # Only our own process is eligible for shutdown. Never find or
                # signal an independently launched Codex process.
                proc.terminate()
            proc.wait()
            proc.stdout.close()
    return 0


def codex_binary() -> str:
    binary = shutil.which("codex")
    if not binary:
        raise ValueError("codex_binary_unavailable")
    return binary
