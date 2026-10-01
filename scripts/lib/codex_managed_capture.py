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
    from codex_managed_delivery import managed_settings

    return managed_settings().get("SUMMITFLOW_CODEX_MANAGED_CAPTURE", "0") == "1"


_CONFORMANCE_CACHE: dict = {}


def conformance(binary: str, *, env: dict | None = None, outbox: ManagedOutbox | None = None) -> tuple[str, str, dict]:
    from agent_hub.codex_protocol import SUPPORTED_VERSIONS, fingerprint, schemas

    version = subprocess.run([binary, "--version"], env=env, capture_output=True, check=True, text=True, timeout=10).stdout.strip()
    installed = None
    reference_version = version
    try:
        expected = fingerprint(provider_version=version)
        expected_schemas = schemas(provider_version=version)
    except (ValueError, KeyError) as error:
        approved = (outbox.metadata("approved_profiles") if outbox else {}).get(version, {})
        environment = os.environ if env is None else env
        if approved.get("qualified"):
            reference_version = approved["reference_profile_version"]
            expected_schemas = schemas(provider_version=reference_version)
            expected = fingerprint(provider_version=reference_version)
            if expected != approved.get("schema_fingerprint"):
                raise ValueError("unsupported_authority_profile") from error
        elif environment.get("SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION") == "1" and {entry.name for entry in Path("/sys/class/net").iterdir()} == {"lo"}:
            # Candidate aliases are executable only inside the qualification
            # namespace. Normal execution requires Agent Hub's durable approval.
            with tempfile.TemporaryDirectory(prefix="codex-candidate-protocol-") as directory:
                subprocess.run([binary, "app-server", "generate-json-schema", "--out", directory], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)
                installed = {name: json.loads(Path(directory, f"{name}.json").read_text()) for name in ("ServerNotification", "ServerRequest")}
            expected = hashlib.sha256(json.dumps(installed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            reference_version = next((candidate for candidate in SUPPORTED_VERSIONS if fingerprint(candidate) == expected), None)
            if not reference_version:
                raise ValueError("unsupported_candidate_schema") from error
            expected_schemas = schemas(reference_version)
        else:
            raise ValueError("unsupported_app_server_version") from error
    environment = os.environ if env is None else env
    executable_paths = [Path(binary).resolve()]
    from codex_managed_update import native_binary

    native = native_binary(binary)
    if native not in executable_paths:
        executable_paths.append(native)
    real = Path(environment.get("CODEX_REAL", str(Path(environment.get("HOME", str(Path.home()))) / ".local/bin/codex-real")))
    if real.is_file():
        executable_paths.append(real.resolve())
        resolved_native = native_binary(str(real))
        if resolved_native not in executable_paths:
            executable_paths.append(resolved_native)
    identity = tuple((str(path), path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns) for path in executable_paths)
    key = (identity, version, expected, reference_version, "stdio-client-initialize-full-notifications-v1")
    if key in _CONFORMANCE_CACHE:
        return _CONFORMANCE_CACHE[key]
    cache_key = hashlib.sha256(json.dumps(key).encode()).hexdigest()
    if outbox and outbox.metadata("conformance").get("binary_profile_key") == cache_key:
        result = version, expected, {name: Draft7Validator(schema) for name, schema in expected_schemas.items()}
        _CONFORMANCE_CACHE[key] = result
        return result
    # Compare the actual binary's schema, not just its reported version string.
    if installed is None:
        with tempfile.TemporaryDirectory(prefix="codex-managed-protocol-") as directory:
            subprocess.run([binary, "app-server", "generate-json-schema", "--out", directory], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)
            installed = {name: json.loads(Path(directory, f"{name}.json").read_text()) for name in expected_schemas}
    actual = hashlib.sha256(json.dumps(installed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if actual != expected:
        raise ValueError("unsupported_app_server_schema")
    result = version, actual, {name: Draft7Validator(schema) for name, schema in installed.items()}
    _CONFORMANCE_CACHE.clear()
    _CONFORMANCE_CACHE[key] = result
    if outbox:
        outbox.metadata("conformance", {"binary_profile_key": cache_key})
    return result


class ManagedCapture:
    """Wire routing and durable capture only; normalization belongs to Agent Hub."""

    def __init__(self, outbox: ManagedOutbox, *, project: str, namespace: str, version: str, fingerprint: str, validators: dict, enforce_handshake: bool = False):
        self.outbox = outbox
        self.project = project
        self.namespace = namespace
        self.version = version
        self.fingerprint = fingerprint
        self.validators = validators
        self.pending: dict = {}
        self.approvals: dict = {}
        try:
            self.owned = {thread["id"] for thread in outbox.threads()}
        except (OSError, sqlite3.Error):
            self.owned = set()
        self.capturing = True
        self.failure: str | None = None
        self.connection_id = str(uuid4())
        self.enforce_handshake = enforce_handshake
        self.initialized = not enforce_handshake
        self.initialize_response = False
        self.subscription_queue: list[dict] = []
        self.subscribed: set[str] = set()
        self.client_modified = False

    def quarantine(self, wire: dict):
        owner = self.outbox.owner()
        registration = {"project_id": self.project, "namespace": self.namespace, "producer_id": owner["producer"], "epoch": owner["epoch"], "collector_id": "summitflow/codex-managed", "provider_version": self.version, "schema_fingerprint": self.fingerprint, "generation": self.outbox.metadata("protocol_generation").get("generation", 0)}
        self.outbox.quarantine(wire, registration=registration, reference={"connection_id": self.connection_id})

    def subscribe(self, thread: str):
        if not self.capturing or thread not in self.owned or thread in self.subscribed or not self.initialized:
            return
        self.subscribed.add(thread)
        identifier = f"summitflow-managed-{self.connection_id}-{len(self.subscribed)}"
        wire = {"id": identifier, "method": "thread/resume", "params": {"threadId": thread}}
        self.pending[identifier] = ("thread/resume", thread, {})
        self.subscription_queue.append(wire)

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

    def health_all(self, state: str, *, gap: bool = False, reason: str | None = None):
        try:
            self.outbox.health(self.failure or state, gap=gap)
            for thread in self.owned:
                payload = {"state": state, "capture_gaps": self.outbox.owner()["gaps"], "transport": "stdio", "provider_version": self.version}
                if reason:
                    payload["reason"] = reason
                self._retain(thread, "capture_health", payload)
        except (OSError, sqlite3.Error, OutboxFull):
            self.capturing = False
            self.failure = "outbox_full"

    def refresh_switch(self):
        if self.capturing and self.outbox.owner()["capture_disabled"]:
            self.health_all("disabled")
            self.capturing = False
            self.failure = "disabled"
            self.approvals.clear()
        elif self.failure == "disabled" and not self.outbox.owner()["capture_disabled"]:
            self.capturing = True
            self.failure = None
            self.health_all("capture_gap", gap=True, reason="capture_reenabled_after_disabled_interval")
            self.health_all("connected")

    def own_thread(self, thread: str):
        if thread in self.owned:
            return
        self.owned.add(thread)
        try:
            owner = self.outbox.owner()
            self.outbox.add_thread(thread, self.project, {"namespace": self.namespace, "source_kind": "app_server", "producer_id": owner["producer"], "epoch": owner["epoch"], "collector_id": "summitflow/codex-managed", "provider_version": self.version, "schema_fingerprint": self.fingerprint, "thread_id": thread})
        except (OSError, sqlite3.Error, OutboxFull):
            # Ownership is proven by this process's own start/spawn response.
            # A failed local catalog write cannot strand native execution.
            self.capturing = False
            self.failure = "outbox_full"
            with suppress(OSError, sqlite3.Error):
                self.outbox.health("outbox_full", gap=True)
            return
        self._retain(thread, "capture_health", {"state": "connected", "capture_gaps": owner["gaps"], "transport": "stdio", "provider_version": self.version})

    def client_message(self, wire: dict) -> dict | None:
        """Return a local rejection; capture never synthesizes approval responses."""
        self.refresh_switch()
        self.client_modified = False
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
            if self.enforce_handshake and method == "initialized":
                if not self.initialize_response:
                    return {"id": wire.get("id"), "error": {"code": -32600, "message": "managed_initialize_response_required"}}
                self.initialized = True
                self.health_all("initialized")
            elif self.enforce_handshake and method != "initialize" and not self.initialized:
                return {"id": wire.get("id"), "error": {"code": -32002, "message": "managed_client_initialization_required"}}
            if self.capturing and thread in self.owned and method in {"turn/start", "turn/steer"} and "clientUserMessageId" not in params:
                params["clientUserMessageId"] = str(uuid4())
                self.client_modified = True
            if "id" in wire:
                # Keep only routing evidence in memory; never retain user prompts
                # or authentication RPCs in the capture spool.
                configuration = {key: params[key] for key in ("model", "effort", "reasoningEffort", "clientUserMessageId") if key in params}
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
            # Disabled capture still tracks the own process's RPC lifecycle so
            # initialization and new owned threads work without relaxing fencing.
            if "method" not in wire and isinstance(wire.get("result"), dict):
                pending = self.pending.pop(wire.get("id"), None)
                if pending:
                    method, _, _ = pending
                    if method == "initialize":
                        self.initialize_response = True
                    thread = wire["result"].get("thread")
                    if method in {"thread/start", "thread/fork"} and isinstance(thread, dict) and isinstance(thread.get("id"), str):
                        self.own_thread(thread["id"])
            return
        if "method" not in wire:
            if not isinstance(wire.get("result", {}), dict):
                self.quarantine(wire)
                self.health_all("unsupported", gap=True)
                self.capturing = False
                self.failure = "unsupported"
                return
            pending = self.pending.pop(wire.get("id"), None)
            if pending:
                method, parent, requested = pending
                if method == "initialize" and "result" in wire:
                    self.initialize_response = True
                if str(wire.get("id", "")).startswith(f"summitflow-managed-{self.connection_id}-") and "error" in wire:
                    self.health_all("capture_gap", gap=True)
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
                    reference = {"parent_thread_id": parent if method == "thread/fork" else None}
                    if str(wire.get("id", "")).startswith(f"summitflow-managed-{self.connection_id}-"):
                        reference["managed_subscription"] = True
                    self._retain(thread["id"], "app_server_snapshot", {"method": method, "thread": thread}, reference)
            return
        params = wire.get("params", {})
        schema = "ServerRequest" if "id" in wire else "ServerNotification"
        if not isinstance(params, dict) or not isinstance(wire.get("method"), str):
            self.quarantine(wire)
            self.health_all("unsupported", gap=True)
            self.capturing = False
            self.failure = "unsupported"
            return
        thread_obj = params.get("thread", {})
        if not isinstance(thread_obj, dict):
            thread_obj = {}
        thread = params.get("threadId") or thread_obj.get("id")
        if thread is not None and not isinstance(thread, str):
            self.quarantine(wire)
            self.health_all("unsupported", gap=True)
            self.capturing = False
            self.failure = "unsupported"
            return
        if wire["method"] == "thread/started" and thread not in self.owned:
            source = thread_obj.get("source", {})
            subagent = source.get("subAgent", {}) if isinstance(source, dict) else {}
            spawn = subagent.get("thread_spawn", {}) if isinstance(subagent, dict) else {}
            parent = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
            starts = [method for method, _, _ in self.pending.values() if method in {"thread/start", "thread/fork"}]
            if thread and (parent in self.owned or starts):
                self.own_thread(thread)
                if parent in self.owned:
                    self.subscribe(thread)
        if thread not in self.owned:
            # Account/auth/global messages are deliberately outside session capture.
            # Unknown subject-bearing messages are a visible attribution limitation.
            if thread:
                self.health_all("capture_gap", gap=True, reason="subject_ownership_not_yet_proven")
                self.quarantine(wire)
            elif wire["method"] in {"applyPatchApproval", "execCommandApproval"} or not self.validators["ServerRequest" if "id" in wire else "ServerNotification"].is_valid(wire):
                # Legacy approval requests have no exact modern turn/item subject.
                # Validating their shape does not establish attribution; retain
                # them explicitly instead of silently treating them as globals.
                self.quarantine(wire)
                self.health_all("unsupported", gap=True)
                self.capturing = False
                self.failure = "unsupported"
            elif wire["method"].startswith(("thread/", "turn/", "item/", "process/", "command/")):
                self.quarantine(wire)
                self.health_all("capture_gap", gap=True)
            return
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
                    self.subscribe(child)


def supervise(outbox: ManagedOutbox, *, project: str, namespace: str, binary: str, input_stream, output_stream, env: dict | None = None) -> int:
    """The controlling client supplies initialization, turns and approval decisions."""
    with outbox.lease():
        storage_preflight_failed = False
        try:
            threads = outbox.threads()
            binding = outbox.metadata("project")
        except (OSError, sqlite3.Error):
            threads, binding = [], {}
            storage_preflight_failed = True
        if any(thread["project"] != project for thread in threads):
            raise ValueError("managed_outbox_project_binding_mismatch")
        if binding and binding.get("project_id") != project:
            raise ValueError("managed_outbox_project_binding_mismatch")
        with suppress(OSError, sqlite3.Error, OutboxFull):
            outbox.metadata("project", {"project_id": project})
        unsupported = False
        failure = None
        pinned_lease = None
        try:
            if storage_preflight_failed:
                raise OutboxFull("managed_storage_preflight_failed")
            from codex_managed_update import (
                pin_runtime,
                reclaim_runtimes,
                runtime_lease,
                update_lease,
            )

            with update_lease(outbox):
                binary = pin_runtime(outbox, binary)
                candidate_lease = runtime_lease(binary)
                candidate_lease.__enter__()
                pinned_lease = candidate_lease
                reclaim_runtimes(outbox, outbox.metadata("update"))
                outbox.metadata("running_runtime", {"binary": binary})
            version, fingerprint, validators = conformance(binary, env=env, outbox=outbox)
            outbox.rotate_protocol(version=version, fingerprint=fingerprint)
        except (ValueError, OSError, sqlite3.Error, OutboxFull, subprocess.SubprocessError) as error:
            failure = "outbox_full" if isinstance(error, (OSError, sqlite3.Error, OutboxFull)) else "unsupported"
            with suppress(OSError, sqlite3.Error, OutboxFull):
                outbox.health(failure, gap=True)
                for thread in outbox.threads():
                    outbox.capture(thread["id"], kind="capture_health", payload={"state": failure, "reason": "installed_version_schema_or_durable_storage_unavailable"})
            version, fingerprint, validators = "unknown", "unknown", {}
            unsupported = True
            print("Managed Codex capture unavailable; native execution continues with rollout recovery.", file=sys.stderr)
        with suppress(OSError, sqlite3.Error, OutboxFull):
            outbox.metadata("protocol", {"provider_version": version, "schema_fingerprint": fingerprint, "protocol_health": failure or "compatible", "capabilities": "client_initialized_stdio"})
        capture = ManagedCapture(outbox, project=project, namespace=namespace, version=version, fingerprint=fingerprint, validators=validators, enforce_handshake=True)
        if unsupported:
            capture.capturing = False
            capture.failure = failure
        try:
            owner = outbox.owner()
            previous = owner["health"]
            if owner["capture_disabled"]:
                capture.capturing = False
                capture.failure = "disabled"
        except (OSError, sqlite3.Error):
            previous = "outbox_full"
        if capture.owned and previous != "new":
            # Restart/read/resume cannot recover omitted live notifications or
            # pending approvals. The gap survives even if rollout later recovers.
            capture.health_all("capture_gap", gap=True, reason="supervisor_restart_requires_rollout_recovery")
        try:
            proc = subprocess.Popen([binary, "app-server", "--listen", "stdio://"], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception:
            if pinned_lease:
                pinned_lease.__exit__(None, None, None)
            raise
        assert proc.stdin is not None and proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(input_stream, selectors.EVENT_READ, "client")
        selector.register(proc.stdout, selectors.EVENT_READ, "server")
        buffers = {"client": b"", "server": b""}
        passthrough = unsupported
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
                    if len(buffers[role]) > outbox.max_bytes and (b"\n" not in buffers[role] or buffers[role].find(b"\n") > outbox.max_bytes):
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
                                if capture.client_modified:
                                    line = json.dumps(wire, separators=(",", ":")).encode()
                                proc.stdin.write(line + b"\n")
                                proc.stdin.flush()
                            else:
                                # Local FULL commit precedes transport forwarding.
                                capture.server_message(wire)
                                internal = str(wire.get("id", "")).startswith(f"summitflow-managed-{capture.connection_id}-") and "method" not in wire
                                if not internal:
                                    output_stream.write(line + b"\n")
                                    output_stream.flush()
                                while capture.subscription_queue:
                                    subscription = capture.subscription_queue.pop(0)
                                    proc.stdin.write(json.dumps(subscription).encode() + b"\n")
                                    proc.stdin.flush()
                        except (ValueError, TypeError, KeyError, AttributeError, OSError, sqlite3.Error, OutboxFull) as error:
                            capture.failure = "outbox_full" if isinstance(error, (OSError, sqlite3.Error, OutboxFull)) else "unsupported"
                            capture.health_all(capture.failure, gap=True)
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
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            with suppress(OSError, sqlite3.Error, OutboxFull):
                outbox.metadata("running_runtime", {})
            if pinned_lease:
                pinned_lease.__exit__(None, None, None)
    return 0


def codex_binary() -> str:
    binary = shutil.which("codex")
    if not binary:
        raise ValueError("codex_binary_unavailable")
    return binary
