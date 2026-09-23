"""Source-bound local acceptance receipts and narrow repository mutation locking."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.env_files import project_env_files


class AcceptanceError(RuntimeError):
    """The requested source cannot be accepted or its receipt is invalid."""


AcceptanceRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]

_SCHEMA_VERSION = 1
_ACCEPTANCE_COMMANDS: tuple[tuple[str, ...], ...] = (("st", "check", "--check"),)
_INPUT_NAMES = {
    ".st-check.toml",
    "AGENTS.md",
    "alembic.ini",
    "biome.json",
    "biome.jsonc",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "poetry.lock",
    "pyproject.toml",
    "pytest.ini",
    "requirements.txt",
    "setup.cfg",
    "tox.ini",
    "tsconfig.build.json",
    "tsconfig.json",
    "uv.lock",
    "vite.config.ts",
    "vitest.config.ts",
    "yarn.lock",
}

# These process inputs can change the canonical full gate's database target,
# runtime configuration, or test-runner behavior.  Receipt entries retain only
# presence and SHA-256; secret values are never persisted or logged.
_GATE_ENVIRONMENT_NAMES = (
    "CI",
    "DATABASE_ADMIN_URL",
    "DATABASE_URL",
    "NODE_ENV",
    "PGHOST",
    "PGPASSWORD",
    "PGPORT",
    "PGUSER",
    "POSTGRES_ADMIN_URL",
    "PYTEST_ADDOPTS",
    "REDIS_URL",
    "TEST_DATABASE_URL",
)


def _local_gate_file_candidates(repo: Path) -> list[tuple[str, Path]]:
    """Return known local config files consumed by the full check surface."""
    candidates: list[tuple[str, Path]] = [("~/.env.local", Path.home() / ".env.local")]
    for label, root in (("root", repo), ("backend", repo / "backend"), ("frontend", repo / "frontend")):
        for path in project_env_files(root):
            # Examples are not runtime inputs; committed examples remain bound
            # by the accepted Git tree like every other source file.
            if path.name == ".env.example":
                continue
            candidates.append((f"{label}/{path.name}", path))
    candidates.extend(
        (
            ("root/.st-check.toml", repo / ".st-check.toml"),
            ("backend/.env.test", repo / "backend" / ".env.test"),
            ("backend/.env.test.local", repo / "backend" / ".env.test.local"),
            ("frontend/.env.test", repo / "frontend" / ".env.test"),
            ("frontend/.env.test.local", repo / "frontend" / ".env.test.local"),
        )
    )
    unique: dict[str, Path] = {}
    for name, path in candidates:
        unique.setdefault(name, path)
    return sorted(unique.items())


def _secret_safe_file_input(name: str, path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {"name": name, "state": "missing"}
        if not path.is_file():
            return {"name": name, "state": "not_regular"}
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return {"name": name, "state": "unreadable"}
    return {"name": name, "state": "present", "sha256": digest}


def _local_gate_inputs(repo: Path) -> dict[str, Any]:
    """Fingerprint selected local gate inputs without retaining their values."""
    files = [
        _secret_safe_file_input(name, path)
        for name, path in _local_gate_file_candidates(repo)
    ]
    environment: list[dict[str, Any]] = []
    for name in _GATE_ENVIRONMENT_NAMES:
        value = os.environ.get(name)
        environment.append(
            {"name": name, "state": "unset"}
            if value is None
            else {
                "name": name,
                "state": "present",
                "sha256": hashlib.sha256(value.encode()).hexdigest(),
            }
        )
    payload: dict[str, Any] = {"files": files, "environment": environment}
    payload["fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def _git(
    repo: Path, args: Sequence[str], *, text: bool = True
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", *args], cwd=repo, text=text, capture_output=True, check=False
    )


def _git_value(repo: Path, args: Sequence[str], error: str) -> str:
    result = _git(repo, args)
    if result.returncode or not result.stdout.strip():
        raise AcceptanceError(result.stderr.strip() or error)
    return result.stdout.strip()


def _git_common_dir(repo: Path) -> Path:
    value = _git_value(
        repo,
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        "cannot resolve repository metadata directory",
    )
    return Path(value)


@contextmanager
def repo_lock(repo: Path, *, purpose: str) -> Iterator[None]:
    """Acquire the shared, nonblocking lock for mutations of one repository."""
    common = _git_common_dir(repo)
    lock_dir = common / "st"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "repo-mutation.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AcceptanceError(
                f"repo_mutation_in_progress: cannot start {purpose}; retry after the active repository operation"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _hash_parts(parts: Sequence[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _workspace_fingerprint(repo: Path) -> tuple[str, str]:
    status = _git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if status.returncode:
        raise AcceptanceError(status.stderr.strip() or "cannot inspect checkout state")
    unstaged = _git(repo, ["diff", "--binary", "--no-ext-diff"], text=False)
    staged = _git(repo, ["diff", "--cached", "--binary", "--no-ext-diff"], text=False)
    untracked = _git(repo, ["ls-files", "--others", "--exclude-standard", "-z"])
    for result in (unstaged, staged, untracked):
        if result.returncode:
            stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="replace")
            raise AcceptanceError(stderr.strip() or "cannot fingerprint checkout inputs")
    parts = [status.stdout.encode(), unstaged.stdout, staged.stdout]
    for relative in sorted(path for path in untracked.stdout.split("\0") if path):
        path = repo / relative
        try:
            content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        except OSError as exc:
            raise AcceptanceError(f"cannot fingerprint untracked input: {relative}") from exc
        parts.extend((relative.encode(), content))
    return status.stdout, _hash_parts(parts)


def workspace_fingerprint(repo: Path) -> str:
    """Return an exact tracked and nonignored-untracked checkout fingerprint."""
    return _workspace_fingerprint(repo.resolve())[1]


def _source_input_paths(repo: Path, commit: str) -> list[str]:
    result = _git(repo, ["ls-tree", "-r", "-z", "--name-only", commit])
    if result.returncode:
        raise AcceptanceError(result.stderr.strip() or "cannot enumerate accepted source inputs")
    selected = []
    for value in result.stdout.split("\0"):
        if not value:
            continue
        path = Path(value)
        if (
            path.name in _INPUT_NAMES
            or value == "scripts/lib/tool-registry.json"
            or "alembic/versions" in value
            or value.startswith((".github/workflows/", ".agents/"))
        ):
            selected.append(value)
    return sorted(selected)


def _source_inputs(repo: Path, commit: str) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    for path in _source_input_paths(repo, commit):
        result = _git(repo, ["show", f"{commit}:{path}"], text=False)
        if result.returncode:
            raise AcceptanceError(f"cannot read accepted source input: {path}")
        entries.append({"path": path, "sha256": hashlib.sha256(result.stdout).hexdigest()})
    fingerprint = _hash_parts(
        [f"{entry['path']}\0{entry['sha256']}".encode() for entry in entries]
    )
    return {"fingerprint": fingerprint, "files": entries}


def source_identity(repo: Path, *, sha: str = "HEAD") -> dict[str, Any]:
    """Capture the immutable revision plus current tracked/untracked checkout inputs."""
    repo = repo.resolve()
    commit = _git_value(
        repo, ["rev-parse", "--verify", f"{sha}^{{commit}}"], "source revision is not a commit"
    )
    tree = _git_value(
        repo, ["rev-parse", "--verify", f"{commit}^{{tree}}"], "source tree is unavailable"
    )
    status, workspace = _workspace_fingerprint(repo)
    source_inputs = _source_inputs(repo, commit)
    local_inputs = _local_gate_inputs(repo)
    combined = _hash_parts(
        [
            commit.encode(),
            tree.encode(),
            workspace.encode(),
            source_inputs["fingerprint"].encode(),
            local_inputs["fingerprint"].encode(),
        ]
    )
    return {
        "commit": commit,
        "tree": tree,
        "clean": not status,
        "status": status,
        "workspace_fingerprint": workspace,
        "source_inputs": source_inputs,
        "local_inputs": local_inputs,
        "input_fingerprint": combined,
    }


def _file_identity(path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        return {
            "path": str(resolved),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        }
    except OSError:
        return {"path": str(path), "unavailable": True}


def _acceptance_plan() -> dict[str, Any]:
    executable = shutil.which("st")
    plan: dict[str, Any] = {
        "commands": [list(command) for command in _ACCEPTANCE_COMMANDS],
        "toolchain": {"st": _file_identity(Path(executable)) if executable else {"unavailable": True}},
        "remote_security": "not_run_local_acceptance_does_not_claim_codeql_equivalence",
    }
    plan["fingerprint"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return plan


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in receipt.items()
        if key not in {"acceptance_id", "task_id", "scope"}
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _receipt_path(repo: Path, key: str) -> Path:
    directory = _git_common_dir(repo) / "st" / "acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{key}.json"


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _load_receipt(receipt: Mapping[str, Any] | Path) -> tuple[dict[str, Any], Path | None]:
    if isinstance(receipt, Path):
        try:
            value = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AcceptanceError("acceptance receipt is unreadable") from exc
        artifact = receipt
    else:
        value = dict(receipt)
        artifact_value = value.pop("acceptance_artifact", None)
        artifact = Path(artifact_value) if isinstance(artifact_value, str) else None
        for key in (
            "source_commit",
            "source_tree",
            "input_fingerprint",
            "acceptance_plan_fingerprint",
            "reused",
            "reuse_lookup_ms",
        ):
            value.pop(key, None)
    if not isinstance(value, dict):
        raise AcceptanceError("acceptance receipt must contain an object")
    return value, artifact


def _descriptor(
    receipt: Mapping[str, Any], artifact: Path, *, reused: bool, task_id: str | None = None
) -> dict[str, Any]:
    source = receipt["source"]
    inputs = receipt["inputs"]
    plan = receipt["plan"]
    return {
        **receipt,
        "acceptance_artifact": str(artifact),
        "source_commit": source["commit"],
        "source_tree": source["tree"],
        "input_fingerprint": inputs["fingerprint"],
        "acceptance_plan_fingerprint": plan["fingerprint"],
        "task_id": task_id if task_id is not None else receipt.get("task_id", ""),
        "reused": reused,
    }


def validate_acceptance_receipt(
    repo: Path,
    receipt: Mapping[str, Any] | Path,
    *,
    sha: str | None = None,
) -> dict[str, Any]:
    """Validate a successful receipt and return its immutable source descriptor."""
    repo = repo.resolve()
    value, artifact = _load_receipt(receipt)
    acceptance_id = value.get("acceptance_id")
    if not isinstance(acceptance_id, str) or _receipt_digest(value) != acceptance_id:
        raise AcceptanceError("acceptance receipt integrity check failed")
    if value.get("schema_version") != _SCHEMA_VERSION or value.get("state") != "success":
        raise AcceptanceError("acceptance receipt does not record successful full acceptance")
    source = value.get("source")
    inputs = value.get("inputs")
    plan = value.get("plan")
    if not isinstance(source, dict) or not isinstance(inputs, dict) or not isinstance(plan, dict):
        raise AcceptanceError("acceptance receipt is missing source-bound inputs")
    commit = _git_value(
        repo,
        ["rev-parse", "--verify", f"{source.get('commit', '')}^{{commit}}"],
        "accepted source commit is unavailable",
    )
    tree = _git_value(
        repo, ["rev-parse", "--verify", f"{commit}^{{tree}}"], "accepted source tree is unavailable"
    )
    if commit != source.get("commit") or tree != source.get("tree"):
        raise AcceptanceError("accepted source no longer matches its commit/tree identity")
    if sha is not None:
        expected = _git_value(
            repo, ["rev-parse", "--verify", f"{sha}^{{commit}}"], "requested source is unavailable"
        )
        if expected != commit:
            raise AcceptanceError("acceptance receipt belongs to a different source commit")
    source_inputs = _source_inputs(repo, commit)
    if source_inputs != inputs.get("source_inputs"):
        raise AcceptanceError("accepted dependency/configuration inputs no longer match")
    local_inputs = _local_gate_inputs(repo)
    if local_inputs != inputs.get("local_inputs"):
        raise AcceptanceError("accepted local environment/configuration inputs no longer match")
    current_plan = _acceptance_plan()
    if current_plan != plan:
        raise AcceptanceError("acceptance plan or local toolchain changed; rerun full acceptance")
    checks = value.get("checks")
    commands = current_plan["commands"]
    if (
        not isinstance(checks, list)
        or len(checks) != len(commands)
        or value.get("check_count") != len(commands)
        or any(
            not isinstance(check, dict)
            or check.get("command") != command
            or check.get("state") != "success"
            or type(check.get("returncode")) is not int
            or check["returncode"] != 0
            for check, command in zip(checks, commands, strict=True)
        )
    ):
        raise AcceptanceError("acceptance checks do not record successful completion of the full plan")
    if artifact is None:
        artifact = _receipt_path(repo, acceptance_id)
    return _descriptor(value, artifact, reused=False)


def accept_revision(
    repo: Path,
    *,
    sha: str,
    scope: Sequence[str] = (),
    task_id: str = "",
    reuse: bool = True,
    runner: AcceptanceRunner | None = None,
) -> dict[str, Any]:
    """Run or reuse full local acceptance for the exact clean HEAD revision."""
    repo = repo.resolve()
    run = runner or _run
    with repo_lock(repo, purpose="full acceptance"):
        acceptance_started = time.monotonic()
        before = source_identity(repo, sha=sha)
        head = _git_value(repo, ["rev-parse", "--verify", "HEAD^{commit}"], "HEAD is unavailable")
        if before["commit"] != head:
            raise AcceptanceError("full acceptance requires the requested revision to be checked out at HEAD")
        if not before["clean"]:
            raise AcceptanceError("full acceptance requires a clean checkout including nonignored untracked files")
        plan = _acceptance_plan()
        normalized_scope = sorted({str(path).strip() for path in scope if str(path).strip()})
        key = _hash_parts(
            [
                before["commit"].encode(),
                before["tree"].encode(),
                before["input_fingerprint"].encode(),
                plan["fingerprint"].encode(),
            ]
        )
        artifact = _receipt_path(repo, key)
        if reuse and artifact.is_file():
            try:
                validated = validate_acceptance_receipt(repo, artifact, sha=before["commit"])
            except AcceptanceError:
                pass
            else:
                return {
                    **validated,
                    "task_id": task_id or validated.get("task_id", ""),
                    "scope": normalized_scope or validated.get("scope", []),
                    "reused": True,
                    "reuse_lookup_ms": round((time.monotonic() - acceptance_started) * 1000, 3),
                }

        started_at = datetime.now(UTC).isoformat()
        checks: list[dict[str, Any]] = []
        failed = False
        for command in plan["commands"]:
            check_started = time.monotonic()
            result = run(list(command), repo)
            detail = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            checks.append(
                {
                    "command": command,
                    "state": "success" if result.returncode == 0 else "failed",
                    "returncode": result.returncode,
                    "duration_ms": round((time.monotonic() - check_started) * 1000, 3),
                    "output_bytes": len(detail.encode()),
                    "detail": detail[-1200:],
                }
            )
            if result.returncode != 0:
                failed = True
                break
        after = source_identity(repo, sha=before["commit"])
        mutated = any(
            before[field] != after[field]
            for field in ("commit", "tree", "status", "workspace_fingerprint", "input_fingerprint")
        )
        state = "blocked" if mutated else ("failed" if failed else "success")
        reason = (
            "source_changed_during_acceptance"
            if mutated
            else ("acceptance_checks_failed" if failed else "")
        )
        receipt: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "kind": "local_full_acceptance",
            "state": state,
            "reason": reason,
            "source": {"commit": before["commit"], "tree": before["tree"]},
            "inputs": {
                "fingerprint": before["input_fingerprint"],
                "workspace_fingerprint": before["workspace_fingerprint"],
                "source_inputs": before["source_inputs"],
                "local_inputs": before["local_inputs"],
            },
            "plan": plan,
            "scope": normalized_scope,
            "task_id": task_id,
            "checks": checks,
            "check_count": len(checks),
            "duration_ms": round((time.monotonic() - acceptance_started) * 1000, 3),
            "output_bytes": sum(check["output_bytes"] for check in checks),
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        receipt["acceptance_id"] = _receipt_digest(receipt)
        _write_receipt(artifact, receipt)
        if state != "success":
            raise AcceptanceError(f"{reason}; acceptance evidence: {artifact}")
        return _descriptor(receipt, artifact, reused=False)
