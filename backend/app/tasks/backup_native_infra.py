"""Infrastructure backup helpers for native backup tasks."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..logging_config import get_logger
from ..services.backup_keys import backup_key_directory
from ..utils.shared_paths import get_host_config_root, get_repo_root
from .backup_activity import (
    backup_phase,
    check_backup_cancelled,
    current_activity,
    record_local_archive,
    run_bulk_process,
)
from .backup_native_archive import (
    INFRASTRUCTURE_DATABASE_DUMP_NAME,
    INFRASTRUCTURE_DATABASE_PAYLOAD_NAME,
    _gzip_payload_file,
    _regular_file_filter,
    _run_gzip_stream,
    _run_plain_stream,
    payload_tree_metadata,
    verify_archive,
)
from .backup_native_offsite import encrypt_completed_archive, replicate_completed_archive
from .backup_native_recovery import (
    _snapshot_entry_is_stable,
    copy_inventory_snapshot,
    inventory_project_tree,
)
from .backup_native_smb import StorageConfig, _save_pending, _smb_upload, _storage_config
from .backup_native_storage import (
    apply_local_retention,
    copy_to_local_backend,
    local_storage_config,
    storage_backend_type,
    update_backup_index,
)

logger = get_logger(__name__)

INFRA_BACKUP_TIMEOUT = 900
CAPTURE_MANIFEST_VERSION = 1


def _find_compose_container(service: str) -> str | None:
    if not Path("/var/run/docker.sock").exists():
        return None
    commands = [
        ["docker", "compose", "-p", "summitflow-stack", "ps", "--format", "{{.Name}}", service],
        ["docker", "ps", "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.Names}}"],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    return None


def _dump_infra_database(destination: Path) -> int:
    pg_user = os.environ.get("PGUSER", "admin")
    pg_host = os.environ.get("PGHOST", "localhost")
    pg_container = os.environ.get("POSTGRES_CONTAINER") or _find_compose_container("postgres")
    stream = _run_gzip_stream if destination.suffix == ".gz" else _run_plain_stream
    if pg_container:
        command = ["docker", "exec", pg_container, "pg_dumpall", "-U", pg_user]
        returncode, stderr = stream(command, destination, env=None, timeout=INFRA_BACKUP_TIMEOUT)
    else:
        env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "")}
        command = ["pg_dumpall", "-U", pg_user, "-h", pg_host]
        returncode, stderr = stream(command, destination, env=env, timeout=INFRA_BACKUP_TIMEOUT)
    if returncode != 0:
        detail = stderr.decode(errors="ignore").strip()
        raise RuntimeError(f"pg_dumpall failed: {detail or returncode}")
    return destination.stat().st_size


def _copy_if_exists(src: Path, dest: Path) -> int:
    if _path_is_within(src, backup_key_directory()):
        return 0
    try:
        source_mode = src.lstat().st_mode
    except FileNotFoundError:
        return 0
    if not (stat.S_ISDIR(source_mode) or stat.S_ISREG(source_mode)):
        return 0
    _copy_regular_path(src, dest)
    return 1


def _ignore_unsafe_copy_entries(directory: str, names: list[str]) -> list[str]:
    """Exclude links and special files before copying configuration trees."""
    ignored: list[str] = []
    root = Path(directory)
    for name in names:
        if _path_is_within(root / name, backup_key_directory()):
            ignored.append(name)
            continue
        try:
            mode = (root / name).lstat().st_mode
        except OSError:
            ignored.append(name)
            continue
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            ignored.append(name)
    return ignored


def _safe_config_archive_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Exclude member types restore rejects."""
    return member if member.isdir() or member.isreg() else None


def _absolute_path(path: Path) -> Path:
    """Normalize a host path lexically without following links."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _path_is_within(path: Path, root: Path) -> bool:
    path = _absolute_path(path)
    root = _absolute_path(root)
    return path == root or root in path.parents


def _copy_regular_path(
    source: Path,
    destination: Path,
    *,
    excluded_roots: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Copy regular files/directories without dereferencing links.

    Link identities are returned for recovery manifests, but link targets are
    never opened. Any unreadable regular entry raises so its component can be
    marked incomplete rather than silently presented as covered.
    """
    source = _absolute_path(source)
    destination = _absolute_path(destination)
    exclusions = tuple(
        _absolute_path(item) for item in (*excluded_roots, backup_key_directory())
    )
    result: dict[str, Any] = {
        "files": 0,
        "links": [],
        "special_files_skipped": 0,
        "excluded_paths": 0,
    }

    def excluded(path: Path) -> bool:
        return any(_path_is_within(path, root) for root in exclusions)

    def record_entry(path: Path, relative: Path) -> None:
        check_backup_cancelled()
        if excluded(path):
            result["excluded_paths"] += 1
            return
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            result["links"].append(
                {"path": relative.as_posix(), "target": os.readlink(path)}
            )
            return
        if stat.S_ISREG(mode):
            inventory_path = relative.as_posix() if stat.S_ISDIR(source_mode) else source.name
            if inventory_path in before:
                result["files"] += 1
            return
        if not stat.S_ISDIR(mode):
            result["special_files_skipped"] += 1
            return

        with os.scandir(path) as entries:
            children = sorted(entries, key=lambda item: item.name)
        for child in children:
            child_path = Path(child.path)
            record_entry(child_path, relative / child.name)

    if excluded(source):
        result["excluded_paths"] = 1
        return result
    source_mode = source.lstat().st_mode
    if not (stat.S_ISDIR(source_mode) or stat.S_ISREG(source_mode)):
        record_entry(source, Path("."))
        return result
    source_base = source if stat.S_ISDIR(source_mode) else source.parent

    def excluded_relative(relative: str, _patterns: tuple[str, ...]) -> bool:
        return excluded(source_base / relative)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="infra-capture-", dir=destination.parent) as temporary:
        captured = Path(temporary) / "snapshot"
        before = inventory_project_tree(source, (), excluded_relative)
        copy_inventory_snapshot(source, captured, {rel: entry for rel, entry in before.items() if entry.kind == "file"})
        record_entry(source, Path("."))
        after = inventory_project_tree(source, (), excluded_relative)
        if any(
            not _snapshot_entry_is_stable(source, captured, rel, before.get(rel), after.get(rel))
            for rel in set(before) | set(after)
        ):
            raise RuntimeError("Infrastructure backup source changed during capture")
        if stat.S_ISREG(source_mode):
            shutil.copy2(captured / source.name, destination, follow_symlinks=False)
        else:
            shutil.copytree(captured, destination, dirs_exist_ok=True, symlinks=False)
    result["links"] = sorted(result["links"], key=lambda item: item["path"])
    return result


def _write_capture_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _path_kind(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    return "unsupported"


def _cloudflared_credential_path(config_path: Path) -> Path:
    """Resolve Cloudflared's exact credential reference from safe YAML."""
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError("cloudflared config is invalid") from exc
    if not isinstance(document, dict):
        raise ValueError("cloudflared config is not a mapping")
    raw_reference = document.get("credentials-file")
    if not isinstance(raw_reference, str) or not raw_reference.strip():
        raise ValueError("cloudflared credential reference is missing or unsupported")
    if "\x00" in raw_reference:
        raise ValueError("cloudflared credential reference is missing or unsupported")
    referenced = Path(raw_reference.strip()).expanduser()
    if not referenced.is_absolute():
        referenced = config_path.parent / referenced
    return _absolute_path(referenced)


def _capture_host_ingress(destination: Path) -> dict[str, Any]:
    """Capture configured host ingress state without exposing secret content."""
    destination.mkdir(parents=True, exist_ok=True)
    cloud_config = _absolute_path(
        Path(os.environ.get("CLOUDFLARED_CONFIG", "/etc/cloudflared/config.yml"))
    )
    caddy_config = _absolute_path(
        Path(os.environ.get("CADDY_CONFIG", "/etc/caddy/Caddyfile"))
    )
    caddy_env = _absolute_path(
        Path(os.environ.get("CADDY_ENV_FILE", "/etc/caddy/env"))
    )
    result: dict[str, Any] = {
        "status": "missing",
        "files": 0,
        "missing": [],
    }
    errors: list[str] = []
    try:
        cloud_kind = _path_kind(cloud_config)
        if cloud_kind == "file":
            copied = _copy_regular_path(
                cloud_config,
                destination / "cloudflared" / "config.yml",
            )
            result["files"] += copied["files"]
            try:
                credential_file = _cloudflared_credential_path(cloud_config)
            except ValueError:
                errors.append("cloudflared credential reference is missing or unsupported")
            else:
                credential_kind = _path_kind(credential_file)
                if credential_kind == "file":
                    copied = _copy_regular_path(
                        credential_file,
                        destination / "cloudflared" / credential_file.name,
                    )
                    result["files"] += copied["files"]
                    if copied["files"] != 1:
                        errors.append("cloudflared credential reference is excluded")
                    else:
                        result["credential_file"] = credential_file.name
                elif credential_kind == "missing":
                    result["missing"].append("cloudflared_credentials")
                else:
                    errors.append("cloudflared credential reference is unsupported")
        elif cloud_kind != "missing":
            errors.append("cloudflared config is not a regular file")
        else:
            result["missing"].append("cloudflared_config")

        for label, source, target_name in (
            ("caddy_config", caddy_config, "Caddyfile"),
            ("caddy_env", caddy_env, "env"),
        ):
            kind = _path_kind(source)
            if kind == "file":
                copied = _copy_regular_path(source, destination / "caddy" / target_name)
                result["files"] += copied["files"]
            else:
                result["missing"].append(label)
    except OSError:
        errors.append("required ingress state is unreadable")

    if errors:
        result.update(status="error", error="; ".join(dict.fromkeys(errors)))
    elif not result["missing"]:
        result["status"] = "captured"

    _write_capture_manifest(
        destination / "manifest.json",
        {"schema_version": CAPTURE_MANIFEST_VERSION, **result},
    )
    return result


def _capture_user_systemd(destination: Path) -> dict[str, Any]:
    """Capture user unit files and link identities representing enablement."""
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    ).expanduser()
    source = _absolute_path(config_home / "systemd" / "user")
    destination.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"status": "missing", "files": 0, "enablement": []}
    try:
        kind = _path_kind(source)
        if kind == "directory":
            copied = _copy_regular_path(
                source,
                destination / "files",
                excluded_roots=(backup_key_directory(),),
            )
            result.update(
                status="captured",
                files=copied["files"],
                enablement=copied["links"],
                special_files_skipped=copied["special_files_skipped"],
            )
        elif kind != "missing":
            result.update(status="error", error="systemd user state is not a directory")
    except OSError:
        result.update(status="error", error="systemd user state is unreadable")
    _write_capture_manifest(
        destination / "manifest.json",
        {"schema_version": CAPTURE_MANIFEST_VERSION, **result},
    )
    return result


def _capture_agent_hub_state(destination: Path) -> dict[str, Any]:
    """Capture Agent Hub durable host state while excluding backup keys."""
    state_home = Path(
        os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    ).expanduser()
    source = _absolute_path(state_home / "agent-hub")
    result: dict[str, Any] = {"status": "missing", "files": 0}
    try:
        kind = _path_kind(source)
        if kind == "directory":
            copied = _copy_regular_path(
                source,
                destination / "files",
                excluded_roots=(backup_key_directory(),),
            )
            result.update(
                status="captured",
                files=copied["files"],
                links_skipped=len(copied["links"]),
                special_files_skipped=copied["special_files_skipped"],
                key_paths_excluded=copied["excluded_paths"],
            )
        elif kind != "missing":
            result.update(status="error", error="Agent Hub state is not a directory")
    except OSError:
        result.update(status="error", error="Agent Hub state is unreadable")
    _write_capture_manifest(
        destination / "manifest.json",
        {"schema_version": CAPTURE_MANIFEST_VERSION, **result},
    )
    return result


def _service_state_root() -> Path:
    configured = os.environ.get("SUMMITFLOW_SERVICE_STATE_ROOT", "").strip()
    return _absolute_path(
        Path(configured) if configured else Path.home() / ".summitflow" / "services"
    )


def _release_identity(link: Path, releases: Path) -> tuple[str | None, str | None]:
    """Return a release build identity without dereferencing its source tree."""
    try:
        mode = link.lstat().st_mode
    except FileNotFoundError:
        return None, None
    if not stat.S_ISLNK(mode):
        return None, "pointer is not a symbolic link"
    try:
        raw_target = os.readlink(link)
    except OSError:
        return None, "pointer is unreadable"
    target = Path(raw_target)
    candidate = _absolute_path(target if target.is_absolute() else link.parent / target)
    releases = _absolute_path(releases)
    if candidate.parent != releases or not candidate.name:
        return None, "pointer target is outside release storage"
    return candidate.name, None


def _capture_managed_service_state(destination: Path) -> dict[str, Any]:
    """Capture service receipts/jobs and release identities, never release trees."""
    source = _service_state_root()
    destination.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"status": "missing", "files": 0, "projects": {}}
    pointer_errors: list[str] = []
    try:
        kind = _path_kind(source)
        if kind == "directory":
            projects_root = source / "projects"
            if _path_kind(projects_root) == "directory":
                with os.scandir(projects_root) as entries:
                    projects = sorted(entries, key=lambda item: item.name)
                for entry in projects:
                    project_path = Path(entry.path)
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    project_manifest: dict[str, Any] = {}
                    releases = project_path / "releases"
                    for pointer in ("current", "previous"):
                        build_id, error = _release_identity(project_path / pointer, releases)
                        project_manifest[f"{pointer}_build"] = build_id
                        if error:
                            pointer_errors.append(f"{entry.name}:{pointer}")
                    receipts = project_path / "receipts"
                    if _path_kind(receipts) == "directory":
                        copied = _copy_regular_path(
                            receipts,
                            destination / "projects" / entry.name / "receipts",
                            excluded_roots=(backup_key_directory(),),
                        )
                        result["files"] += copied["files"]
                        project_manifest["receipt_files"] = copied["files"]
                    else:
                        project_manifest["receipt_files"] = 0
                    result["projects"][entry.name] = project_manifest

            jobs = source / "jobs"
            if _path_kind(jobs) == "directory":
                copied = _copy_regular_path(
                    jobs,
                    destination / "jobs",
                    excluded_roots=(backup_key_directory(),),
                )
                result["files"] += copied["files"]
                result["job_files"] = copied["files"]
            else:
                result["job_files"] = 0
            result["status"] = "error" if pointer_errors else "captured"
            if pointer_errors:
                result["error"] = "managed service release pointers are invalid"
                result["invalid_pointers"] = pointer_errors
        elif kind != "missing":
            result.update(status="error", error="managed service state is not a directory")
    except OSError:
        result.update(status="error", error="managed service state is unreadable")
    _write_capture_manifest(
        destination / "manifest.json",
        {"schema_version": CAPTURE_MANIFEST_VERSION, **result},
    )
    return result


def _base_config_components(configs: Path) -> dict[str, dict[str, str]]:
    """Record exact base configuration artifacts copied into private staging."""

    def regular_file_status(path: Path) -> str:
        try:
            metadata = path.lstat()
            return (
                "captured"
                if stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0
                else "missing"
            )
        except FileNotFoundError:
            return "missing"

    def populated_directory_status(path: Path) -> str:
        try:
            for candidate in path.rglob("*"):
                metadata = candidate.lstat()
                if stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0:
                    return "captured"
        except FileNotFoundError:
            pass
        return "missing"

    return {
        "env_local": {"status": regular_file_status(configs / "env.local")},
        "compose_env": {"status": regular_file_status(configs / "compose-env")},
        "smb_credentials": {
            "status": regular_file_status(configs / "smbcredentials")
        },
        "hatchet_config": {
            "status": populated_directory_status(configs / "hatchet-config")
        },
        "redis_state": {"status": regular_file_status(configs / "redis-dump.rdb")},
    }


def _capture_recovery_state(
    staging: Path,
    base_components: dict[str, dict[str, str]],
) -> dict[str, Any]:
    state = staging / "state"
    components = {
        **base_components,
        "host_ingress": _capture_host_ingress(state / "host-ingress"),
        "systemd_user": _capture_user_systemd(state / "systemd-user"),
        "agent_hub_state": _capture_agent_hub_state(state / "agent-hub"),
        "managed_service_state": _capture_managed_service_state(
            state / "managed-services"
        ),
    }
    verification_components = {
        key: {
            field: value
            for field, value in component.items()
            if field in {"status", "error", "files", "missing"}
        }
        for key, component in components.items()
    }
    manifest = {
        "schema_version": CAPTURE_MANIFEST_VERSION,
        "components": components,
    }
    _write_capture_manifest(state / "capture-manifest.json", manifest)
    return {
        "schema_version": CAPTURE_MANIFEST_VERSION,
        "components": verification_components,
    }


def _collect_redis_dump(destination: Path) -> None:
    redis_cli = shutil.which("redis-cli")
    if redis_cli:
        result = run_bulk_process([redis_cli, "-h", os.environ.get("REDIS_HOST", "localhost"), "-p", os.environ.get("REDIS_PORT", "6379"), "--rdb", str(destination)], phase="capture", object_name="Redis snapshot")
        if result.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
            return
    container = _find_compose_container("redis")
    if not container:
        return
    run_bulk_process(["docker", "exec", container, "redis-cli", "BGSAVE"], phase="capture", object_name="Redis snapshot request")
    time.sleep(2)
    with destination.open("wb") as out:
        run_bulk_process(
            ["docker", "exec", container, "cat", "/data/dump.rdb"], phase="capture", object_name="Redis snapshot",
            stdout_sink=lambda source: shutil.copyfileobj(source, out),
        )


def prepare_infrastructure_payload(
    project_dir: Path,
    staging: Path,
    *,
    host_config_root: Path | None = None,
) -> dict[str, Any]:
    """Stage infrastructure configs/state and plain SQL before archive packing."""
    backup_phase("capture")
    config_root = host_config_root or project_dir
    snapshot_dir = staging / "infrastructure-snapshot"
    configs = snapshot_dir / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    db_dump = snapshot_dir / INFRASTRUCTURE_DATABASE_PAYLOAD_NAME
    _dump_infra_database(db_dump)
    db_size = db_dump.stat().st_size
    if db_size == 0:
        raise RuntimeError("Infrastructure database dump is empty")
    _copy_if_exists(Path.home() / ".env.local", configs / "env.local")
    _copy_if_exists(config_root / "docker" / "compose" / ".env", configs / "compose-env")
    _copy_if_exists(Path.home() / ".smbcredentials", configs / "smbcredentials")
    _copy_if_exists(
        config_root / "docker" / "compose" / "hatchet-config",
        configs / "hatchet-config",
    )
    _collect_redis_dump(configs / "redis-dump.rdb")
    coverage = _capture_recovery_state(snapshot_dir, _base_config_components(configs))
    metadata = payload_tree_metadata(snapshot_dir)
    verification = {
        "verified": True, "errors": [], "has_db": True, "expects_db": True,
        "tree": metadata["tree"], "total_files": metadata["total_files"], "coverage": coverage,
    }
    return {
        **metadata, "snapshot_dir": snapshot_dir, "db_bytes": db_size,
        "files_bytes": metadata["total_bytes"] - db_size, "expects_db": True,
        "db_dump_name": INFRASTRUCTURE_DATABASE_PAYLOAD_NAME,
        "recovery": coverage, "verification": verification,
    }


def _build_infra_archive(
    project_dir: Path, staging: Path, archive_name: str,
    *, host_config_root: Path | None = None,
) -> tuple[Path, int, dict[str, Any]]:
    payload = prepare_infrastructure_payload(project_dir, staging, host_config_root=host_config_root)
    snapshot_dir = payload["snapshot_dir"]
    configs = snapshot_dir / "configs"
    db_dump = staging / INFRASTRUCTURE_DATABASE_DUMP_NAME
    db_size = _gzip_payload_file(snapshot_dir / INFRASTRUCTURE_DATABASE_PAYLOAD_NAME, db_dump)
    archive_path = staging / archive_name
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(
            db_dump,
            arcname=f"infrastructure/{INFRASTRUCTURE_DATABASE_DUMP_NAME}",
            recursive=False,
            filter=_regular_file_filter,
        )
        archive.add(
            configs,
            arcname="infrastructure/configs",
            recursive=True,
            filter=_safe_config_archive_filter,
        )
        archive.add(
            snapshot_dir / "state",
            arcname="infrastructure/state",
            recursive=True,
            filter=_safe_config_archive_filter,
        )
    verification = verify_archive(
        archive_path,
        db_dump_name=INFRASTRUCTURE_DATABASE_DUMP_NAME,
        expects_db=True,
    )
    verification["coverage"] = payload["verification"]["coverage"]
    result = {
        "archive_name": archive_name,
        "archive_path": archive_path,
        "total_bytes": archive_path.stat().st_size,
        "logical_bytes": payload["logical_bytes"],
        "db_bytes": db_size,
        "files_bytes": max(archive_path.stat().st_size - db_size, 0),
        "verification": verification,
    }
    return archive_path, db_size, result


def _finish_infra_backup(
    project_dir: Path,
    source_id: str,
    result: dict[str, Any],
    archive_path: Path,
    storage: StorageConfig,
    keep_local: bool,
    retention: int,
    run_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    archive_name = str(result["archive_name"])
    if storage_backend_type(run_env or {}) == "local":
        local_storage = local_storage_config(source_id, run_env or {})
        location = copy_to_local_backend(archive_path, archive_name, local_storage)
        if keep_local:
            local_dir = project_dir / "backups" / "infrastructure"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
            apply_local_retention(local_dir, retention)
        update_backup_index(source_id, result, "ok", location, retention)
        return {**result, "location": location}

    upload = _smb_upload(archive_path, archive_name, storage)
    if upload.ok:
        location = upload.location
        if keep_local:
            local_dir = project_dir / "backups" / "infrastructure"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
            apply_local_retention(local_dir, retention)
        update_backup_index(source_id, result, "ok", location, retention)
        return {**result, "location": location}
    logger.warning(
        "infra_backup_smb_upload_failed",
        archive=archive_name,
        remote_path=storage.remote_path,
        error=upload.error,
    )
    pending = _save_pending(archive_path, archive_name, source_id, storage)
    location = str(pending)
    update_backup_index(source_id, result, "pending", location, retention)
    return {**result, "location": location, "pending_path": location, "upload_error": upload.error}


def run_infra_backup(
    *,
    env: dict[str, str] | None = None,
    keep_local: bool = False,
    retention_days: int | None = None,
    on_progress: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Create an infrastructure backup archive."""
    source_id = "infrastructure"
    project_dir = get_repo_root()
    host_config_root = get_host_config_root()
    run_env = dict(env or {})
    storage_env = {**run_env, "SMB_PATH": run_env.get("SMB_PATH", "project-backups/infrastructure")}
    storage = _storage_config(source_id, storage_env)
    retention = retention_days or 14
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"infrastructure-{timestamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="infrastructure-backup-") as temp_dir:
        staging = Path(temp_dir)
        archive_path, _, result = _build_infra_archive(
            project_dir,
            staging,
            archive_name,
            host_config_root=host_config_root,
        )
        archive_path.chmod(0o600)
        encrypted_name = f"{archive_name}.age"
        encrypted_path = staging / encrypted_name
        encryption = encrypt_completed_archive(archive_path, encrypted_path, run_env)
        verification = dict(result["verification"])
        verification.update(
            {
                "checksum": encryption["checksum"],
                "content_checksum": encryption["content_checksum"],
                "encrypted": True,
                "encryption": {"duration_ms": encryption.get("duration_ms")},
            }
        )
        result.update(
            {
                "archive_name": encrypted_name,
                "archive_path": encrypted_path,
                "content_bytes": result["total_bytes"],
                "total_bytes": encryption["encrypted_bytes"],
                "verification": verification,
            }
        )
        offsite_configured = bool(
            run_env.get("BACKUP_OFFSITE_GIO_URI")
            or os.environ.get("BACKUP_OFFSITE_GIO_URI")
        )
        backend_type = storage_backend_type(run_env)
        local_dir = project_dir / "backups" / "infrastructure"
        if offsite_configured and backend_type != "local":
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(encrypted_path, local_dir / encrypted_name)
            apply_local_retention(local_dir, retention)
        backup_phase("local-storage")
        stored = _finish_infra_backup(
            project_dir,
            source_id,
            result,
            encrypted_path,
            storage,
            keep_local and not offsite_configured,
            retention,
            run_env=run_env,
        )
        if offsite_configured:
            record_local_archive(stored)
            replica_source = (
                Path(str(stored["location"]))
                if backend_type == "local"
                else local_dir / encrypted_name
            )
            offsite = replicate_completed_archive(
                replica_source,
                source_id=source_id,
                local_dir=replica_source.parent,
                env=run_env,
                retention_days=retention,
                on_progress=on_progress,
            )
            stored_verification = dict(stored["verification"])
            activity = current_activity()
            if activity:
                activity.record_offsite_result(offsite)
            stored_verification["offsite"] = offsite
            stored["verification"] = stored_verification
        return stored
