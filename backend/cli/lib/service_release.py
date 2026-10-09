"""Stable source materialization and durable evidence for managed services."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ReleaseError(RuntimeError):
    """Raised when a stable release cannot be prepared or recorded safely."""


@dataclass(frozen=True)
class AcceptedSource:
    """Validated acceptance identity consumed by deployment."""

    acceptance_id: str
    source_commit: str
    source_tree: str
    acceptance_artifact: str = ""
    input_fingerprint: str = ""
    acceptance_plan_fingerprint: str = ""
    scope: tuple[str, ...] = ()
    task_id: str = ""
    checks: Any = None
    check_count: int = 0
    duration_ms: float | None = None
    output_bytes: int = 0
    started_at: Any = None
    completed_at: Any = None
    reused: bool = False
    reuse_lookup_ms: float | None = None
    coverage: str | None = None

    @classmethod
    def from_descriptor(
        cls, descriptor: Mapping[str, Any], *, require_full: bool = False
    ) -> AcceptedSource:
        coverage = descriptor.get("coverage")
        # Older retained deployment records omitted coverage. New releases must
        # carry the canonical full proof; explicit task evidence is never a release.
        if (require_full or coverage is not None) and coverage != "full":
            raise ReleaseError(
                f"Managed releases require full acceptance coverage (received {coverage or 'unknown'})"
            )
        try:
            source = cls(
                acceptance_id=str(descriptor["acceptance_id"]),
                source_commit=str(descriptor["source_commit"]),
                source_tree=str(descriptor["source_tree"]),
                acceptance_artifact=str(descriptor.get("acceptance_artifact") or ""),
                input_fingerprint=str(descriptor.get("input_fingerprint") or ""),
                acceptance_plan_fingerprint=str(
                    descriptor.get("acceptance_plan_fingerprint") or ""
                ),
                scope=tuple(str(item) for item in descriptor.get("scope", ())),
                task_id=str(descriptor.get("task_id") or ""),
                checks=descriptor.get("checks"),
                check_count=int(descriptor.get("check_count") or 0),
                duration_ms=(
                    float(descriptor["duration_ms"])
                    if descriptor.get("duration_ms") is not None
                    else None
                ),
                output_bytes=int(descriptor.get("output_bytes") or 0),
                started_at=descriptor.get("started_at"),
                completed_at=descriptor.get("completed_at"),
                reused=bool(descriptor.get("reused", False)),
                reuse_lookup_ms=(
                    float(descriptor["reuse_lookup_ms"])
                    if descriptor.get("reuse_lookup_ms") is not None
                    else None
                ),
                coverage=coverage,
            )
        except KeyError as exc:
            raise ReleaseError(f"Accepted source is missing {exc.args[0]}") from None
        except (TypeError, ValueError) as exc:
            raise ReleaseError("Accepted source identity is invalid") from exc
        if not source.acceptance_id or not source.source_commit or not source.source_tree:
            raise ReleaseError("Accepted source identity is incomplete")
        return source

    def evidence(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreparedRelease:
    project_id: str
    build_id: str
    source: AcceptedSource
    release_root: Path
    source_root: Path
    receipt_path: Path


def service_state_root() -> Path:
    """Return the configurable service state root outside development checkouts."""
    configured = os.environ.get("SUMMITFLOW_SERVICE_STATE_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".summitflow" / "services"


def _safe_project_id(project_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in project_id)
    safe = safe.strip("-")
    if not safe:
        raise ReleaseError("Invalid managed project id")
    return safe


def _project_state(project_id: str, state_root: Path | None = None) -> Path:
    return (state_root or service_state_root()) / "projects" / _safe_project_id(project_id)


def jobs_root(state_root: Path | None = None) -> Path:
    return (state_root or service_state_root()) / "jobs"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        json.dump(value, temporary, sort_keys=True)
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
    os.replace(temporary.name, path)


def _receipt_id(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("deployment_id", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_receipt(path: Path, value: Mapping[str, Any]) -> None:
    sealed = dict(value)
    sealed["deployment_id"] = _receipt_id(sealed)
    _write_json(path, sealed)


def _read_receipt(release: PreparedRelease) -> dict[str, Any]:
    try:
        value = json.loads(release.receipt_path.read_text())
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"Release receipt unavailable: {release.build_id}") from exc
    if not isinstance(value, dict) or value.get("build_id") != release.build_id:
        raise ReleaseError(f"Release receipt identity mismatch: {release.build_id}")
    if value.get("deployment_id") != _receipt_id(value):
        raise ReleaseError(f"Release receipt integrity mismatch: {release.build_id}")
    return value


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError("Accepted source Git object is unavailable")
    return result.stdout.strip()


def _current_build(project_state: Path) -> str | None:
    current = project_state / "current"
    if not current.is_symlink():
        return None
    try:
        target = current.resolve(strict=True)
    except OSError:
        return None
    if target.parent != project_state / "releases":
        raise ReleaseError("Managed current release points outside the release root")
    return target.name


def current_source_root(
    project_id: str, *, state_root: Path | None = None
) -> Path | None:
    """Resolve the last health-verified managed source without consulting a checkout."""
    project_state = _project_state(project_id, state_root)
    build_id = _current_build(project_state)
    if build_id is None:
        return None
    source_root = project_state / "releases" / build_id / "source"
    if not source_root.is_dir():
        raise ReleaseError("Current managed release source is unavailable")
    return source_root


def _materialize_release(
    project_id: str,
    repo: Path,
    source: AcceptedSource | Mapping[str, Any],
    *,
    state_root: Path | None = None,
) -> PreparedRelease:
    """Materialize the exact accepted Git tree into a new stable release."""
    accepted = AcceptedSource.from_descriptor(
        source.evidence() if isinstance(source, AcceptedSource) else source
    )
    commit = _git(repo, "rev-parse", "--verify", f"{accepted.source_commit}^{{commit}}")
    if commit != accepted.source_commit:
        raise ReleaseError("Accepted source commit identity mismatch")
    tree = _git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}")
    if tree != accepted.source_tree:
        raise ReleaseError("Accepted source tree identity mismatch")

    project_state = _project_state(project_id, state_root)
    try:
        project_state.resolve().relative_to(repo.resolve(strict=True))
    except ValueError:
        pass
    except OSError as exc:
        raise ReleaseError("Development checkout is unavailable") from exc
    else:
        raise ReleaseError("Service state root must be outside the development checkout")
    releases = project_state / "releases"
    receipts = project_state / "receipts"
    releases.mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True, exist_ok=True)
    build_id = uuid.uuid4().hex
    release_root = releases / build_id
    receipt_path = receipts / f"{build_id}.json"
    staging = Path(tempfile.mkdtemp(prefix=f".{build_id}-", dir=releases))
    archive_path = staging / ".accepted-source.tar"
    source_root = staging / "source"
    source_root.mkdir()
    try:
        result = subprocess.run(
            ["git", "archive", "--format=tar", "--output", str(archive_path), commit],
            cwd=repo,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise ReleaseError("Accepted source could not be archived")
        with tarfile.open(archive_path) as archive:
            archive.extractall(source_root, filter="data")
        archive_path.unlink()
        os.replace(staging, release_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    prepared = PreparedRelease(
        project_id=project_id,
        build_id=build_id,
        source=accepted,
        release_root=release_root,
        source_root=release_root / "source",
        receipt_path=receipt_path,
    )
    _write_receipt(
        receipt_path,
        {
            "schema_version": 1,
            "project": project_id,
            "build_id": build_id,
            "deployment_artifact": str(receipt_path),
            "state": "prepared",
            "source": accepted.evidence(),
            "source_root": str(prepared.source_root),
            "previous_usable_release": _current_build(project_state),
            "migrations": "not_started",
            "events": [
                {"phase": "prepared", "status": "succeeded", "at": time.time()}
            ],
        },
    )
    return prepared


def prepare_release(
    project_id: str,
    repo: Path,
    source: Mapping[str, Any] | Path,
    *,
    state_root: Path | None = None,
) -> PreparedRelease:
    """Validate a receipt and materialize its commit/tree under the shared repo lock."""
    from . import acceptance

    with acceptance.repo_lock(repo, purpose="deployment"):
        descriptor = acceptance.validate_acceptance_receipt(repo, source)
        AcceptedSource.from_descriptor(descriptor, require_full=True)
        if not isinstance(source, Path):
            descriptor = {
                **descriptor,
                "reused": bool(source.get("reused", False)),
                "reuse_lookup_ms": source.get("reuse_lookup_ms"),
            }
        if isinstance(source, Path) and not descriptor.get("acceptance_artifact"):
            descriptor = {**descriptor, "acceptance_artifact": str(source)}
        return _materialize_release(
            project_id, repo, descriptor, state_root=state_root
        )


def mark_phase(
    release: PreparedRelease, phase: str, *, status: str, **evidence: Any
) -> None:
    receipt = _read_receipt(release)
    receipt["events"].append(
        {"phase": phase, "status": status, "at": time.time(), **evidence}
    )
    if phase == "migrations":
        receipt["migrations"] = status
    _write_receipt(release.receipt_path, receipt)


def fail_release(
    release: PreparedRelease,
    failed_phase: str,
    *,
    migrations: str | None = None,
) -> None:
    receipt = _read_receipt(release)
    receipt.update(state="failed", failed_phase=failed_phase, completed_at=time.time())
    if migrations is not None:
        receipt["migrations"] = migrations
    if not receipt["events"] or (
        receipt["events"][-1].get("phase"), receipt["events"][-1].get("status")
    ) != (failed_phase, "failed"):
        receipt["events"].append(
            {"phase": failed_phase, "status": "failed", "at": time.time()}
        )
    _write_receipt(release.receipt_path, receipt)


def previous_source_root(release: PreparedRelease) -> Path | None:
    """Return the retained prior source tree, if one was successfully activated."""
    receipt = _read_receipt(release)
    build_id = receipt.get("previous_usable_release")
    if not isinstance(build_id, str) or not build_id:
        return None
    source_root = release.release_root.parent / build_id / "source"
    try:
        source_root.resolve(strict=True).relative_to(release.release_root.parent)
    except (OSError, ValueError) as exc:
        raise ReleaseError("Previous usable release is unavailable") from exc
    return source_root


def _replace_symlink(path: Path, target: Path) -> None:
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    temporary.symlink_to(target)
    os.replace(temporary, path)


def _pointer_release(path: Path, releases: Path) -> Path | None:
    if not path.is_symlink():
        if path.exists():
            raise ReleaseError(f"Managed release pointer is not a symlink: {path.name}")
        return None
    try:
        raw_target = Path(os.readlink(path))
        target = path.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError(f"Managed release pointer is unavailable: {path.name}") from exc
    entry_name = raw_target.name
    entry = releases / entry_name
    try:
        resolved_entry = entry.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError(f"Managed release pointer is unavailable: {path.name}") from exc
    if (
        target.parent != releases
        or target != resolved_entry
        or entry.is_symlink()
        or not entry.is_dir()
        or not re.fullmatch(r"[0-9a-f]{32}", entry_name)
    ):
        raise ReleaseError(f"Managed release pointer leaves the release root: {path.name}")
    return target


def prune_old_releases(
    release: PreparedRelease, *, service_references: set[Path] | None
) -> tuple[Path, ...]:
    """Remove only validated, rebuildable releases unused by pointers or services."""
    if service_references is None:
        print("[service] release cleanup skipped: service references are unavailable")
        return ()
    releases = release.release_root.parent
    project_state = releases.parent
    try:
        resolved_releases = releases.resolve(strict=True)
        resolved_release = release.release_root.resolve(strict=True)
        if (
            resolved_release.parent != resolved_releases
            or resolved_release.name != release.build_id
            or not re.fullmatch(r"[0-9a-f]{32}", release.build_id)
        ):
            raise ReleaseError("Completed release path is outside managed release storage")
        protected = {resolved_release}
        for pointer_name in ("current", "previous"):
            target = _pointer_release(project_state / pointer_name, resolved_releases)
            if target is not None:
                protected.add(target)
        for reference in service_references:
            if reference.is_symlink():
                raise ReleaseError("Service release reference is not a real directory")
            resolved = reference.resolve(strict=True)
            if (
                resolved.parent != resolved_releases
                or not resolved.is_dir()
                or resolved.is_symlink()
                or not re.fullmatch(r"[0-9a-f]{32}", resolved.name)
            ):
                raise ReleaseError("Service release reference is outside managed release storage")
            protected.add(resolved)
        candidates: list[Path] = []
        for entry in releases.iterdir():
            if not re.fullmatch(r"[0-9a-f]{32}", entry.name):
                continue
            if entry.is_symlink() or not entry.is_dir():
                raise ReleaseError("Managed release entry is not a real directory")
            resolved = entry.resolve(strict=True)
            if resolved.parent != resolved_releases:
                raise ReleaseError("Managed release entry leaves release storage")
            if resolved not in protected:
                candidates.append(resolved)
    except (OSError, ReleaseError) as exc:
        print(f"[service] release cleanup skipped: {exc}")
        return ()

    removed: list[Path] = []
    for candidate in sorted(candidates):
        try:
            shutil.rmtree(candidate)
        except OSError as exc:
            print(f"[service] release cleanup stopped: {candidate.name}: {exc}")
            break
        print(f"[service] removed rebuildable release {candidate.name}")
        removed.append(candidate)
    return tuple(removed)


def complete_release(
    release: PreparedRelease, *, service_references: set[Path] | None = None
) -> None:
    """Mark health-verified source current while retaining the prior release."""
    receipt = _read_receipt(release)
    project_state = _project_state(release.project_id, release.release_root.parents[3])
    current = project_state / "current"
    previous = project_state / "previous"
    releases = project_state / "releases"
    old_target = _pointer_release(current, releases)
    _pointer_release(previous, releases)
    if old_target is not None:
        _replace_symlink(previous, old_target)
        receipt["previous_usable_release"] = old_target.name
    _replace_symlink(current, release.release_root)
    receipt.update(state="succeeded", completed_at=time.time())
    receipt["events"].append(
        {"phase": "completed", "status": "succeeded", "at": time.time()}
    )
    _write_receipt(release.receipt_path, receipt)
    prune_old_releases(release, service_references=service_references)


def validate_deployment_receipt(
    receipt: Mapping[str, Any] | Path,
    *,
    require_success: bool = True,
    project_root: Path | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    """Load and authenticate deployment evidence for task closeout."""
    artifact = str(receipt) if isinstance(receipt, Path) else ""
    if isinstance(receipt, Path):
        try:
            value = json.loads(receipt.read_text())
        except (OSError, ValueError) as exc:
            raise ReleaseError(f"Deployment receipt unavailable: {receipt}") from exc
    else:
        value = dict(receipt)
    if not isinstance(value, dict) or value.get("deployment_id") != _receipt_id(value):
        raise ReleaseError("Deployment receipt identity mismatch")
    source = value.get("source")
    if not isinstance(source, dict):
        raise ReleaseError("Deployment receipt has no accepted source")
    accepted = AcceptedSource.from_descriptor(source)
    state = str(value.get("state") or "")
    if require_success and state != "succeeded":
        raise ReleaseError("Deployment receipt is not successful")
    events = value.get("events")
    if not isinstance(events, list):
        raise ReleaseError("Deployment receipt has no lifecycle evidence")
    if require_success:
        required = {
            "backend_dependencies",
            "frontend_build",
            "systemd_units",
            "restart",
            "health",
            "seeds",
            "completed",
        }
        succeeded = {
            event.get("phase")
            for event in events
            if isinstance(event, dict) and event.get("status") == "succeeded"
        }
        failed = {
            event.get("phase")
            for event in events
            if isinstance(event, dict) and event.get("status") == "failed"
        }
        if required - succeeded or required & failed:
            raise ReleaseError("Deployment receipt is missing successful lifecycle evidence")
        if value.get("migrations") not in {"succeeded", "not_applicable"}:
            raise ReleaseError("Deployment receipt has no successful migration evidence")
    if source_commit is not None and accepted.source_commit != source_commit:
        raise ReleaseError("Deployment receipt source commit mismatch")
    deployed_source = Path(str(value.get("source_root") or ""))
    if project_root is not None:
        try:
            deployed_source.resolve(strict=True).relative_to(project_root.resolve(strict=True))
        except ValueError:
            pass
        except OSError as exc:
            raise ReleaseError("Deployed source root is unavailable") from exc
        else:
            raise ReleaseError("Deployment receipt points into the development checkout")
    return {
        "state": state,
        "deployment_id": value["deployment_id"],
        "artifact": artifact or str(value.get("deployment_artifact") or ""),
        "project": str(value.get("project") or ""),
        "build_id": str(value.get("build_id") or ""),
        "acceptance_id": accepted.acceptance_id,
        "source_commit": accepted.source_commit,
        "source_tree": accepted.source_tree,
        "coverage": accepted.coverage,
        "migrations": str(value.get("migrations") or ""),
        "events": events,
        "source_root": str(deployed_source),
    }


def publish_deployment_result(
    release: PreparedRelease,
    *,
    project_root: Path,
    result_path: Path | None = None,
) -> dict[str, Any]:
    """Expose canonical evidence to normal output and a detached job result file."""
    result = validate_deployment_receipt(
        release.receipt_path,
        project_root=project_root,
        source_commit=release.source.source_commit,
    )
    destination = result_path
    if destination is None and os.environ.get("SUMMITFLOW_DEPLOYMENT_RESULT"):
        destination = Path(os.environ["SUMMITFLOW_DEPLOYMENT_RESULT"])
    if destination is not None:
        _write_json(destination, _read_receipt(release))
    return result


@contextmanager
def deployment_lock(
    project_id: str, *, state_root: Path | None = None
) -> Iterator[None]:
    """Prevent foreground and detached rebuilds from overlapping per project."""
    project_state = _project_state(project_id, state_root)
    project_state.mkdir(parents=True, exist_ok=True)
    path = project_state / "deployment.lock"
    with path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseError(
                f"Managed deployment already in progress for {project_id}"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
