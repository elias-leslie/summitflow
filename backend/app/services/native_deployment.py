"""Server-issued observations for owner-managed native deployments.

Owners establish artifact provenance and live behavior. ST executes the trusted
operation from accepted Git objects, proves runtime input equivalence, and owns
the immutable receipt. Client verification JSON is never an issuer.
"""
from __future__ import annotations

import hashlib
import os
import re
import tarfile
import tempfile
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from st_sdk.native_deployment import (
    canonical_json,
    decode_json,
    validate_observation_request,
    validate_observation_response,
)

from app.utils import safe_subprocess

KIND = "native_deployment_observation.v1"


class NativeDeploymentError(ValueError):
    """Native evidence could not be issued or authenticated."""


def deployment_evidence_family(project: str) -> str:
    """Trusted owner metadata chooses the verifier; client markers cannot."""
    from cli.extensions import load_extensions

    catalog = load_extensions(set())
    if catalog.diagnostics:
        return "unknown"
    owners = [record for record in catalog.records if record.binding and record.binding.owner == project]
    if any(record.manifest is None for record in owners):
        return "unknown"
    # A denied/incompatible registration still declares native ownership.
    # Revocation must never downgrade verification to caller-asserted legacy.
    if any(record.manifest and "observe_deployment" in record.manifest.structured_operations for record in owners):
        return "native"
    return "legacy"


def _git(root: Path, *args: str) -> bytes:
    result = safe_subprocess.run(["git", "--no-replace-objects", *args], cwd=root, capture_output=True, check=False)
    if result.returncode:
        raise NativeDeploymentError("Native deployment source objects are unavailable")
    return result.stdout


def runtime_projection(root: Path, commit: str, rule: Mapping[str, Any]) -> str:
    """Default to all tree entries, including modes, embeds and gitlinks."""
    entries = []
    for row in _git(root, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if path in rule["paths"] or any(path.startswith(prefix) for prefix in rule["prefixes"]):
            continue
        entries.append([path, *metadata.decode("ascii").split()])
    return hashlib.sha256(canonical_json({"entries": entries}).encode()).hexdigest()


def source_binding(root: Path, response: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the build revision intact; prove equality under the pinned rule."""
    accepted = response["accepted_source_commit"]
    deployed = response["deployed_source_commit"]
    _git(root, "merge-base", "--is-ancestor", deployed, accepted)
    policy_path = response["runtime_policy_path"]
    policy = _git(root, "show", f"{accepted}:{policy_path}")
    if decode_json(policy) != response["runtime_exclusions"]:
        raise NativeDeploymentError("Observer runtime rule differs from accepted source")
    accepted_hash = runtime_projection(root, accepted, response["runtime_exclusions"])
    deployed_hash = runtime_projection(root, deployed, response["runtime_exclusions"])
    if accepted_hash != deployed_hash:
        raise NativeDeploymentError("Deployed runtime inputs differ from accepted source")
    changes = _git(root, "diff", "--name-only", "-z", deployed, accepted).decode().split("\0")
    return {
        "rule_version": response["runtime_exclusions"]["rule_version"],
        "runtime_policy_path": policy_path,
        "runtime_policy_sha256": hashlib.sha256(policy).hexdigest(),
        "runtime_exclusions": response["runtime_exclusions"],
        "deployed_source_commit": deployed,
        "accepted_source_commit": accepted,
        "deployed_projection": deployed_hash,
        "accepted_projection": accepted_hash,
        "changed_paths": [path for path in changes if path],
    }


def _store_root() -> Path:
    from cli.lib.service_release import service_state_root

    return service_state_root() / "native-observations"


def _record_path(receipt_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", receipt_id):
        raise NativeDeploymentError("Invalid native receipt identity")
    return _store_root() / f"{receipt_id}.json"


def _write_record(record: dict[str, Any]) -> Path:
    root = _store_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise NativeDeploymentError("Native receipt store must be private to the service account")
    path = _record_path(record["receipt_id"])
    # Exclusive creation preserves old attempts, including failures.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(canonical_json(record) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def read_native_evidence(receipt_id: str, *, project: str | None = None) -> dict[str, Any]:
    """Only fixed private server state is a native receipt source."""
    path = _record_path(receipt_id)
    try:
        root = _store_root()
        if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
            raise NativeDeploymentError("Native receipt store must be private to the service account")
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise NativeDeploymentError("Native receipt is not service-owned private state")
        record = decode_json(path.read_bytes())
    except OSError as exc:
        raise NativeDeploymentError("Server-issued native receipt is unavailable") from exc
    if record.get("kind") != KIND or record.get("receipt_id") != receipt_id:
        raise NativeDeploymentError("Native receipt identity mismatch")
    if project is not None and record.get("project") != project:
        raise NativeDeploymentError("Native receipt belongs to another project")
    return record


def _descriptors(record: Mapping[str, Any]) -> dict[str, Any]:
    artifact = str(_record_path(record["receipt_id"]))
    digest = hashlib.sha256((canonical_json(record) + "\n").encode()).hexdigest()
    common = {
        "kind": KIND, "receipt_id": record["receipt_id"], "project": record["project"],
        "task_id": record["task_id"], "acceptance_id": record["acceptance_id"],
        "source_commit": record["observation"]["deployed_source_commit"],
        "accepted_source_commit": record["accepted_source_commit"],
        "artifact": artifact, "sha256": digest,
    }
    return {
        "deployment": {**common, "state": record["state"],
                       "source_binding": record["source_binding"],
                       "target_id": record["observation"]["target_id"]},
        "live_validation": {**common, "checks": [
            {"id": check["id"], "state": check["state"], "artifact": artifact, "sha256": digest}
            for check in record["observation"]["checks"]
        ]},
    }


def validate_native_evidence(
    deployment: Mapping[str, Any], live: Mapping[str, Any], *, task_id: str,
    project: str, acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-read server state at every completion gate; distrust stored task JSON."""
    receipt_id = str(deployment.get("receipt_id") or "")
    record = read_native_evidence(receipt_id)
    if (record.get("task_id"), record.get("project"), record.get("acceptance_id"),
        record.get("accepted_source_commit")) != (
        task_id, project, acceptance.get("acceptance_id"), acceptance.get("source_commit")
    ):
        raise NativeDeploymentError("Native receipt is bound to another task or accepted source")
    expected = _descriptors(record)
    if dict(deployment) != expected["deployment"] or dict(live) != expected["live_validation"]:
        raise NativeDeploymentError("Submitted native evidence differs from the server-issued receipt")
    if record["state"] != "succeeded":
        raise NativeDeploymentError("Native observations did not succeed")
    return expected


def _observe(root: Path, accepted: Mapping[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from cli.extensions import _environment, extension_context, load_extensions

    records = [record for record in load_extensions(set()).records
               if record.binding and record.binding.owner == request["project"]
               and record.manifest and "observe_deployment" in record.manifest.structured_operations]
    if len(records) != 1:
        raise NativeDeploymentError("Project requires one trusted native observation extension")
    record = records[0]
    binding, manifest = record.binding, record.manifest
    assert binding is not None and manifest is not None
    operation = manifest.structured_operations["observe_deployment"]
    if (record.status != "unverified" or binding.execution_source != "checkout"
        or operation.request_contract_version != 1 or operation.response_schema_version != 1
        or set(manifest.effects) - {"network", "read-remote", "read-local", "credentials", "process"}):
        raise NativeDeploymentError("Native observation extension lacks a compatible read-only grant")
    with tempfile.TemporaryDirectory(prefix="st-native-observer-") as temporary:
        snapshot = Path(temporary) / "source"
        snapshot.mkdir()
        archive = Path(temporary) / "source.tar"
        _git(root, "archive", "--format=tar", "--output", str(archive), accepted["source_commit"])
        with tarfile.open(archive) as source:
            source.extractall(snapshot, filter="data")
        archive.unlink()
        executable = snapshot / binding.executable
        if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise NativeDeploymentError("Accepted observer entrypoint is unavailable or unsafe")
        executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        mode = _git(root, "ls-tree", accepted["source_commit"], "--", binding.executable).split(b" ", 1)[0]
        original_digest = hashlib.sha256(_git(root, "show", f"{accepted['source_commit']}:{binding.executable}")).hexdigest()
        if mode != b"100755" or original_digest != executable_digest:
            raise NativeDeploymentError("Observer executable differs from its accepted Git object")
        # Context selects approved owner-local configuration, never a client host.
        context = extension_context()
        context.update(project_id=request["project"], project_root=str(root), cwd=str(snapshot),
                       output={"human": False, "compact": False, "progress_only": False})
        env = _environment(binding, context)
        # GNU timeout owns the process group; the ASGI-safe helper uses
        # posix_spawn rather than Python fork/session setup in a web worker.
        # The deadline matches the existing ST client operation ceiling.
        result = safe_subprocess.run(
            ["timeout", "--signal=KILL", "330s", str(executable), *binding.arguments,
             "--request", canonical_json(request)], cwd=snapshot, env=env,
            capture_output=True, check=False,
        )
        if result.returncode:
            raise NativeDeploymentError("Native observer did not return a valid observation; credentials and stderr withheld")
        response = validate_observation_response(decode_json(result.stdout), request=request)
        pin = {"extension_id": binding.id, "manifest_version": manifest.version,
               "manifest_sha256": hashlib.sha256(canonical_json(manifest.model_dump()).encode()).hexdigest(),
               "binding_sha256": hashlib.sha256(canonical_json(binding.model_dump()).encode()).hexdigest(),
               "observer_source_commit": accepted["source_commit"], "observer_source_tree": accepted["source_tree"],
               "executable": binding.executable, "executable_sha256": executable_digest}
        return response, pin


def issue_native_evidence(task: Mapping[str, Any], root: Path, artifact: Path) -> dict[str, Any]:
    """The sole issuer: validate current acceptance, execute, prove and persist."""
    from cli.lib.acceptance import AcceptanceError

    started = time.time()
    try:
        return _issue_native_evidence(task, root, artifact)
    except Exception as exc:
        # A malformed/failed observer is audit evidence, never a successful
        # deployment descriptor. Preserve the attempt without raw output,
        # request-selected paths, credential values or private stderr.
        attempt = {"kind": "native_deployment_attempt.v1", "receipt_id": uuid.uuid4().hex,
                   "task_id": str(task["id"]), "project": str(task["project_id"]),
                   "state": "failed", "started_at": started, "completed_at": time.time(),
                   "failure_type": type(exc).__name__}
        try:
            _write_record(attempt)
        except (NativeDeploymentError, OSError):
            raise NativeDeploymentError("Native observation failed and its attempt could not be retained") from exc
        detail = str(exc) if isinstance(exc, (AcceptanceError, NativeDeploymentError)) else type(exc).__name__
        raise NativeDeploymentError(f"{detail}; retained failed attempt {attempt['receipt_id']}") from exc


def _issue_native_evidence(task: Mapping[str, Any], root: Path, artifact: Path) -> dict[str, Any]:
    from cli.lib.acceptance import (
        AcceptanceError,
        _git_common_dir,
        repo_lock,
        validate_acceptance_receipt,
    )

    task_id, project = str(task["id"]), str(task["project_id"])
    if task.get("status") != "running":
        raise NativeDeploymentError("Claim the task before observing its required native deployment")
    with repo_lock(root, purpose="native-deployment-observation"):
        artifact = artifact.resolve(strict=True)
        receipt_root = (_git_common_dir(root) / "st" / "acceptance").resolve(strict=True)
        if artifact.parent != receipt_root or not re.fullmatch(r"[0-9a-f]{64}\.json", artifact.name):
            raise NativeDeploymentError("Native observation requires a canonical local acceptance artifact")
        try:
            accepted = validate_acceptance_receipt(root, artifact, sha="HEAD")
        except AcceptanceError as exc:
            raise NativeDeploymentError(str(exc)) from exc
        if accepted.get("scope"):
            raise NativeDeploymentError("Native deployment observation requires full source acceptance")
        request = validate_observation_request({
            "contract_version": 1, "operation": "observe_deployment", "challenge": uuid.uuid4().hex,
            "task_id": task_id, "project": project, "accepted_source_commit": accepted["source_commit"],
            "acceptance_id": accepted["acceptance_id"],
        })
        started = time.time()
        response, pin = _observe(root, accepted, request)
        succeeded = all(check["state"] == "success" for check in response["checks"])
        proof = source_binding(root, response) if succeeded else {"state": "not_verified", "reason": "observation_failed"}
        record = {"kind": KIND, "receipt_id": uuid.uuid4().hex, "project": project, "task_id": task_id,
                  "acceptance_id": accepted["acceptance_id"], "accepted_source_commit": accepted["source_commit"],
                  "accepted_source_tree": accepted["source_tree"], "started_at": started, "completed_at": time.time(),
                  "state": "succeeded" if succeeded else "failed", "request": request, "observer": pin,
                  "source_binding": proof, "observation": response}
        _write_record(record)
        if not succeeded:
            raise NativeDeploymentError(f"Native observations failed; retained receipt {record['receipt_id']}")
        return _descriptors(record)
