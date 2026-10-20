"""Private accepted-tool contract for Nightshift's owner action launcher.

No caller-selected identity or environment switch authorizes this handler. The
installed configuration and the actual process/session-manager UID must agree.
Only JSON evidence is returned; unit output and credentials are never exported.
"""
from __future__ import annotations

import json
import os
import pwd
import re
import socket
import stat
import struct
import uuid
from pathlib import Path
from typing import Any

from app.utils.agent_execution import run_as_agent

from . import service_deploy_client, service_ops
from . import service_owner_artifact as artifacts
from . import service_release as releases

CONFIG = Path("/etc/nightshift/owner-actions.json")
SITE = Path("/etc/nightshift/site.json")
PHASES = {"precheck", "apply", "verify", "rollback"}


def _trusted_json(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Owner runtime configuration must be installed by root")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Invalid owner runtime configuration")
    return value


def _identity(request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    config = _trusted_json(CONFIG)
    site = _trusted_json(SITE)
    owner_config = site.get("owner")
    owner = owner_config.get("user") if isinstance(owner_config, dict) else None
    if not isinstance(owner, str) or not owner:
        raise ValueError("Nightshift owner is not configured")
    uid = pwd.getpwnam(owner).pw_uid
    if uid == 0 or os.getuid() != uid or os.geteuid() != uid or request.get("expected_uid") != uid:
        raise ValueError("Owner runtime child is not the configured owner")
    runtime = Path(f"/run/user/{uid}")
    if runtime.stat().st_uid != uid or not (runtime / "bus").is_socket():
        raise ValueError("Configured owner's user manager is unavailable")
    if os.environ.get("XDG_RUNTIME_DIR") != str(runtime) or os.environ.get("DBUS_SESSION_BUS_ADDRESS") != f"unix:path={runtime}/bus":
        raise ValueError("Owner runtime session does not match the configured owner")
    if not config.get("tool_revision") or request.get("tool_revision") != config["tool_revision"]:
        raise ValueError("Owner runtime tool revision mismatch")
    with socket.socket(socket.AF_UNIX) as bus:
        bus.connect(str(runtime / "bus"))
        _pid, bus_uid, _gid = struct.unpack("3i", bus.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    if bus_uid != uid:
        raise ValueError("Owner user-manager bus has an unexpected identity")
    return bus_uid, config


def handle(phase: str, request: dict[str, Any]) -> dict[str, Any]:
    """Validate one frozen deployment phase as the already-dropped owner child.

    Status and service control are handled directly by Nightshift's installed
    helper. This private tool entry point is only for accepted release activation.
    """
    if phase not in PHASES or request.get("schema") != 1 or request.get("action") != "owner.deploy":
        raise ValueError("Unknown owner deployment protocol, action or phase")
    _uid, config = _identity(request)
    params = request.get("params")
    if not isinstance(params, dict):
        raise ValueError("Owner action parameters are required")
    project_id = params.get("project")
    projects = config.get("projects")
    registered = projects.get(project_id) if isinstance(projects, dict) and isinstance(project_id, str) else None
    if not isinstance(registered, dict):
        raise ValueError("Project is not registered for owner actions")
    sha, operation = params.get("sha"), params.get("operation")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha) or operation not in {"deploy", "rollback"}:
        raise ValueError("Owner deployment requires an exact source and operation")
    project = service_ops.load_project(project_id)
    if project.runtime_user != "owner":
        raise ValueError("Project is not configured with the owner runtime")
    artifacts.portable(project)
    if not set(project.all_services).issubset(set(registered.get("units", ()))):
        raise ValueError("Project units do not match the installed owner registry")
    with releases.deployment_lock(project_id):
        if phase == "precheck":
            if operation == "deploy" and service_deploy_client.main_sha(project.root, as_agent=True) != sha:
                raise ValueError("Owner deployment source is no longer main")
            result = {"before": _precheck(project, request, operation, sha, config)}
        else:
            before = request.get("before")
            if not isinstance(before, dict):
                raise ValueError("Owner deployment is missing its frozen before state")
            frozen = json.loads(_snapshot_path(project_id, before["transaction"]).read_text())
            if frozen["request_id"] != request.get("request_id") or frozen["sha"] != sha:
                raise ValueError("Owner deployment transaction identity mismatch")
            if phase == "apply":
                if _pointer(project_id, "current") != frozen["current"]:
                    raise ValueError("Owner release changed after precheck")
                release = (_retained(project_id, before["build_id"]) if operation == "rollback" else
                    artifacts.import_artifact(before["artifact"], project_id=project_id, sha=sha,
                        build_id=before["build_id"], tool_revision=request["tool_revision"], tracked=frozen["tracked"]))
                if operation == "deploy":
                    _agent_job(config, project, {"operation": "cleanup", "descriptor": before["artifact"]})
                original_receipt = releases._read_receipt(release) if operation == "rollback" else None
                try:
                    _activate(project, release)
                    releases.complete_release(release, service_references=None)
                    releases.validate_deployment_receipt(release.receipt_path, source_commit=sha)
                    frozen["applied_units"] = _unit_contents(project)
                    releases._write_json(_snapshot_path(project_id, before["transaction"]), frozen)
                except Exception:
                    if operation != "rollback":
                        releases.fail_release(release, "activation")
                    try:
                        _restore(project, frozen, release.build_id, allow_uncommitted=True)
                    finally:
                        if original_receipt is not None:
                            releases._write_receipt(release.receipt_path, original_receipt)
                    raise
                result = {"result": {"build_id": release.build_id, "source_commit": sha,
                    "health": "verified", "deployment_id": releases._read_receipt(release)["deployment_id"]}}
            elif phase == "verify":
                release = _retained(project_id, before["build_id"])
                if _pointer(project_id, "current") != release.build_id or service_ops.verify_health(
                        service_ops.project_at_source(project, release.source_root, source_sha=release.source.source_commit)):
                    raise ValueError("Owner deployed release verification failed")
                result = {"result": {"build_id": release.build_id, "health": "verified"}}
            else:
                restored = _restore(project, frozen, before["build_id"])
                result = {"result": {"restored": restored, "health": "verified" if restored else "later_release_preserved"}}
    return {"schema": 1, "request_id": request.get("request_id"), "action": request["action"],
        "project": project_id, "phase": phase, "uid": os.getuid(), "manager_uid": _uid,
        "tool_revision": config["tool_revision"], "ok": True, **result}


def prepare(project_id: str, *, sha: str, build_id: str, tool_revision: str) -> dict[str, Any]:
    """Agent-only CLI adapter; caller keeps build output off JSON stdout."""
    from app.services import tether
    if os.getuid() != tether._agent_uid():
        raise ValueError("Owner artifact preparation must run as the configured agent")
    return artifacts.prepare(project_id, sha=sha, build_id=build_id, tool_revision=tool_revision)


def _pointer(project_id: str, name: str) -> str | None:
    state = releases._project_state(project_id)
    target = releases._pointer_release(state / name, state / "releases")
    return target.name if target else None


def _snapshot_path(project_id: str, transaction: str) -> Path:
    if not isinstance(transaction, str) or not re.fullmatch(r"[0-9a-f]{32}", transaction):
        raise ValueError("Invalid owner transaction")
    return releases._project_state(project_id) / "owner-transactions" / f"{transaction}.json"


def _retained(project_id: str, build_id: str) -> releases.PreparedRelease:
    if not re.fullmatch(r"[0-9a-f]{32}", build_id):
        raise ValueError("Invalid retained release")
    state = releases._project_state(project_id)
    value = json.loads((state / "receipts" / f"{build_id}.json").read_text())
    release = releases.PreparedRelease(project_id, build_id,
        releases.AcceptedSource.from_descriptor(value["source"], require_full=True),
        state / "releases" / build_id, state / "releases" / build_id / "source",
        state / "receipts" / f"{build_id}.json")
    if releases._read_receipt(release).get("state") != "succeeded" or not release.source_root.is_dir():
        raise ValueError("Previous accepted release is unavailable")
    return release


def _units_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd" / "user"


def _unit_contents(project: service_ops.ProjectServices) -> dict[str, str | None]:
    # Match the complete set rendered by sync_systemd_units, including the
    # services activated by timer/socket units.
    units = dict.fromkeys(service_ops.canonical_unit(name) for unit in project.all_services
                          for name in (unit, service_ops.activated_service(unit)) if name)
    return {unit: ((_units_dir() / unit).read_text() if (_units_dir() / unit).exists() else None)
            for unit in units}


def _tool_argv(config: dict[str, Any]) -> list[str]:
    argv = config.get("tool_argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv) or not Path(argv[0]).is_absolute():
        raise ValueError("Pinned owner tool argv is unavailable")
    return argv


def _agent_job(config: dict[str, Any], project: service_ops.ProjectServices, payload: dict[str, Any]) -> dict[str, Any]:
    completed = run_as_agent([*_tool_argv(config), "checkout-job", "cli.lib.service_owner_artifact"],
        cwd=project.root, input=json.dumps({"project": project.project_id, **payload}),
        capture_output=True, text=True, timeout=3600, max_output_bytes=16 * 1024 * 1024)
    if completed.returncode:
        raise ValueError("Pinned agent artifact validation or cleanup failed; check agent access to the installed tool")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("Pinned agent artifact job returned invalid evidence")
    return value


def _precheck(project: service_ops.ProjectServices, request: dict[str, Any], operation: str, sha: str,
              config: dict[str, Any]) -> dict[str, Any]:
    transaction, build_id = uuid.uuid4().hex, uuid.uuid4().hex
    current, previous = _pointer(project.project_id, "current"), _pointer(project.project_id, "previous")
    if current:
        _retained(project.project_id, current)
    if operation == "rollback":
        if not previous or _retained(project.project_id, previous).source.source_commit != sha:
            raise ValueError("Requested rollback is not the previous accepted release")
        build_id, artifact, tracked = previous, None, {}
    else:
        completed = run_as_agent([*_tool_argv(config), "service", "owner-prepare", project.project_id, "--sha", sha,
            "--build-id", build_id, "--tool-revision", request["tool_revision"]], cwd=project.root,
            capture_output=True, text=True, timeout=3600, max_output_bytes=1024 * 1024)
        if completed.returncode:
            raise ValueError("Pinned agent artifact preparation failed; check agent access to the installed tool")
        artifact = json.loads(completed.stdout)
        artifacts.validate(artifact, project_id=project.project_id, sha=sha, build_id=build_id,
                           tool_revision=request["tool_revision"])
        proof = _agent_job(config, project, {"operation": "validate", "descriptor": artifact})
        canonical = releases.AcceptedSource.from_descriptor(proof["source"], require_full=True)
        for key in ("acceptance_id", "source_commit", "source_tree", "input_fingerprint", "acceptance_plan_fingerprint"):
            if artifact["source"].get(key, "") != canonical.evidence()[key]:
                raise ValueError("Artifact differs from canonical accepted source")
        tracked = proof["tracked"]
    units = _unit_contents(project)
    active = [unit for unit, contents in units.items()
              if contents is not None and service_ops.service_state(unit) == "active"]
    active_optional = [unit for unit in project.optional_workers if service_ops.canonical_unit(unit) in active]
    frozen = {"request_id": request.get("request_id"), "sha": sha, "current": current,
              "previous": previous, "units": units, "active": active, "optional": active_optional, "tracked": tracked}
    path = _snapshot_path(project.project_id, transaction)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    releases._write_json(path, frozen)
    path.chmod(0o600)
    return {"transaction": transaction, "build_id": build_id, "artifact": artifact,
        "previous_build_id": current, "undo": "restore previous accepted runtime" if current else "restore existing units and runtime; no previous accepted release"}


def _activate(project: service_ops.ProjectServices, release: releases.PreparedRelease) -> None:
    services = service_ops.project_at_source(project, release.source_root, source_sha=release.source.source_commit)
    # Deliberately no dependency, source-build or project installer call here.
    for name, work in (("migrations", service_ops.run_migrations), ("systemd_units", service_ops.sync_systemd_units)):
        code = work(services)
        releases.mark_phase(release, name, status="succeeded" if code == 0 else "failed")
        if code:
            raise ValueError(f"Owner activation failed: {name}")
    workers = (*services.default_workers, *(unit for unit in services.optional_workers if service_ops.service_state(unit) == "active"))
    for unit, port in ((services.backend_service, services.backend_port),
                       *((unit, 0) for unit in workers), (services.frontend_service, services.frontend_port)):
        if unit and service_ops.restart_service(unit, port=port, project=services):
            raise ValueError("Owner activation failed: restart")
    releases.mark_phase(release, "restart", status="succeeded")
    if service_ops.verify_health(services):
        raise ValueError("Owner activation failed: health or seeds")
    releases.mark_phase(release, "health", status="succeeded")
    if service_ops.sync_seeds(services):
        raise ValueError("Owner activation failed: health or seeds")
    releases.mark_phase(release, "seeds", status="succeeded")


def _restore(project: service_ops.ProjectServices, frozen: dict[str, Any], applied_build: str,
             *, allow_uncommitted: bool = False) -> bool:
    current = _pointer(project.project_id, "current")
    if current != applied_build and not (allow_uncommitted and current == frozen["current"]):
        return False
    if "applied_units" in frozen and _unit_contents(project) != frozen["applied_units"]:
        raise ValueError("Owner unit changed after deployment; preserving later edits")
    for unit, contents in frozen["units"].items():
        path = _units_dir() / unit
        if contents is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(contents)
    if service_ops.run(["systemctl", "--user", "daemon-reload"]):
        raise ValueError("Previous owner runtime daemon reload failed")
    prior = _retained(project.project_id, frozen["current"]) if frozen["current"] else None
    if prior is None:
        if service_ops.stop_services(project):
            raise ValueError("Failed initial owner runtime could not be stopped")
        if "active" not in frozen:
            raise ValueError("Owner unit configuration restored; previous activity is unavailable")
    services = (service_ops.project_at_source(project, prior.source_root, source_sha=prior.source.source_commit)
                if prior else project)
    workers = (*services.default_workers, *frozen["optional"])
    if prior is None:
        mains = {service_ops.canonical_unit(unit) for unit in (services.backend_service, services.frontend_service)}
        workers = tuple(unit for unit in frozen["active"] if unit not in mains)
    for unit, port in ((services.backend_service, services.backend_port),
                       *((unit, 0) for unit in workers),
                       (services.frontend_service, services.frontend_port)):
        if prior is None and service_ops.canonical_unit(unit) not in frozen["active"]:
            continue
        if unit and service_ops.restart_service(unit, port=port, project=services):
            raise ValueError("Previous owner runtime restart failed")
    running = {service_ops.canonical_unit(unit) for unit in (services.backend_service, services.frontend_service) if unit}
    if (prior is not None or running.issubset(frozen["active"])) and service_ops.verify_health(services):
        raise ValueError("Previous owner runtime health verification failed")
    state = releases._project_state(project.project_id)
    for name in ("current", "previous"):
        if frozen[name]:
            releases._replace_symlink(state / name, state / "releases" / frozen[name])
        else:
            (state / name).unlink(missing_ok=True)
    return True
