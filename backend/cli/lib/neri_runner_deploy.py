"""Typed Neri runner adapter for the canonical service rebuild lifecycle."""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import neri_runner_guest as guest
from .proxmox import ProxmoxClient, ProxmoxError

VM_ID = "120"
SOURCES = ("scripts/proxy_runner.py", "backend/app/proxy_core.py")


class RunnerAdapter(StrEnum):
    neri_runner_v1 = "neri-runner-v1"


@dataclass(frozen=True)
class FrozenBundle:
    contents: tuple[bytes, bytes]

    @property
    def payload(self) -> dict[str, Any]:
        files = dict(zip(guest.FILES, self.contents, strict=True))
        return {"identity": guest.identity(files), "files": {
            name: base64.b64encode(value).decode("ascii") for name, value in files.items()
        }}

    @classmethod
    def from_checkout(cls, root: Path) -> FrozenBundle:
        return cls(((root / SOURCES[0]).read_bytes(), (root / SOURCES[1]).read_bytes()))


def _operate_runner(root: Path, adapter: RunnerAdapter, action: str) -> int:
    if adapter != RunnerAdapter.neri_runner_v1:
        raise ValueError("Unsupported runner adapter")
    if action not in {"bootstrap", "deploy"}:
        raise ValueError("Unsupported fixed runner operation")
    attempt = uuid.uuid4().hex
    directory = root / ".dev-tools" / "runner-deployments"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (attempt + ".json")
    record: dict[str, Any] = {
        "adapter": adapter.value, "operation": action, "attempt": attempt,
        "state": "running", "events": [], "guest_processes": {},
    }

    def phase(name: str, **values: Any) -> None:
        record.update(phase=name, **values)
        record["events"].append({"phase": name, "at": time.time()})
        guest.atomic_json(path, record)
        print(f"[service] runner {name}; attempt={attempt}; result={path}")

    submitted = False
    try:
        phase("freeze")
        bundle = FrozenBundle.from_checkout(root)
        record["expected"] = bundle.payload["identity"]
        # Fixed implementation source, never a path or executable from identity.
        program = Path(guest.__file__).read_text()
        client = ProxmoxClient()

        def execute(action: str, *arguments: str) -> tuple[int, dict[str, Any]]:
            nonlocal submitted
            record["guest_processes"][action] = {"state": "submitting", "pid": None}
            # Clear the compatibility field before submission so a lost
            # deployment response cannot leave the earlier inspection PID as
            # the apparent process to reconcile.
            phase(action + "-submitting", guest_action=action, guest_pid=None)
            if action in {"bootstrap", "deploy"}:
                submitted = True  # The API may accept a command before losing its response.
            response = client.agent_exec(VM_ID, ["/usr/bin/python3", "-c", program, action, *arguments])
            pid = response.get("pid")
            if not isinstance(pid, int):
                raise ProxmoxError("Guest execution returned no process identity")
            record["guest_processes"][action] = {"state": "waiting", "pid": pid}
            phase(action + "-waiting", guest_action=action, guest_pid=pid)
            # Match the existing guest-exec wait window; first adoption can
            # include both a bounded stop and restart before startup health.
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                status = client.agent_exec_status(VM_ID, pid)
                if status.get("exited"):
                    record["guest_processes"][action] = {
                        "state": "exited", "pid": pid, "exitcode": status.get("exitcode"),
                    }
                    phase(action + "-exited", guest_action=action, guest_pid=pid)
                    if status.get("out-truncated") or status.get("err-truncated"):
                        raise ProxmoxError("Guest result was truncated; inspect its durable receipt")
                    result = json.loads(status.get("out-data", ""))
                    if not isinstance(result, dict) or not isinstance(status.get("exitcode"), int):
                        raise ProxmoxError("Guest result is incomplete")
                    return status["exitcode"], result
                time.sleep(1)
            raise ProxmoxError("Guest execution still unsettled; inspect its process identity before retry")

        # Always inspect current identity, including after an uncertain attempt.
        code, observation = execute("inspect")
        phase("inspected", observation=observation)
        if code != 0:
            raise ProxmoxError("Runner inspection failed")
        if observation.get("marker") is not None:
            raise ProxmoxError("Existing runner interlock retained; recovery required")
        if action == "deploy":
            guest.require_release(observation, observation["installed"], blocked=False)
        code, result = execute(action, attempt, json.dumps(bundle.payload, separators=(",", ":")))
        phase("result", guest=result, state=result.get("state", "uncertain"))
        if result.get("attempt") != attempt:
            raise ProxmoxError("Guest result identity mismatch")
        if code == 0 and result.get("state") in {"noop", "succeeded"}:
            if result.get("expected") != record["expected"] or result.get("interlock_retained") is not False:
                raise ProxmoxError("Guest verified result is incomplete")
            guest.require_release(result["after"], record["expected"], blocked=result["state"] == "succeeded")
            return 0
        return 1
    except Exception as exc:
        # Proxmox errors can contain API response text: retain identity, not raw
        # transport output, credentials, or the source bundle in diagnostic logs.
        error = str(exc) if isinstance(exc, guest.DeploymentError) else type(exc).__name__
        phase("failed", failed_phase=record.get("phase"), state="uncertain" if submitted else "failed", error=error)
        print("[service] runner deployment stopped; inspect recorded installed/running identities before retry")
        return 1


def deploy_runner(root: Path, adapter: RunnerAdapter) -> int:
    return _operate_runner(root, adapter, "deploy")


def bootstrap_runner(root: Path, adapter: RunnerAdapter) -> int:
    return _operate_runner(root, adapter, "bootstrap")
