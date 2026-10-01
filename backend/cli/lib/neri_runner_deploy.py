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
FIXTURE_SOURCES = (
    "config/reset-profiles.json",
    "scripts/lab-vm/target_reset.py",
    *("scripts/lab-vm/wordpress-fixture/" + name for name in guest.FIXTURE_CONTROLS),
)


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


@dataclass(frozen=True)
class FrozenFixture:
    contents: tuple[bytes, ...]

    @property
    def payload(self) -> dict[str, Any]:
        files = dict(zip(guest.FIXTURE_FILES, self.contents, strict=True))
        return {"identity": guest.identity(files), "files": {
            name: base64.b64encode(value).decode("ascii") for name, value in files.items()
        }}

    @classmethod
    def from_checkout(cls, root: Path) -> FrozenFixture:
        result = cls(tuple((root / source).read_bytes() for source in FIXTURE_SOURCES))
        guest.fixture_contents(result.payload)
        return result


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
        fixture = FrozenFixture.from_checkout(root) if action == "deploy" else None
        if fixture is not None:
            record["fixture_expected"] = fixture.payload["identity"]
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
            if action in {"bootstrap", "deploy", "sync-fixture"}:
                submitted = True  # The API may accept a command before losing its response.
            response = client.agent_exec(VM_ID, ["/usr/bin/python3", "-c", program, action, *arguments])
            pid = response.get("pid")
            if not isinstance(pid, int):
                raise ProxmoxError("Guest execution returned no process identity")
            record["guest_processes"][action] = {"state": "waiting", "pid": pid}
            phase(action + "-waiting", guest_action=action, guest_pid=pid)
            # Match the existing guest-exec wait window; first adoption can
            # include both a bounded stop and restart before startup health.
            deadline = time.monotonic() + (2100 if action == "sync-fixture" else 300)
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
            assert fixture is not None
            code, fixture_result = execute("sync-fixture", attempt, guest.encode_payload(fixture.payload))
            phase("fixture-result", fixture=fixture_result, state=fixture_result.get("state", "uncertain"))
            if (fixture_result.get("attempt") != attempt
                    or fixture_result.get("expected") != record["fixture_expected"]):
                raise ProxmoxError("Guest fixture result identity mismatch")
            if code != 0 or fixture_result.get("state") not in {"noop", "succeeded"}:
                return 1
            if (fixture_result.get("interlock_retained") is not False
                    or fixture_result.get("after", {}).get("installed") != record["fixture_expected"]
                    or fixture_result.get("after", {}).get("artifact_identity") != fixture_result.get("artifact_identity")
                    or fixture_result.get("verified") is not True):
                raise ProxmoxError("Guest verified fixture result is incomplete")
        code, result = execute(action, attempt, guest.encode_payload(bundle.payload))
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
