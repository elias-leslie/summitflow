#!/usr/bin/env python3
"""Installed App Server canary. Run only inside an isolated network namespace."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Test the exact packaged SDK scheduled for deployment, without installing it.
sys.path.insert(0, str(ROOT / "docker/workspace-packages/agent_hub_client-0.6.0-py3-none-any.whl"))
sys.path.insert(0, str(ROOT / "scripts/lib"))

from codex_managed_capture import conformance  # noqa: E402
from codex_managed_outbox import ManagedOutbox  # noqa: E402
from codex_managed_update import (  # noqa: E402
    pin_runtime,
    runtime_digest,
    selected_binary,
    update_action,
)


class Provider(BaseHTTPRequestHandler):
    """Scripted Responses fixture, not a model or a general execution framework."""

    actions: queue.Queue = queue.Queue()
    requests_seen = 0

    def log_message(self, *_):
        pass  # never print provider bodies, inputs, or headers

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests_seen += 1
        try:
            action = self.actions.get_nowait()
        except queue.Empty:
            action = "message"
        rid = f"response-{self.requests_seen}"
        if action in {"command", "approval", "sleep", "child"}:
            names = []
            namespaces = {}
            def collect(tools, parent=None):
                for tool in tools:
                    names.append(tool.get("name"))
                    namespaces[tool.get("name")] = parent
                    collect(tool.get("tools", []), tool.get("name"))
            collect(body.get("tools", []))
            tool = "exec_command" if "exec_command" in names else "shell_command"
            command = "sleep 30" if action == "sleep" else "printf managed-canary"
            arguments = {"cmd" if tool == "exec_command" else "command": command}
            if action == "approval":
                arguments.update(sandbox_permissions="require_escalated", justification="Isolated local canary request")
            if action == "child":
                assert "spawn_agent" in names, f"Native child capability absent; tool names={names}"
                tool = "spawn_agent"
                arguments = {"message": "Return the local scripted fixture response.", "agent_type": "default"}
            item = {"type": "function_call", "call_id": f"call-{rid}", "name": tool, "arguments": json.dumps(arguments)}
            if namespaces.get(tool):
                item["namespace"] = namespaces[tool]
        else:
            item = {"type": "message", "role": "assistant", "id": rid, "content": [{"type": "output_text", "text": "Local canary completed."}]}
        events = [{"type": "response.created", "response": {"id": rid}}, {"type": "response.output_item.done", "item": item}, {"type": "response.completed", "response": {"id": rid, "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}}]
        data = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Connection:
    def __init__(self, *, env, root):
        project = json.loads((root / "project.identity.json").read_text())["project"]["id"]
        self.process = subprocess.Popen([sys.executable, str(ROOT / "scripts/codex-managed-session.py"), "--project", project, "--project-root", str(root)], cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.messages: queue.Queue = queue.Queue()
        self.seen = []
        self.identifier = 0

        def read():
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
            self.messages.put(None)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def send(self, wire):
        self.process.stdin.write(json.dumps(wire).encode() + b"\n")
        self.process.stdin.flush()

    def wait(self, predicate, *, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                wire = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                summary = Counter((w.get("method"), w.get("params", {}).get("item", {}).get("type"), w.get("params", {}).get("item", {}).get("status")) for w in self.seen)
                raise RuntimeError(f"canary_notification_timeout:content_free_counts={dict(summary)}") from None
            if wire is None:
                raise RuntimeError("canary_transport_closed")
            self.seen.append(wire)
            if predicate(wire):
                return wire
        raise RuntimeError("canary_notification_timeout")

    def rpc(self, method, params):
        self.identifier += 1
        identifier = self.identifier
        self.send({"id": identifier, "method": method, "params": params})
        response = self.wait(lambda wire: wire.get("id") == identifier and "method" not in wire)
        if "error" in response:
            raise RuntimeError(f"canary_rpc_failed:{method}")
        return response["result"]

    def initialize(self):
        self.rpc("initialize", {"clientInfo": {"name": "summitflow_canary", "version": "1"}})
        self.send({"method": "initialized"})

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=30)
        self.reader.join(timeout=5)
        self.process.stdout.close()
        assert self.process.returncode == 0


def run(output: Path, evidence_directory: Path | None = None, *, project: str = "canary"):
    links = json.loads(subprocess.run(["ip", "-j", "link", "show"], capture_output=True, text=True, check=True).stdout)
    assert [link["ifname"] for link in links] == ["lo"], "Canary requires unshare -Urn; external networking must be absent"
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    binary = shutil.which("codex")
    assert binary
    real_binary = os.environ.get("CODEX_REAL", str(Path.home() / ".local/bin/codex-real"))
    with tempfile.TemporaryDirectory(prefix="codex-managed-canary-") as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        native = home / "codex"
        native.mkdir()
        (root / "project.identity.json").write_text(json.dumps({"project": {"id": project}}))
        provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        serving = threading.Thread(target=provider.serve_forever, daemon=True)
        serving.start()
        (native / "config.toml").write_text(f'model = "canary-model"\nmodel_provider = "canary"\napproval_policy = "on-request"\nsandbox_mode = "read-only"\nmodel_auto_compact_token_limit = 1000000\n[model_providers.canary]\nname = "local-canary"\nbase_url = "http://127.0.0.1:{provider.server_port}/v1"\nwire_api = "responses"\nrequires_openai_auth = false\nrequest_max_retries = 0\nstream_max_retries = 0\n[features]\nunified_exec = true\nmulti_agent = true\n[analytics]\nenabled = false\n[feedback]\nenabled = false\n')
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "CODEX_REAL": real_binary, "CODEX_HOME": str(native), "PYTHONPATH": str(ROOT / "docker/workspace-packages/agent_hub_client-0.6.0-py3-none-any.whl"), "SUMMITFLOW_CODEX_MANAGED_CAPTURE": "1", "SUMMITFLOW_CODEX_OUTBOX": str(root / "spool/outbox.sqlite"), "SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES": "10485760", "SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS": "0", "SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION": os.environ.get("SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION", "0"), "RUST_LOG": "off"}
        version, fingerprint, _ = conformance(binary, env=env)
        connection = Connection(env=env, root=root)
        connection.initialize()
        competing = subprocess.run([sys.executable, str(ROOT / "scripts/codex-managed-session.py"), "--project", project, "--project-root", str(root)], cwd=root, env=env, input=b"", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
        assert competing.returncode == 2, "Competing managed process must be fenced before native startup"
        connection.identifier += 1
        identifier = connection.identifier
        connection.send({"id": identifier, "method": "thread/resume", "params": {"threadId": "external-canary-thread"}})
        rejected = connection.wait(lambda wire: wire.get("id") == identifier and "method" not in wire)
        assert rejected["error"]["message"] == "thread_is_not_owned_by_this_managed_session"
        started = connection.rpc("thread/start", {"cwd": str(root), "model": "canary-model", "modelProvider": "canary", "approvalPolicy": "on-request", "sandbox": "read-only"})
        thread = started["thread"]["id"]
        Provider.actions.put("command")
        Provider.actions.put("message")
        connection.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Run the local scripted fixture."}]})
        connection.wait(lambda wire: wire.get("method") == "turn/completed")
        stored = connection.rpc("thread/read", {"threadId": thread, "includeTurns": True})
        commands = [item for turn in stored["thread"]["turns"] for item in turn["items"] if item["type"] == "commandExecution"]
        assert len(commands) == 1 and commands[0]["status"] == "completed" and commands[0]["exitCode"] == 0
        auto_messages = [item for turn in stored["thread"]["turns"] for item in turn["items"] if item["type"] == "userMessage"]
        assert len(auto_messages) == 1 and isinstance(auto_messages[0].get("clientId"), str) and auto_messages[0]["clientId"]
        from uuid import UUID
        UUID(auto_messages[0]["clientId"])
        # Native fork snapshots retain copied history as snapshots, never child events.
        fork = connection.rpc("thread/fork", {"threadId": thread, "cwd": str(root)})
        assert fork["thread"]["id"] != thread
        Provider.actions.put("approval")
        Provider.actions.put("message")
        connection.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Exercise the local approval fixture."}]})
        approval = connection.wait(lambda wire: wire.get("method") == "item/commandExecution/requestApproval")
        # This explicit canary controller is the approval authority; the capture
        # implementation merely forwards its decision and retains evidence.
        connection.send({"id": approval["id"], "result": {"decision": "decline"}})
        connection.wait(lambda wire: wire.get("method") == "serverRequest/resolved")
        connection.wait(lambda wire: wire.get("method") == "turn/completed")
        Provider.actions.put("sleep")
        launched = connection.rpc("turn/start", {"threadId": thread, "clientUserMessageId": "managed-canary-explicit-client-user-message", "input": [{"type": "text", "text": "Exercise interruption and exact native message identity."}]})
        running = connection.wait(lambda wire: wire.get("method") == "item/started" and wire["params"]["item"]["type"] == "commandExecution")
        active = connection.rpc("thread/read", {"threadId": thread, "includeTurns": True})
        resumed_active = connection.rpc("thread/resume", {"threadId": thread})
        connection.rpc("turn/interrupt", {"threadId": thread, "turnId": running["params"]["turnId"]})
        interrupted = connection.wait(lambda wire: wire.get("method") == "turn/completed")
        assert interrupted["params"]["turn"]["status"] == "interrupted"
        final_identity = connection.rpc("thread/read", {"threadId": thread, "includeTurns": True})
        identity_snapshots = []
        for snapshot in (active, resumed_active, final_identity):
            items = [item for turn in snapshot["thread"]["turns"] if turn["id"] == launched["turn"]["id"] for item in turn["items"] if item["type"] == "userMessage"]
            assert len(items) == 1 and items[0].get("clientId") == "managed-canary-explicit-client-user-message"
            identity_snapshots.append(items[0]["id"])
        connection.close()
        restarted = Connection(env=env, root=root)
        restarted.initialize()
        resumed = restarted.rpc("thread/resume", {"threadId": thread})
        assert resumed["thread"]["id"] == thread
        Provider.actions.put("message")
        restarted.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Resume with the local fixture."}]})
        restarted.wait(lambda wire: wire.get("method") == "turn/completed")
        Provider.actions.put("message")
        restarted.rpc("thread/compact/start", {"threadId": thread})
        compacted = restarted.wait(lambda wire: wire.get("method") == "item/completed" and wire["params"]["item"]["type"] == "contextCompaction")
        assert compacted["params"]["threadId"] == thread
        Provider.actions.put("child")
        Provider.actions.put("message")
        Provider.actions.put("message")
        restarted.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Exercise a local native child."}]})
        spawned = restarted.wait(lambda wire: wire.get("method") == "item/completed" and wire["params"]["item"]["type"] == "collabAgentToolCall" and wire["params"]["item"]["tool"] == "spawnAgent")
        assert spawned["params"]["item"]["status"] == "completed"
        child_id = spawned["params"]["item"]["receiverThreadIds"][0]
        assert child_id not in {thread, fork["thread"]["id"]}
        restarted.wait(lambda wire: wire.get("method") == "turn/completed" and wire["params"]["threadId"] == thread)
        live_outbox = ManagedOutbox(Path(env["SUMMITFLOW_CODEX_OUTBOX"]), max_bytes=10485760, retention_seconds=0)
        deadline = time.monotonic() + 10
        subscribed = False
        while not subscribed and time.monotonic() < deadline:
            with live_outbox.connect() as db:
                rows = [json.loads(row[0]) for row in db.execute("SELECT observation FROM events WHERE thread=?", (child_id,))]
            subscribed = any(row["kind"] == "app_server_snapshot" and row["source_reference"].get("managed_subscription") for row in rows)
            if not subscribed:
                time.sleep(0.02)
        assert subscribed, "Owner-proven native child must receive an explicit live subscription"
        child = restarted.rpc("thread/resume", {"threadId": child_id})
        assert child["thread"]["source"]["subAgent"]["thread_spawn"]["parent_thread_id"] == thread
        subprocess.run([sys.executable, str(ROOT / "scripts/codex-managed-session.py"), "--project", project, "--project-root", str(root), "--disable-capture"], cwd=root, env=env, stdout=subprocess.DEVNULL, check=True)
        # The owner still executes after rollback. Only the disabled health marker
        # is captured; subsequent native events remain exclusively in rollout.
        Provider.actions.put("message")
        restarted.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Exercise rollout-only rollback."}]})
        restarted.wait(lambda wire: wire.get("method") == "turn/completed")
        subprocess.run([sys.executable, str(ROOT / "scripts/codex-managed-session.py"), "--project", project, "--project-root", str(root), "--enable-capture"], cwd=root, env=env, stdout=subprocess.DEVNULL, check=True)
        Provider.actions.put("message")
        restarted.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Exercise safe capture re-enable."}]})
        restarted.wait(lambda wire: wire.get("method") == "turn/completed")
        restarted.close()
        # Exhaust capture storage using the actual owned App Server. Its client
        # continues both turns while the original delivery evidence stays pending.
        quota_env = {**env, "SUMMITFLOW_CODEX_OUTBOX": str(root / "quota/outbox.sqlite"), "SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES": "8192"}
        quota_connection = Connection(env=quota_env, root=root)
        quota_connection.initialize()
        quota_thread = quota_connection.rpc("thread/start", {"cwd": str(root), "model": "canary-model", "modelProvider": "canary", "approvalPolicy": "on-request", "sandbox": "read-only"})["thread"]["id"]
        for _ in range(2):
            Provider.actions.put("message")
            quota_connection.rpc("turn/start", {"threadId": quota_thread, "input": [{"type": "text", "text": "Exercise bounded capture fallback."}]})
            quota_connection.wait(lambda wire: wire.get("method") == "turn/completed")
        quota_connection.close()
        quota_outbox = ManagedOutbox(Path(quota_env["SUMMITFLOW_CODEX_OUTBOX"]), max_bytes=8192, retention_seconds=0)
        assert quota_outbox.status()["health"] == "outbox_full" and quota_outbox.status()["capture_gaps"] > 0
        assert quota_outbox.status()["used_bytes"] <= 8192 and quota_outbox.status()["pending"] > 0
        outbox = ManagedOutbox(Path(env["SUMMITFLOW_CODEX_OUTBOX"]), max_bytes=10485760, retention_seconds=0)
        # A real installed vendor tree, including resources, exercises future
        # launch selection and rollback without touching the global npm install.
        baseline = pin_runtime(outbox, real_binary)
        resource_fixture = root / "changed-native-resources"
        shutil.copytree(Path(baseline).parent.parent, resource_fixture)
        (resource_fixture / "codex-resources/managed-canary-resource-proof").write_text("Isolated benign resource identity fixture.\n")
        candidate = pin_runtime(outbox, str(resource_fixture / "bin/codex"))
        assert candidate != baseline and Path(candidate).read_bytes() == Path(baseline).read_bytes()
        import hashlib

        def runtime_record(binary):
            return {"binary": binary, "version": version.removeprefix("codex-cli "), "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(), "runtime_sha256": runtime_digest(Path(binary))}

        # Both are the already qualified bundled installed profile. This is a
        # local selection fixture; AH profile approval is verified separately.
        outbox.metadata("update", {"active": runtime_record(baseline), "candidate": runtime_record(candidate), "candidate_qualified": True})
        for action, expected in (("promote-update", candidate), ("rollback-update", baseline)):
            update_action(outbox, action)
            update_action(outbox, action)  # uncertain operator responses are safe
            assert selected_binary(outbox) == expected
            runtime_connection = Connection(env=env, root=root)
            runtime_connection.initialize()
            runtime_connection.rpc("thread/resume", {"threadId": thread})
            Provider.actions.put("message")
            runtime_connection.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Exercise private runtime selection."}]})
            runtime_connection.wait(lambda wire: wire.get("method") == "turn/completed")
            runtime_connection.close()
        with outbox.connect() as db:
            observations = [json.loads(row[0]) for row in db.execute("SELECT observation FROM events ORDER BY thread,position")]
        methods = Counter(observation["payload"].get("method") for observation in observations if observation["kind"] == "app_server_event")
        gap_reasons = {(observation["payload"].get("capture_gaps"), observation["payload"].get("reason")) for observation in observations if observation["kind"] == "capture_health" and observation["payload"].get("state") == "capture_gap"}
        with outbox.connect() as db:
            quarantined_methods = Counter(json.loads(row[0]).get("method") for row in db.execute("SELECT payload FROM quarantine"))
        assert methods["item/commandExecution/requestApproval"] == 1 and methods["serverRequest/resolved"] == 1
        assert methods["thread/tokenUsage/updated"] > 0
        assert outbox.status()["capture_gaps"] > 0
        assert outbox.status()["health"] != "unsupported"
        assert not outbox.status()["capture_disabled"]
        result = {"version": version, "schema_fingerprint": fingerprint, "transport": "stdio", "external_network": "absent", "provider": "scripted_loopback_fixture", "provider_requests": Provider.requests_seen, "cases": {"completed_command": True, "live_approval_request_resolution": True, "turn_interruption_resume": True, "compaction": True, "fork_snapshot": True, "native_child": True, "owned_child_subscription": True, "supervisor_restart_resume": True, "usage_snapshots": True, "runtime_rollback_to_rollout": True, "safe_runtime_reenable": True, "process_owner_fencing": True, "external_thread_rejection": True, "quota_preserves_native_execution": True}, "outbox": outbox.status(), "notification_counts": dict(methods), "observed_model": None, "promotion_state": "shadow"}
        result["cases"]["exact_client_message_identity"] = True
        result["generated_client_message_correlation"] = True
        result["project_id"] = project
        result["cases"]["private_runtime_pin_promote_rollback"] = True
        result["runtime_update_proof"] = {"provider_version": version, "different_resource_tree_same_executable": True, "active_process_resources_pinned": True, "promote_and_rollback_request_replay_safe": True, "selected_runtime_native_turns": 2, "registry_install": "not_performed", "qualification_authority": "bundled_known_profile_local_selection_fixture; AH durable approval verified by integration suite"}
        result["user_message_snapshot_ids"] = identity_snapshots
        result["capture_limitations"] = {"gap_reasons": [{"gap_number": number, "reason": reason} for number, reason in sorted(gap_reasons)], "quarantined_notification_counts": dict(quarantined_methods), "explanation": "Restart and disable/re-enable deliberately omit live intervals. Native root start notifications and child status/warning frames can arrive before their exact start response or parent spawn proves ownership and stay quarantined; explicit subscription does not reconstruct that missing prefix. Rollout is the recovery source; this receipt does not claim uninterrupted live capture."}
        if evidence_directory:
            evidence_directory.mkdir(parents=True, exist_ok=False, mode=0o700)
            shutil.copy2(outbox.path, evidence_directory / "outbox.sqlite")
            shutil.copytree(native / "sessions", evidence_directory / "sessions")
            for path in evidence_directory.rglob("*"):
                path.chmod(0o700 if path.is_dir() else 0o600)
        # Thread IDs are toy identifiers; payloads, prompts and approvals are never
        # exported. Temporary capture and native files are removed on context exit.
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
        provider.shutdown()
        provider.server_close()
        print(json.dumps({"result": "pass", "receipt": str(output), "cases": result["cases"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-directory", type=Path, help="Private toy-only spool/rollout export for isolated PostgreSQL acceptance; remove after verification")
    parser.add_argument("--project", default="canary", help="Explicit registered fixture project for owner-authorized local delivery verification")
    args = parser.parse_args()
    run(args.output, args.evidence_directory, project=args.project)
