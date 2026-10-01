"""Owner-controlled npm staging, isolated qualification and future-launch selection."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REGISTRY = "https://registry.npmjs.org"
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ManagedUpdateError(ValueError):
    """Only fixed content-free codes cross the operator boundary."""
    def __init__(self, code: str, stage: str):
        super().__init__(code)
        self.code = code
        self.stage = stage


UPDATE_ERRORS = {
    "delivery_credentials_unavailable", "managed_update_version_invalid",
    "managed_update_check_required", "managed_update_stage_required",
    "managed_update_qualification_required", "managed_candidate_changed",
    "managed_candidate_resources_changed", "managed_candidate_version_mismatch",
    "managed_candidate_receipt_binding_mismatch", "managed_candidate_authority_binding_mismatch",
    "candidate_conformance_failed", "candidate_protocol_unsupported",
    "agent_hub_qualification_rejected", "agent_hub_qualification_unavailable",
    "registry_check_failed", "candidate_install_failed", "runtime_selection_failed",
    "managed_runtime_changed_during_pin", "managed_runtime_pinned_tree_changed",
    "managed_runtime_resource_escapes_vendor", "managed_runtime_private_directory_required",
    "managed_runtime_native_binary_unavailable", "managed_runtime_platform_unsupported",
}


def private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("managed_runtime_private_directory_required")
    return path


def runtime_root(outbox) -> Path:
    return private_directory(outbox.path.parent / "runtimes")


@contextmanager
def update_lease(outbox):
    fd = os.open(runtime_root(outbox) / ".update-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def native_binary(binary: str) -> Path:
    """Resolve the installed npm launcher's own platform package, never another process."""
    path = Path(binary).resolve()
    # The installed context wrapper delegates admin commands unchanged. Pin
    # its selected native package, rather than copying a launcher which can
    # resolve a different global installation during an active session.
    if path.name == "codex":
        with path.open("rb") as handle:
            prefix = handle.read(8192)
        if prefix.startswith(b"#!/usr/bin/env python3") and b"CODEX_REAL" in prefix:
            real = os.environ.get("CODEX_REAL", str(Path.home() / ".local/bin/codex-real"))
            return native_binary(real)
    if path.suffix != ".js":
        return path
    target = {"x86_64": ("linux-x64", "x86_64-unknown-linux-musl"), "aarch64": ("linux-arm64", "aarch64-unknown-linux-musl")}.get(platform.machine())
    if platform.system() != "Linux" or not target:
        raise ValueError("managed_runtime_platform_unsupported")
    package, triple = target
    root = path.parent.parent
    # npm global installs can nest the optional platform package inside the
    # launcher, while a fresh private prefix normally hoists it beside the
    # launcher in the same @openai scope. Both are official package layouts.
    for vendor in (root / "node_modules" / "@openai" / f"codex-{package}" / "vendor", root.parent / f"codex-{package}" / "vendor", root / "vendor"):
        candidate = vendor / triple / "bin/codex"
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError("managed_runtime_native_binary_unavailable")


def runtime_digest(binary: Path) -> str:
    vendor = binary.parent.parent if binary.parent.name == "bin" and (binary.parent.parent / "codex-package.json").is_file() else None
    entries = sorted(vendor.rglob("*")) if vendor else [binary]
    digest = hashlib.sha256()
    for entry in entries:
        if vendor and not entry.resolve().is_relative_to(vendor.resolve()):
            raise ValueError("managed_runtime_resource_escapes_vendor")
        name = str(entry.relative_to(vendor)) if vendor else "bin/codex"
        digest.update(json.dumps([name, "directory" if entry.is_dir() else "file", bool(entry.stat().st_mode & 0o111)], separators=(",", ":")).encode() + b"\0")
        if entry.is_file():
            with entry.open("rb") as handle:
                while data := handle.read(1024 * 1024):
                    digest.update(data)
    return digest.hexdigest()


def pin_runtime(outbox, binary: str) -> str:
    """Keep the executable and adjacent native resources immutable for active sessions."""
    source = native_binary(binary)
    digest = runtime_digest(source)
    root = runtime_root(outbox)
    destination = root / digest
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".pin-", dir=root))
        try:
            if source.parent.name == "bin" and (source.parent.parent / "codex-package.json").is_file():
                shutil.copytree(source.parent.parent, temporary / "native", symlinks=False)
            else:
                (temporary / "native/bin").mkdir(parents=True, mode=0o700)
                shutil.copy2(source, temporary / "native/bin/codex")
            pinned = temporary / "native/bin/codex"
            if runtime_digest(pinned) != digest or runtime_digest(source) != digest:
                raise ValueError("managed_runtime_changed_during_pin")
            for entry in temporary.rglob("*"):
                if entry.is_dir():
                    entry.chmod(0o700)
                else:
                    entry.chmod(0o700 if os.access(entry, os.X_OK) else 0o600)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    pinned = destination / "native/bin/codex"
    if destination.is_symlink() or runtime_digest(pinned) != digest:
        raise ValueError("managed_runtime_pinned_tree_changed")
    return str(pinned)


def selected_binary(outbox) -> str | None:
    active = outbox.metadata("update").get("active")
    if not active:
        return None
    path = Path(active["binary"])
    if not path.resolve().is_relative_to(runtime_root(outbox)) or not path.is_file():
        raise ValueError("managed_runtime_selection_unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != active["binary_sha256"]:
        raise ValueError("managed_runtime_selection_changed")
    if runtime_digest(path) != active["runtime_sha256"]:
        raise ValueError("managed_runtime_resources_changed")
    return str(path)


@contextmanager
def runtime_lease(binary: str):
    """Filesystem fencing survives quota failures in the SQLite GC reference."""
    artifact = Path(binary).parents[2]
    fd = os.open(artifact / ".runtime-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def update_status(outbox) -> dict:
    state = outbox.metadata("update")
    return {"state": state.get("state", "unchecked"), "latest_version": state.get("latest_version"), "candidate_version": (state.get("candidate") or {}).get("version"), "active_version": (state.get("active") or {}).get("version"), "previous_version": (state.get("previous") or {}).get("version"), "error_code": state.get("error_code"), "error_stage": state.get("error_stage"), "candidate_schema_fingerprint": (state.get("candidate") or {}).get("schema_fingerprint")}


def update_actions(outbox) -> list[str]:
    state = outbox.metadata("update")
    actions = ["check-update"] if shutil.which("npm") else []
    if state.get("latest_version") and shutil.which("npm"):
        actions.append("stage-update")
    if state.get("candidate"):
        actions.append("qualify-update")
        if state.get("candidate_qualified") and (state.get("active") or {}).get("runtime_sha256") != state["candidate"].get("runtime_sha256"):
            actions.append("promote-update")
    if state.get("previous") and state.get("state") != "rolled_back":
        actions.append("rollback-update")
    return actions


def reclaim_runtimes(outbox, state: dict):
    root = runtime_root(outbox)
    referenced = {Path(value["binary"]).parents[2].name for value in (state.get("active"), state.get("previous"), state.get("candidate"), outbox.metadata("running_runtime")) if value and value.get("binary")}
    for artifact in root.iterdir():
        if re.fullmatch(r"[a-f0-9]{64}", artifact.name) and artifact.name not in referenced:
            try:
                with runtime_lease(str(artifact / "native/bin/codex")):
                    shutil.rmtree(artifact)
            except BlockingIOError:
                continue


def _qualification(outbox, candidate: dict) -> dict:
    from codex_managed_delivery import owner_credentials

    secret, client_id = owner_credentials()
    if not secret or not client_id:
        raise ValueError("delivery_credentials_unavailable")
    root = runtime_root(outbox)
    receipt = root / "candidate-canary.json"
    script = Path(__file__).resolve().parents[1] / "codex-managed-canary.py"
    environment = {"PATH": os.environ["PATH"], "CODEX_REAL": candidate["binary"], "SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION": "1"}
    try:
        subprocess.run(["unshare", "-Urn", sys.executable, str(script), "--output", str(receipt)], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("candidate_conformance_failed") from None
    evidence = json.loads(receipt.read_text())
    if evidence.get("version") != f"codex-cli {candidate['version']}":
        raise ValueError("managed_candidate_receipt_binding_mismatch")
    import asyncio

    async def register():
        from agent_hub import AsyncAgentHubClient
        from agent_hub.models.native_observation import NativeProtocolProfileRegistration

        async with AsyncAgentHubClient(base_url=os.environ.get("AGENT_HUB_API", "http://localhost:8003/api").removesuffix("/api"), client_id=client_id, client_name="summitflow/codex-managed", request_source="codex-managed-update", timeout=30) as client:
            request = NativeProtocolProfileRegistration(provider_version=evidence["version"], schema_fingerprint=evidence["schema_fingerprint"], canary_receipt=evidence)
            return await client.register_native_protocol_profile(request, execution_owner_secret=secret)

    candidate["schema_fingerprint"] = evidence.get("schema_fingerprint")
    try:
        result = asyncio.run(register())
    except Exception as error:
        status = getattr(error, "status_code", None)
        code = "agent_hub_qualification_rejected" if isinstance(status, int) and 400 <= status < 500 else "agent_hub_qualification_unavailable"
        raise ValueError(code) from None
    profile = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    if not profile.get("qualified") or profile.get("provider_version") != evidence["version"] or profile.get("schema_fingerprint") != evidence["schema_fingerprint"]:
        raise ValueError("managed_candidate_authority_binding_mismatch")
    profiles = outbox.metadata("approved_profiles")
    profiles[profile["provider_version"]] = profile
    outbox.metadata("approved_profiles", profiles)
    return profile


def update_action(outbox, action: str):
    from codex_managed_capture import conformance

    with update_lease(outbox):
        state = outbox.metadata("update")
        state["error_code"] = None
        state["error_stage"] = None
        try:
            if action == "check-update":
                result = subprocess.run(["npm", "view", "@openai/codex", "version", "--json", "--registry", REGISTRY], capture_output=True, check=True, text=True, timeout=30)
                latest = json.loads(result.stdout)
                if not isinstance(latest, str) or not VERSION.fullmatch(latest):
                    raise ValueError("managed_update_version_invalid")
                state.update(latest_version=latest, state="available")
            elif action == "stage-update":
                latest = state.get("latest_version")
                if not isinstance(latest, str) or not VERSION.fullmatch(latest):
                    raise ValueError("managed_update_check_required")
                root = runtime_root(outbox)
                stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=root))
                try:
                    environment = {"PATH": os.environ["PATH"], "HOME": str(stage), "NPM_CONFIG_USERCONFIG": "/dev/null", "NPM_CONFIG_CACHE": str(stage / ".npm")}
                    subprocess.run(["npm", "install", "--prefix", str(stage), "--ignore-scripts", "--no-audit", "--no-fund", "--registry", REGISTRY, f"@openai/codex@{latest}"], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=180)
                    binary = pin_runtime(outbox, str(stage / "node_modules/@openai/codex/bin/codex.js"))
                    actual = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
                    if actual != f"codex-cli {latest}":
                        raise ValueError("managed_candidate_version_mismatch")
                    candidate = {"version": latest, "binary": binary, "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(), "runtime_sha256": runtime_digest(Path(binary))}
                    state.update(candidate=candidate, candidate_qualified=False, state="staged")
                finally:
                    shutil.rmtree(stage)
            elif action == "qualify-update":
                candidate = state.get("candidate")
                if not candidate:
                    raise ValueError("managed_update_stage_required")
                if hashlib.sha256(Path(candidate["binary"]).read_bytes()).hexdigest() != candidate["binary_sha256"]:
                    raise ValueError("managed_candidate_changed")
                if runtime_digest(Path(candidate["binary"])) != candidate["runtime_sha256"]:
                    raise ValueError("managed_candidate_resources_changed")
                _qualification(outbox, candidate)
                conformance(candidate["binary"], outbox=outbox)
                state.update(candidate_qualified=True, state="qualified")
            elif action in {"promote-update", "rollback-update"}:
                selected = state.get("candidate") if action == "promote-update" else state.get("previous")
                if not selected or (action == "promote-update" and not state.get("candidate_qualified")):
                    raise ValueError("managed_update_qualification_required")
                if (action == "rollback-update" and state.get("state") == "rolled_back") or (action == "promote-update" and (state.get("active") or {}).get("runtime_sha256") == selected.get("runtime_sha256")):
                    return
                if hashlib.sha256(Path(selected["binary"]).read_bytes()).hexdigest() != selected["binary_sha256"]:
                    raise ValueError("managed_candidate_changed")
                if runtime_digest(Path(selected["binary"])) != selected["runtime_sha256"]:
                    raise ValueError("managed_candidate_resources_changed")
                conformance(selected["binary"], outbox=outbox)
                previous = state.get("active")
                if not previous:
                    binary = pin_runtime(outbox, os.environ.get("CODEX_REAL", str(Path.home() / ".local/bin/codex-real")))
                    version, _, _ = conformance(binary, outbox=outbox)
                    previous = {"binary": binary, "version": version.removeprefix("codex-cli "), "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(), "runtime_sha256": runtime_digest(Path(binary))}
                state.update(active=selected, previous=previous, state="active" if action == "promote-update" else "rolled_back")
            else:
                raise ValueError("managed_update_action_unsupported")
        except Exception as error:
            fallback = {"check-update": "registry_check_failed", "stage-update": "candidate_install_failed", "qualify-update": "candidate_conformance_failed", "promote-update": "runtime_selection_failed", "rollback-update": "runtime_selection_failed"}
            code = str(error) if isinstance(error, ValueError) and str(error) in UPDATE_ERRORS else fallback.get(action, "runtime_selection_failed")
            if isinstance(error, ValueError) and str(error).startswith("unsupported_"):
                code = "candidate_protocol_unsupported"
            state.update(state="failed", error_code=code, error_stage=action)
            outbox.metadata("update", state)
            raise ManagedUpdateError(code, action) from None
        outbox.metadata("update", state)
        reclaim_runtimes(outbox, state)
