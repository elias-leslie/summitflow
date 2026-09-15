"""Fixed stdlib-only Neri deployment program sent through the guest agent.

This is operator code, never code or commands supplied by project identity.
Only the two source files, their hashes, and an attempt UUID are input data.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ADAPTER = "neri-runner-v1"
ROOT = Path("/opt/neri-runner")
PROFILES = (
    ("juice-shop-local-v1", Path("/etc/neri-runner/config.json"), 8517),
    ("wordpress-simple-page-ordering-local-v1", Path("/etc/neri-runner/wordpress-config.json"), 8518),
)
SERVICES = ("neri-proxy.service", "neri-wordpress-proxy.service")
FILES = ("proxy_runner.py", "proxy_core.py")
PRIVILEGED_UID = 0


class DeploymentError(RuntimeError):
    """A deployment stopped at a recorded phase."""


def identity(contents: dict[str, bytes]) -> dict[str, Any]:
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"release_id": "sha256:" + digest, "files": hashes}


def read_identity(directory: Path) -> dict[str, Any]:
    return identity({name: (directory / name).read_bytes() for name in FILES})


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeploymentError("Runner health redirected")


def profile_health(config: Path, port: int) -> dict[str, Any]:
    # The key never leaves its existing guest configuration or enters argv/logs.
    key = json.loads(config.read_text())["api_key"]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health", headers={"Authorization": "Bearer " + key},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=3) as response:
        value = json.load(response)
    # Omit target/capture/session content from deployment evidence.
    health = {name: value.get(name) for name in (
        "status", "stopped", "busy", "failure", "release", "deployment_protocol", "deployment_blocked",
    )}
    if health["failure"] is not None:
        health["failure"] = "Runner reported a failure"
    return health


def inspect() -> dict[str, Any]:
    result: dict[str, Any] = {"profiles": {}, "installed": None, "marker": None}
    try:
        result["installed"] = read_identity(ROOT)
    except (OSError, ValueError):
        result["installed_error"] = "Installed bundle unreadable"
    marker = ROOT / ".deploying"
    if marker.exists():
        try:
            owner = marker.read_text().strip()
            result["marker"] = owner if re.fullmatch(r"[0-9a-f]{32}", owner) else "unrecognized"
        except OSError:
            result["marker"] = "unreadable"
    for name, config, port in PROFILES:
        try:
            result["profiles"][name] = profile_health(config, port)
        except Exception:
            result["profiles"][name] = {"error": "Runner health unavailable"}
    return result


def require_idle(observation: dict[str, Any], *, blocked: bool) -> None:
    if set(observation["profiles"]) != {profile[0] for profile in PROFILES}:
        raise DeploymentError("Both fixed runner profiles must report health")
    for value in observation["profiles"].values():
        if (value.get("status") != "ok" or value.get("failure") is not None
                or value.get("deployment_protocol") != ADAPTER
                or value.get("deployment_blocked") is not blocked):
            raise DeploymentError("Runner health or deployment interlock unavailable; controlled bootstrap/recovery required")
        if value.get("stopped") is not True or value.get("busy") is not False:
            raise DeploymentError("Runner profile is busy; deployment refused")


def require_release(observation: dict[str, Any], expected: dict[str, Any], *, blocked: bool) -> None:
    require_idle(observation, blocked=blocked)
    if observation["installed"] != expected:
        raise DeploymentError("Installed bundle hash mismatch")
    if any(value.get("release") != expected for value in observation["profiles"].values()):
        raise DeploymentError("Running release identity mismatch")


def save_bundle(contents: dict[str, bytes], expected: dict[str, Any]) -> Path:
    releases = ROOT / "releases"
    releases.mkdir(exist_ok=True)
    releases.chmod(0o755)
    directory = releases / expected["release_id"].removeprefix("sha256:")
    if not directory.exists():
        directory.mkdir()
        directory.chmod(0o755)
        for name, value in contents.items():
            path = directory / name
            with path.open("xb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o644)
        sync_directory(directory)
        sync_directory(directory.parent)
    if read_identity(directory) != expected:
        raise DeploymentError("Staged bundle hash mismatch; preserve and inspect the release directory")
    return directory


def replace_link(path: Path, target: str) -> None:
    temporary = path.with_name(path.name + ".next")
    if temporary.exists() or temporary.is_symlink():
        raise DeploymentError("Unsettled activation link exists; inspect deployment state")
    temporary.symlink_to(target)
    os.replace(temporary, path)
    sync_directory(path.parent)


def systemctl(action: str) -> None:
    result = subprocess.run(
        ["/usr/bin/systemctl", action, *SERVICES], capture_output=True, timeout=90, check=False,
    )
    if result.returncode != 0:
        raise DeploymentError(f"Runner service {action} failed")


def activate(directory: Path, previous: Path, *, services_stopped: bool = False) -> None:
    current = ROOT / "current"
    if not current.exists() and not current.is_symlink():
        # One-time conversion of guarded legacy runners. Both are stopped while
        # the flat entry points become stable links; source activation itself is
        # still one atomic current-link replacement.
        if not services_stopped:
            systemctl("stop")
        replace_link(current, str(previous.relative_to(ROOT)))
        for name in FILES:
            replace_link(ROOT / name, "current/" + name)
    if (not current.is_symlink()
            or any(not (ROOT / name).is_symlink() or os.readlink(ROOT / name) != "current/" + name for name in FILES)
            or current.resolve() != previous):
        raise DeploymentError("Installed layout changed; inspect before recovery")
    replace_link(ROOT / "previous", str(previous.relative_to(ROOT)))
    replace_link(current, str(directory.relative_to(ROOT)))


def require_legacy_layout() -> None:
    """Accept only the original two-file installation for one-time adoption."""
    if (ROOT / "current").exists() or (ROOT / "current").is_symlink():
        raise DeploymentError("Guarded runner layout already exists; use normal deployment or recovery")
    if (ROOT / "previous").exists() or (ROOT / "previous").is_symlink():
        raise DeploymentError("Unexpected legacy previous link; inspect before recovery")
    if any(not (ROOT / name).is_file() or (ROOT / name).is_symlink() for name in FILES):
        raise DeploymentError("Legacy runner source layout is not the expected fixed-file installation")


def bootstrap(attempt: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Adopt the fixed legacy layout after explicitly stopping both runners."""
    if not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise DeploymentError("Invalid deployment attempt")
    if os.geteuid() != PRIVILEGED_UID or ROOT.stat().st_uid != PRIVILEGED_UID:
        raise DeploymentError("Runner deployment requires its root-owned installation directory")
    receipts = ROOT / "deployments"
    receipts.mkdir(exist_ok=True)
    path = receipts / (attempt + ".json")
    if path.exists():
        raise DeploymentError("Attempt already exists; inspect its receipt instead of retrying")
    record: dict[str, Any] = {
        "adapter": ADAPTER, "operation": "bootstrap", "attempt": attempt,
        "state": "running", "events": [],
    }
    marker_owned = False
    uncertain = False

    def phase(name: str, **values: Any) -> None:
        record.update(phase=name, **values)
        record["events"].append({"phase": name, "at": time.time()})
        atomic_json(path, record)

    with (ROOT / ".deployment-lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            phase("inspect")
            before = inspect()
            record["before"] = before
            if before["marker"] is not None:
                raise DeploymentError("Existing deployment interlock retained; inspect and recover its owner")
            require_legacy_layout()
            if set(payload) != {"files", "identity"} or set(payload["files"]) != set(FILES):
                raise DeploymentError("Bundle must contain exactly the two fixed source files")
            contents = {name: base64.b64decode(payload["files"][name], validate=True) for name in FILES}
            expected = identity(contents)
            record["expected"] = expected
            if expected != payload["identity"]:
                raise DeploymentError("Transferred bundle hash mismatch")
            previous_contents = {name: (ROOT / name).read_bytes() for name in FILES}
            if identity(previous_contents) != before["installed"]:
                raise DeploymentError("Installed source changed since inspection")

            phase("interlock")
            marker = ROOT / ".deploying"
            with marker.open("x") as stream:
                stream.write(attempt)
                stream.flush()
                os.fsync(stream.fileno())
            marker.chmod(0o644)
            marker_owned = True
            uncertain = True
            sync_directory(ROOT)
            phase("stop")
            systemctl("stop")
            phase("stage")
            directory = save_bundle(contents, expected)
            previous = save_bundle(previous_contents, before["installed"])
            phase("activate", previous=before["installed"])
            activate(directory, previous, services_stopped=True)
            phase("restart")
            systemctl("restart")
            phase("verify")
            deadline = time.monotonic() + 30
            while True:
                after = inspect()
                try:
                    require_release(after, expected, blocked=True)
                    break
                except DeploymentError:
                    if time.monotonic() >= deadline:
                        record["after"] = after
                        raise
                    time.sleep(1)
            phase("verified", state="succeeded", after=after)
            uncertain = False
        except Exception as exc:
            reason = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
            phase(
                "failed", failed_phase=record.get("phase"),
                state="uncertain" if uncertain else "failed", error=reason, after=inspect(),
            )
        finally:
            if marker_owned and not uncertain:
                marker = ROOT / ".deploying"
                if marker.read_text().strip() == attempt:
                    marker.unlink()
                    sync_directory(ROOT)
            record["interlock_retained"] = (ROOT / ".deploying").exists()
            atomic_json(path, record)
    return record


def deploy(attempt: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise DeploymentError("Invalid deployment attempt")
    if os.geteuid() != PRIVILEGED_UID or ROOT.stat().st_uid != PRIVILEGED_UID:
        raise DeploymentError("Runner deployment requires its root-owned installation directory")
    receipts = ROOT / "deployments"
    receipts.mkdir(exist_ok=True)
    path = receipts / (attempt + ".json")
    if path.exists():
        raise DeploymentError("Attempt already exists; inspect its receipt instead of retrying")
    record: dict[str, Any] = {"adapter": ADAPTER, "attempt": attempt, "state": "running", "events": []}
    marker_owned = False
    uncertain = False

    def phase(name: str, **values: Any) -> None:
        record.update(phase=name, **values)
        record["events"].append({"phase": name, "at": time.time()})
        atomic_json(path, record)

    # Serialize deployments without truncating a previous attempt's marker.
    with (ROOT / ".deployment-lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            phase("inspect")
            before = inspect()
            record["before"] = before
            if before["marker"] is not None:
                raise DeploymentError("Existing deployment interlock retained; inspect and recover its owner")
            require_release(before, before["installed"], blocked=False)
            if set(payload) != {"files", "identity"} or set(payload["files"]) != set(FILES):
                raise DeploymentError("Bundle must contain exactly the two fixed source files")
            contents = {name: base64.b64decode(payload["files"][name], validate=True) for name in FILES}
            expected = identity(contents)
            record["expected"] = expected
            if expected != payload["identity"]:
                raise DeploymentError("Transferred bundle hash mismatch")
            if before["installed"] == expected:
                require_release(before, expected, blocked=False)
                phase("verified", state="noop", after=before)
                return record
            phase("interlock")
            marker = ROOT / ".deploying"
            with marker.open("x") as stream:
                stream.write(attempt)
                stream.flush()
                os.fsync(stream.fileno())
            marker.chmod(0o644)
            marker_owned = True
            sync_directory(ROOT)
            # The marker blocks new permits before this second health check.
            require_idle(inspect(), blocked=True)
            phase("stage")
            directory = save_bundle(contents, expected)
            previous_contents = {name: (ROOT / name).read_bytes() for name in FILES}
            if identity(previous_contents) != before["installed"]:
                raise DeploymentError("Installed source changed since inspection")
            previous = save_bundle(previous_contents, before["installed"])
            phase("activate", previous=before["installed"])
            uncertain = True
            activate(directory, previous)
            phase("restart")
            systemctl("restart")
            phase("verify")
            # Service startup is asynchronous; only read-only health is polled.
            deadline = time.monotonic() + 30
            while True:
                after = inspect()
                try:
                    require_release(after, expected, blocked=True)
                    break
                except DeploymentError:
                    if time.monotonic() >= deadline:
                        record["after"] = after
                        raise
                    time.sleep(1)
            phase("verified", state="succeeded", after=after)
            uncertain = False
        except Exception as exc:
            # Never emit raw guest/subprocess/HTTP exceptions containing secrets.
            reason = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
            phase("failed", failed_phase=record.get("phase"), state="uncertain" if uncertain else "failed", error=reason, after=inspect())
        finally:
            if marker_owned and not uncertain:
                marker = ROOT / ".deploying"
                if marker.read_text().strip() == attempt:
                    marker.unlink()
                    sync_directory(ROOT)
            record["interlock_retained"] = (ROOT / ".deploying").exists()
            atomic_json(path, record)
    return record


def main() -> int:
    if sys.argv[1:] == ["inspect"]:
        print(json.dumps(inspect()))
        return 0
    if len(sys.argv) != 4 or sys.argv[1] not in {"bootstrap", "deploy"}:
        raise DeploymentError("Unsupported fixed adapter action")
    operation = bootstrap if sys.argv[1] == "bootstrap" else deploy
    result = operation(sys.argv[2], json.loads(sys.argv[3]))
    print(json.dumps(result))
    return 0 if result["state"] in {"noop", "succeeded"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
