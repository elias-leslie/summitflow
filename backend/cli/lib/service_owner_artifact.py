"""Transfer agent-built accepted portable runtimes into private owner releases."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.utils import safe_subprocess
from app.utils.heavy_work import heavy_work

from . import acceptance, service_ops
from . import service_release as releases
from .workspace_paths import get_workspaces_root


def exchange_root() -> Path:
    return get_workspaces_root() / "exchange" / "agent" / "service-artifacts"


def initialize_owner_store(project_id: str) -> None:
    """Let the configured owner import future agent exports, including umask 077."""
    from app.services.tether import _agent_uid

    from .service_owner_runtime import CONFIG, _trusted_json

    agent_uid = _agent_uid()
    if os.getuid() != agent_uid:
        return
    config = _trusted_json(CONFIG)
    owner_uid = config.get("owner_uid")
    if project_id not in config.get("projects", {}) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project_id):
        raise ValueError("Project is not registered for owner actions")
    if type(owner_uid) is not int or owner_uid <= 0 or owner_uid == agent_uid:
        raise ValueError("Installed owner artifact identity is invalid")
    executable = shutil.which("setfacl")
    if not executable:
        raise OSError("Owner artifact sharing requires the installed setfacl tool")
    root = exchange_root()
    for directory in (root, root / project_id):
        with suppress(FileExistsError):
            directory.mkdir(mode=0o700)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != agent_uid:
            raise ValueError(f"Owner artifact store must be an agent-owned directory without symlinks: {directory}")
        result = safe_subprocess.run([executable, "--modify", f"u:{owner_uid}:r-x,d:u:{owner_uid}:r-x", str(directory)],
                                     capture_output=True, text=True, check=False)
        if result.returncode:
            raise OSError(f"Could not grant owner read access to artifact store: {directory}")


def portable(project: service_ops.ProjectServices) -> None:
    """Require a locked Python backend or the existing portable Node runtime."""
    python = _python_backend(project)
    if not python and not (project.frontend_dir / "package.json").is_file():
        raise ValueError("Owner artifact import requires a portable Node project or locked Python backend")
    if project.release_install:
        raise ValueError("Owner artifact import does not support release installers")


def _python_backend(project: service_ops.ProjectServices) -> bool:
    python = False
    for directory in {project.root, project.backend_dir}:
        manifest = directory / "pyproject.toml"
        test_only = False
        if manifest.is_file():
            parsed = tomllib.loads(manifest.read_text())
            test_only = (parsed.get("tool", {}).get("uv", {}).get("package") is False
                         and not parsed.get("project", {}).get("dependencies"))
        if (any((directory / name).exists() for name in ("requirements.txt", "alembic.ini"))
                or (manifest.exists() and not test_only)
                or ((directory / ".venv").exists() and not test_only)):
            if directory != project.backend_dir or not manifest.is_file() or not (directory / "uv.lock").is_file():
                raise ValueError("Owner Python artifacts require pyproject.toml and uv.lock in the configured backend")
            python = True
    return python


def _internal_links(root: Path, *, original: Path | None = None) -> None:
    """Rebase interpreter links; reject payload links the tar data filter cannot retain."""
    root = root.resolve(strict=True)
    paths = list(root.rglob("*"))
    # Rebase the whole prefix before resolving chains of interpreter links.
    if original is not None:
        for path in paths:
            if path.is_symlink():
                target = Path(os.readlink(path))
                if target.is_absolute() and target.is_relative_to(original):
                    path.unlink()
                    path.symlink_to(os.path.relpath(root / target.relative_to(original), path.parent))
    for path in paths:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            if Path(os.readlink(path)).is_absolute() or not path.resolve(strict=True).is_relative_to(root):
                raise ValueError(f"Python artifact has an external symlink: {path.relative_to(root)}")
        elif not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"Python artifact has an unsupported file: {path.relative_to(root)}")


def _prepare_python(project: service_ops.ProjectServices) -> int:
    """Build with uv's relocatable launchers and an unchanged, private Python prefix."""
    with heavy_work("accepted Python artifact", project=project.project_id):
        return _build_python(project)


def _build_python(project: service_ops.ProjectServices) -> int:
    declared = service_ops.backend_optional_dependencies(project.backend_dir)
    if declared is None or set(project.backend_extras) - set(declared):
        raise ValueError("Owner Python artifact backend extras must be declared in its locked manifest")
    prefix = Path(sys.base_prefix).resolve(strict=True)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    executable = prefix / "bin" / version
    if not executable.is_file() or executable.is_symlink():
        raise ValueError("Owner Python artifact requires a complete standalone ELF Python interpreter")
    with executable.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ValueError("Owner Python artifact requires a complete standalone ELF Python interpreter")
    if (not (prefix / "lib" / version / "encodings/__init__.py").is_file()
            or not (prefix / "lib" / f"lib{version}.so.1.0").is_file()):
        raise ValueError("Owner Python artifact requires a complete standalone Python prefix")
    bundled = project.backend_dir / ".python"
    environment = project.backend_dir / ".venv"
    if bundled.exists() or bundled.is_symlink() or environment.exists() or environment.is_symlink():
        raise ValueError("Owner Python artifact build must start without .python or .venv")
    shutil.copytree(prefix, bundled, symlinks=True)
    _internal_links(bundled, original=prefix)
    interpreter = bundled / "bin" / version
    env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(environment), UV_PYTHON_DOWNLOADS="never",
               UV_PYTHON=str(interpreter), UV_LINK_MODE="copy", UV_VENV_RELOCATABLE="true")
    commands = [["uv", "venv", "--relocatable", "--no-python-downloads", "--python", str(interpreter), str(environment)],
                [*service_ops.locked_backend_sync_command(declared, project.backend_extras),
                 "--no-editable", "--link-mode", "copy", "--python", str(interpreter)]]
    for command in commands:
        code = service_ops.run(command, cwd=project.backend_dir, env=env, quiet_success=True, _heavy=True)
        if code:
            return code
    # uv creates absolute interpreter links even with --relocatable. Keep their
    # unchanged targets in the bundle using relative links accepted by tar's data filter.
    for path in (environment / "bin").iterdir():
        if path.is_symlink() and Path(os.readlink(path)).is_absolute():
            target = path.resolve(strict=True)
            if not target.is_relative_to(bundled):
                raise ValueError("Python environment interpreter is outside its bundled prefix")
            path.unlink()
            path.symlink_to(os.path.relpath(target, path.parent))
    _internal_links(project.backend_dir)
    site = environment / "lib" / version / "site-packages"
    for direct_url in site.glob("*.dist-info/direct_url.json"):
        if json.loads(direct_url.read_text()).get("dir_info", {}).get("editable"):
            raise ValueError("Python artifact contains an editable install")
    if any("editable" in path.name.lower() for path in site.glob("*.pth")):
        raise ValueError("Python artifact contains an editable install")
    with tempfile.TemporaryDirectory(prefix=".python-relocation-", dir=project.root.parent) as directory:
        temporary = Path(directory)
        relocated = temporary / "source"
        home = temporary / "home"
        home.mkdir()
        backend = project.backend_dir.relative_to(project.root)
        project.root.rename(relocated)
        try:
            # Assert the moved copy supplies the interpreter and standard library,
            # even while the original tool/cached interpreter is still installed.
            return service_ops.run([str(relocated / backend / ".venv/bin/python"), "-I", "-c",
                "import pathlib, ssl, sqlite3, sys, sysconfig; "
                "root = pathlib.Path(sys.argv[1]).resolve(); "
                "assert pathlib.Path(sys.base_prefix).resolve() == root; "
                "assert pathlib.Path(sysconfig.get_path('stdlib')).resolve().is_relative_to(root)",
                str(relocated / backend / ".python")], cwd=home,
                env={"HOME": str(home), "PATH": os.defpath, "LANG": "C.UTF-8"},
                quiet_success=True, _heavy=True)
        finally:
            relocated.rename(project.root)


def prepare(project_id: str, *, sha: str, build_id: str, tool_revision: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", build_id) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid owner artifact identity")
    project = service_ops.load_project(project_id)
    portable(project)
    with releases.deployment_lock(project_id):
        release, built = service_ops.prepare_accepted_release(project)
        if release.source.source_commit != sha:
            raise ValueError("Accepted artifact source does not match requested commit")
        portable(built)
        tracked_names = set(acceptance._source_tree_entries(project.git_root, sha))
        python = _python_backend(built)
        for name, work in (("backend_dependencies", _prepare_python if python else service_ops.sync_backend),
                           ("frontend_build", service_ops.build_frontend)):
            try:
                code = work(built)
            except Exception:
                releases.fail_release(release, name)
                raise
            if code != 0:
                releases.fail_release(release, name)
                raise ValueError(f"Agent artifact preparation failed: {name}")
            releases.mark_phase(release, name, status="succeeded")
        if project_id == "aico" and not all((built.root / path).is_file() for path in (
            "out/main/index.js", "out/preload/index.cjs", "out/renderer/index.html", "node_modules/electron/dist/electron")):
            raise ValueError("Aico artifact is missing its prebuilt runtime")
        destination = exchange_root() / project_id / build_id
        destination.mkdir(parents=True, exist_ok=False)
        archive_path = destination / "runtime.tar"
        with tarfile.open(archive_path, "w") as archive:
            def portable_member(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
                parts = Path(member.name).parts
                if any(part in {".git", "__pycache__", ".env"} for part in parts):
                    return None
                if ".venv" in parts and (not python or not Path(member.name).is_relative_to(
                        Path("source") / built.backend_dir.relative_to(built.root) / ".venv")):
                    return None
                if any(part.startswith(".env.") for part in parts) and member.name.removeprefix("source/") not in tracked_names:
                    return None
                return member
            archive.add(built.root, arcname="source", recursive=True, filter=portable_member)
        descriptor = {"schema": 1, "project": project_id, "build_id": build_id,
                      "source": release.source.evidence(), "tool_revision": tool_revision,
                      "built_phases": ["backend_dependencies", "frontend_build"], "agent_build_id": release.build_id,
                      "archive_sha256": digest(archive_path), "archive_size": archive_path.stat().st_size}
        releases._write_json(destination / "artifact.json", descriptor)
        return descriptor


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(descriptor: dict[str, Any], *, project_id: str, sha: str, build_id: str,
             tool_revision: str) -> releases.AcceptedSource:
    if (descriptor.get("schema") != 1 or descriptor.get("project") != project_id
            or descriptor.get("build_id") != build_id or descriptor.get("tool_revision") != tool_revision
            or not re.fullmatch(r"[0-9a-f]{32}", build_id)):
        raise ValueError("Owner artifact identity mismatch")
    if descriptor.get("built_phases") != ["backend_dependencies", "frontend_build"]:
        raise ValueError("Owner artifact has no successful agent build evidence")
    source = releases.AcceptedSource.from_descriptor(descriptor["source"], require_full=True)
    if not re.fullmatch(r"[0-9a-f]{64}", source.acceptance_id):
        raise ValueError("Owner artifact acceptance identity is invalid")
    if source.source_commit != sha or not re.fullmatch(r"[0-9a-f]{40}", source.source_tree):
        raise ValueError("Owner artifact source mismatch")
    if (not isinstance(descriptor.get("archive_size"), int) or descriptor["archive_size"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(descriptor.get("archive_sha256")))):
        raise ValueError("Owner artifact archive identity is invalid")
    return source


def import_artifact(descriptor: dict[str, Any], *, project_id: str, sha: str,
                    build_id: str, tool_revision: str, tracked: dict[str, tuple[str, str]]) -> releases.PreparedRelease:
    source = validate(descriptor, project_id=project_id, sha=sha, build_id=build_id, tool_revision=tool_revision)
    archive_path = exchange_root() / project_id / build_id / "runtime.tar"
    state = releases._project_state(project_id)
    release_root = state / "releases" / build_id
    release_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{build_id}-", dir=release_root.parent))
    try:
        # Copy once to owner storage, then validate and extract those exact bytes.
        local_archive = staging / "runtime.tar"
        with archive_path.open("rb") as incoming, local_archive.open("xb") as output:
            remaining = descriptor["archive_size"]
            while remaining:
                chunk = incoming.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Owner artifact archive size mismatch")
                output.write(chunk)
                remaining -= len(chunk)
            if incoming.read(1):
                raise ValueError("Owner artifact archive size mismatch")
        if digest(local_archive) != descriptor["archive_sha256"]:
            raise ValueError("Owner artifact archive digest mismatch")
        with tarfile.open(local_archive) as archive:
            for member in archive.getmembers():
                if member.name != "source" and not member.name.startswith("source/"):
                    raise ValueError("Owner artifact contains an unexpected entry")
            archive.extractall(staging, filter="data")
        verify_tracked(staging / "source", tracked)
        local_archive.unlink()
        if release_root.exists():
            raise ValueError("Owner artifact build already exists")
        os.rename(staging, release_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    release = releases.PreparedRelease(project_id, build_id, source, release_root, release_root / "source",
                                       state / "receipts" / f"{build_id}.json")
    releases._write_receipt(release.receipt_path, {
        "schema_version": 1, "project": project_id, "build_id": build_id,
        "deployment_artifact": str(release.receipt_path), "state": "prepared", "source": source.evidence(),
        "source_root": str(release.source_root), "previous_usable_release": releases._current_build(state),
        "migrations": "not_started", "artifact": descriptor,
        "events": [{"phase": phase, "status": "succeeded", "at": time.time()}
                   for phase in ("imported", *descriptor["built_phases"])]})
    return release


def verify_tracked(root: Path, tracked: dict[str, tuple[str, str]]) -> None:
    """Compare private imported source with the canonical accepted Git blobs."""
    if not tracked:
        raise ValueError("Accepted tracked source identity is unavailable")
    materialized = acceptance._materialized_source_entries(root, sorted(tracked))
    for name, (mode, oid) in tracked.items():
        path = root / name
        info = materialized[name]
        if mode in {"100644", "100755"}:
            valid = (info["kind"] == "regular" and bool(info["mode"] & 0o111) == (mode == "100755")
                     and acceptance._matches_git_blob(path, oid))
        elif mode == "120000":
            data = os.fsencode(os.readlink(path)) if info["kind"] == "symlink" else b""
            valid = (info["kind"] == "symlink" and hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == oid)
        else:
            valid = False
        if not valid:
            raise ValueError(f"Imported tracked source differs from accepted commit: {name}")


def run_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Invoked only via the same pinned tool under the configured agent UID."""
    project = service_ops.load_project(payload["project"])
    descriptor = payload["descriptor"]
    source = validate(descriptor, project_id=project.project_id, sha=descriptor["source"]["source_commit"],
                      build_id=descriptor["build_id"], tool_revision=descriptor["tool_revision"])
    if payload["operation"] == "validate":
        receipt = acceptance.acceptance_artifact_directory(project.git_root) / f"{source.acceptance_id}.json"
        canonical = acceptance.validate_acceptance_receipt(project.git_root, receipt, sha=source.source_commit)
        releases.AcceptedSource.from_descriptor(canonical, require_full=True)
        return {"source": canonical, "tracked": acceptance._source_tree_entries(project.git_root, source.source_commit)}
    if payload["operation"] == "cleanup":
        directory = exchange_root() / project.project_id / descriptor["build_id"]
        for name in ("runtime.tar", "artifact.json"):
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()
        staging_id = descriptor.get("agent_build_id", "")
        if re.fullmatch(r"[0-9a-f]{32}", staging_id):
            state = releases._project_state(project.project_id)
            release = releases.PreparedRelease(project.project_id, staging_id, source,
                state / "releases" / staging_id, state / "releases" / staging_id / "source",
                state / "receipts" / f"{staging_id}.json")
            retained = releases._read_receipt(release)
            if (retained.get("state") == "prepared" and retained["source"]["source_commit"] == source.source_commit
                    and staging_id not in {releases._current_build(state),
                        (state / "previous").resolve().name if (state / "previous").is_symlink() else None}):
                shutil.rmtree(release.release_root)
                release.receipt_path.unlink()
        return {"cleaned": True}
    raise ValueError("Unknown owner artifact job")
