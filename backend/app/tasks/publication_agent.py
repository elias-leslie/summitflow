"""Export source objects as agent; publish only from an independent private copy."""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ..services import tether
from ..utils import safe_subprocess
from ..utils.agent_jobs import run_installed_agent_job
from ..utils.transient_scratch import (
    disposable_scratch,
    ensure_scratch_capacity,
    scratch_subprocess_env,
)

logger = logging.getLogger(__name__)
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def source_job(project: Path, operation: str, **payload: Any) -> dict[str, Any]:
    return run_installed_agent_job(__name__, {"operation": operation, "project": str(project.absolute()), **payload},
                                   project=project)


def _handoff_directory(project: Path, transfer_id: str) -> Path:
    if str(UUID(transfer_id)) != transfer_id:
        raise ValueError("Invalid publication transfer identifier")
    marker = project / ".git"
    if marker.is_dir():
        git_dir = marker.resolve()
    else:
        descriptor = os.open(marker, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise RuntimeError("Publication Git metadata must be a directory or regular gitfile")
            value = source.read(4097)
        if len(value) > 4096 or not value.startswith(b"gitdir: "):
            raise RuntimeError("Unable to locate publication transfer")
        git_dir = (project / os.fsdecode(value[8:].strip())).resolve()
    return git_dir / "st" / "publication-transfer" / transfer_id


def _environment() -> dict[str, str]:
    environment = {key: value for key, value in scratch_subprocess_env().items() if not key.startswith("GIT_")}
    environment.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    return environment


@contextmanager
def independent_repository(project: Path, head: str) -> Iterator[Path]:
    """Only regular pack bytes cross identities; no source Git is run as owner."""
    from .backup_native_recovery import _open_metadata_directory

    transfer_id = str(uuid4())
    handoff = _handoff_directory(project, transfer_id)
    try:
        result = source_job(project, "export", transfer_id=transfer_id, head=head)
        object_format = "sha1" if len(head) == 40 else "sha256"
        if result != {"ready": True, "transfer_id": transfer_id, "object_format": object_format}:
            raise RuntimeError("Invalid publication export")
        with disposable_scratch("publication-") as temporary:
            repo = temporary / "repository"
            # --template= prevents owner templates from introducing hooks or
            # alternates; no checkout config or object directory is copied.
            safe_subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "init", "--quiet", "--template=",
                                 f"--object-format={object_format}", str(repo)],
                                env=_environment(), capture_output=True, check=True, timeout=30)
            safe_subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", "/dev/null"],
                                env=_environment(), capture_output=True, check=True, timeout=30)
            parent = _open_metadata_directory(handoff)
            assert parent is not None
            try:
                descriptor = os.open("objects.pack", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            finally:
                os.close(parent)
            with os.fdopen(descriptor, "rb") as source:
                metadata = os.fstat(source.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != tether._agent_uid():
                    raise RuntimeError("Publication export must be an agent-owned regular pack")
                ensure_scratch_capacity(temporary, metadata.st_size)
                pack = temporary / "objects.pack"
                with pack.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
            with pack.open("rb") as data:
                safe_subprocess.run(["git", "--no-replace-objects", "-C", str(repo), "index-pack", "--stdin"],
                                    stdin=data, env=_environment(), capture_output=True, check=True, timeout=3600)
            # Reject incomplete exports (including shallow or promisor gaps).
            safe_subprocess.run(["git", "--no-replace-objects", "-C", str(repo), "fsck", "--connectivity-only", "--no-reflogs", head],
                                env=_environment(), capture_output=True, check=True, timeout=3600)
            yield repo
    finally:
        try:
            source_job(project, "cleanup", transfer_id=transfer_id)
        except Exception:
            logger.warning("Unable to remove temporary publication transfer", exc_info=True)


def run_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Installed source-side work; receives no owner environment or credentials."""
    if os.getuid() != tether._agent_uid():
        raise RuntimeError("Publication source work requires the agent identity")
    project = Path(payload["project"])
    operation = payload["operation"]
    environment = _environment()
    command = ["git", "--no-replace-objects", "-C", str(project)]
    if operation == "cleanup":
        handoff = _handoff_directory(project, payload["transfer_id"])
        if handoff.exists():
            shutil.rmtree(handoff)
        return {"cleaned": True}
    head = payload["head"]
    if not isinstance(head, str) or not _OID.fullmatch(head):
        raise ValueError("Invalid publication source")
    if operation == "export":
        handoff = _handoff_directory(project, payload["transfer_id"])
        handoff.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        handoff.mkdir(mode=0o750)
        try:
            with (handoff / "objects.pack").open("xb") as pack:
                safe_subprocess.run([*command, "pack-objects", "--stdout", "--revs"],
                                    input=(head + "\n").encode(), stdout=pack, stderr=subprocess.PIPE,
                                    env=environment, check=True, timeout=3600)
            (handoff / "objects.pack").chmod(0o640)
            return {"ready": True, "transfer_id": payload["transfer_id"],
                    "object_format": "sha1" if len(head) == 40 else "sha256"}
        except BaseException:
            shutil.rmtree(handoff)
            raise
    if operation == "hook":
        destination, old = payload["destination"], payload["old"]
        if not re.fullmatch(r"refs/heads/(main|master)", destination) or not _OID.fullmatch(old) or len(old) != len(head):
            raise ValueError("Invalid publication update")
        with disposable_scratch("publication-hook-") as temporary:
            hook_input = temporary / "updates"
            hook_input.write_text(f"{head} {head} {destination} {old}\n")
            response = safe_subprocess.run([*command, "hook", "run", "--ignore-missing", f"--to-stdin={hook_input}",
                                            "pre-push", "--", payload["remote"], payload["remote_url"]],
                                           text=True, capture_output=True, env=environment, timeout=310, check=False)
        return {"returncode": response.returncode}
    if operation == "update_tracking":
        tracking_ref = payload["tracking_ref"]
        if not re.fullmatch(r"refs/remotes/[A-Za-z0-9][A-Za-z0-9._-]*/(main|master)", tracking_ref):
            raise ValueError("Invalid publication tracking ref")
        safe_subprocess.run([*command, "update-ref", tracking_ref, head], env=environment,
                            capture_output=True, check=True, timeout=30)
        return {"updated": True}
    raise ValueError("Unsupported publication source operation")
