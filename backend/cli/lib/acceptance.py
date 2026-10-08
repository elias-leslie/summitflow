"""Source-bound local acceptance receipts and narrow repository mutation locking."""

from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv.parser import parse_stream

from app.utils.env_files import project_env_files


class AcceptanceError(RuntimeError):
    """The requested source cannot be accepted or its receipt is invalid."""


AcceptanceRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]

_SCHEMA_VERSION = 3
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
    "SEMGREP_RULES",
    "GITLEAKS_CONFIG",
    "ST_OSV_OFFLINE",
)
_SHARED_CONFIGURATION_KEYS = frozenset({
    "DATABASE_URL", "DATABASE_ADMIN_URL", "POSTGRES_ADMIN_URL", "REDIS_URL", "TEST_DATABASE_URL",
})


def _canonical_gate_environment() -> dict[str, str]:
    """Keep explicit overrides; normalize only redundant literal home-file exports.

    Managed workers export the shared env file that local gates already bind
    and consume. Recreate local unset execution, never inject defaults or strip
    an override merely because its key exists in a file.
    """
    environment = dict(os.environ)
    try:
        with (Path.home() / ".env.local").open(encoding="utf-8") as stream:
            bindings = list(parse_stream(stream))
    except (OSError, UnicodeError):
        return environment
    if any(binding.error for binding in bindings):
        return environment
    for binding in bindings:
        key, value = binding.key, binding.value
        if (key not in _SHARED_CONFIGURATION_KEYS or value is None or "${" in value or
                sum(other.key == key for other in bindings) != 1):
            continue
        if environment.get(key) == value:
            environment.pop(key)
    return environment


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
            ("root/.env.test", repo / ".env.test"),
            ("root/.env.test.local", repo / ".env.test.local"),
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
        entry = path.lstat()
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return {"name": name, "state": "unreadable"}
    return {"name": name, "state": "present", "sha256": digest,
            "file_type": stat.S_IFMT(entry.st_mode), "mode": stat.S_IMODE(info.st_mode) & 0o777,
            "uid": info.st_uid, "gid": info.st_gid, "nlink": info.st_nlink, "size": info.st_size}


def _local_gate_inputs(repo: Path) -> dict[str, Any]:
    """Fingerprint selected local gate inputs without retaining their values."""
    files = [
        _secret_safe_file_input(name, path)
        for name, path in _local_gate_file_candidates(repo)
    ]
    environment: list[dict[str, Any]] = []
    canonical_environment = _canonical_gate_environment()
    for name in _GATE_ENVIRONMENT_NAMES:
        value = canonical_environment.get(name)
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
    repo: Path, args: Sequence[str], *, text: bool = True, input: str | bytes | None = None
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", "--no-replace-objects", "--no-optional-locks", "-c", "diff.autoRefreshIndex=false", *args], cwd=repo, text=text, input=input, capture_output=True, check=False,
        env={**{key: value for key, value in os.environ.items() if not key.startswith("GIT_")}, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"},
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


def _source_tree_entries(repo: Path, commit: str) -> dict[str, tuple[str, str]]:
    result = _git(repo, ["ls-tree", "-r", "-z", commit])
    if result.returncode:
        raise AcceptanceError("cannot enumerate accepted source files")
    entries = {}
    for entry in result.stdout.split("\0"):
        header, separator, name = entry.partition("\t")
        fields = header.split()
        if separator and len(fields) == 3:
            entries[name] = (fields[0], fields[2])
    return entries


def _regular_source_blobs(repo: Path, commit: str) -> dict[str, tuple[str, str]]:
    return {name: entry for name, entry in _source_tree_entries(repo, commit).items()
            if entry[0] in {"100644", "100755"}}


def _matches_git_blob(path: Path, oid: str) -> bool:
    # Compare raw checkout bytes with the actual accepted Git blob semantics.
    # Never run clean filters, write objects, or consult ambient Git config.
    algorithm = {40: "sha1", 64: "sha256"}.get(len(oid))
    if algorithm is None:
        raise AcceptanceError("unsupported source object format")
    with path.open("rb") as stream:
        digest = hashlib.new(algorithm)
        digest.update(f"blob {os.fstat(stream.fileno()).st_size}\0".encode())
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == oid


def projected_source_modes(repo: Path, sha: str) -> dict[str, int]:
    """Project exact ordinary file modes consumed by an isolated Git revision.

    Equivalent current tracked regular files keep their actual ordinary bits
    only when owned by this user with one link; ambiguous metadata is rejected.
    Historical, changed, linked or execute-mismatched files retain safe Git
    defaults. Isolation and receipt validation use this one policy.
    """
    repo = repo.resolve()
    current = _regular_source_blobs(repo, "HEAD")
    projected = {}
    for name, (git_mode, oid) in _regular_source_blobs(repo, sha).items():
        permissions = 0o755 if git_mode == "100755" else 0o644
        original = repo / name
        if current.get(name, (None, None))[0] == git_mode:
            try:
                info = original.lstat()
                actual = stat.S_IMODE(info.st_mode) & 0o777
                if (stat.S_ISREG(info.st_mode) and original.parent.resolve() == original.parent
                        and bool(actual & stat.S_IXUSR) == (git_mode == "100755")
                        and _matches_git_blob(original, oid)):
                    if info.st_uid != os.getuid() or info.st_nlink != 1:
                        raise AcceptanceError("equivalent source metadata cannot be safely preserved in isolation")
                    permissions = actual
            except (FileNotFoundError, NotADirectoryError):
                pass
        projected[name] = permissions
    return projected


def _mode_identity(modes: Mapping[str, Any]) -> dict[str, Any]:
    content = json.dumps(modes, sort_keys=True, separators=(",", ":")).encode()
    return {"schema_version": 1, "file_count": len(modes), "fingerprint": hashlib.sha256(content).hexdigest()}


def _working_source_paths(repo: Path) -> list[str]:
    result = _git(repo, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    if result.returncode:
        raise AcceptanceError("cannot enumerate working source inputs")
    return sorted(set(result.stdout.split("\0")) - {""})


def _materialized_source_entries(repo: Path, paths: Sequence[str]) -> dict[str, Any]:
    """Read consumed file bytes and ordinary modes without Git clean filters."""
    entries = {}
    for name in paths:
        path = repo / name
        try:
            info = path.lstat()
            actual = info
            if path.parent.resolve() != path.parent:
                raise AcceptanceError("source materialization contains a linked parent directory")
            mode = stat.S_IMODE(info.st_mode) & 0o777
            if stat.S_ISLNK(info.st_mode):
                digest = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
                kind = "symlink"
            elif stat.S_ISREG(info.st_mode):
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
                    actual = os.fstat(stream.fileno())
                    if not stat.S_ISREG(actual.st_mode):
                        raise AcceptanceError("source materialization is not a regular file")
                    mode = stat.S_IMODE(actual.st_mode) & 0o777
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                kind = "regular"
            else:
                raise AcceptanceError("source materialization contains an unsupported file type")
            entries[name] = {"kind": kind, "mode": mode, "sha256": digest,
                             "uid": actual.st_uid, "gid": actual.st_gid,
                             "nlink": actual.st_nlink, "size": actual.st_size}
        except (FileNotFoundError, NotADirectoryError):
            entries[name] = {"kind": "missing"}
        except OSError as exc:
            raise AcceptanceError("cannot fingerprint consumed source materialization") from exc
    return entries


def _materialization_identity(entries: Mapping[str, Any]) -> dict[str, Any]:
    content = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {"file_count": len(entries), "fingerprint": hashlib.sha256(content).hexdigest()}


def working_source_materialization_identity(repo: Path) -> dict[str, Any]:
    """Guard every current tracked/nonignored-untracked physical source input."""
    repo = repo.resolve()
    return _materialization_identity(_materialized_source_entries(repo, _working_source_paths(repo)))


def _git_blob_identities(repo: Path, oids: Sequence[str]) -> dict[str, dict[str, Any]]:
    selected = sorted(set(oids))
    result = _git(repo, ["cat-file", "--batch"], text=False, input="".join(f"{oid}\n" for oid in selected).encode())
    if result.returncode:
        raise AcceptanceError("cannot read canonical source blobs")
    identities = {}
    offset = 0
    for oid in selected:
        end = result.stdout.find(b"\n", offset)
        header = result.stdout[offset:end].split()
        if end < 0 or len(header) != 3 or header[0] != oid.encode() or header[1] != b"blob":
            raise AcceptanceError("canonical source blob is unavailable")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise AcceptanceError("canonical source blob is invalid") from exc
        offset = end + 1
        content = result.stdout[offset:offset + size]
        if len(content) != size or result.stdout[offset + size:offset + size + 1] != b"\n":
            raise AcceptanceError("canonical source blob is incomplete")
        identities[oid] = {"sha256": hashlib.sha256(content).hexdigest(), "size": size}
        offset += size + 1
    return identities


def _source_execution(repo: Path, commit: str, basis: str,
                      mode_entries: Mapping[str, int] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    tree = _source_tree_entries(repo, commit)
    if basis == "actual":
        entries = _materialized_source_entries(repo, sorted(tree))
        modes = {name: entries[name].get("mode") for name, (mode, _oid) in tree.items()
                 if mode in {"100644", "100755"}}
    elif basis == "isolated":
        if any(mode not in {"100644", "100755", "120000"} for mode, _oid in tree.values()):
            raise AcceptanceError("isolated source materialization contains an unsupported Git file type")
        modes = dict(mode_entries) if mode_entries is not None else projected_source_modes(repo, commit)
        regular = {name: mode for name, (mode, _oid) in tree.items() if mode in {"100644", "100755"}}
        if (set(modes) != set(regular) or any(type(value) is not int or not 0 <= value <= 0o777
                or bool(value & stat.S_IXUSR) != (regular[name] == "100755") for name, value in modes.items())):
            raise AcceptanceError("isolated source permission entries differ from the immutable Git tree")
        blobs = _git_blob_identities(repo, [oid for _mode, oid in tree.values()])
        # A private checkout creates single-link files owned by the executing
        # user/group. Verify these exact metadata values in the actual clone.
        entries = {name: {"kind": "symlink" if mode == "120000" else "regular",
                          "mode": 0o777 if mode == "120000" else modes[name],
                          "uid": os.getuid(), "gid": os.getgid(), "nlink": 1, **blobs[oid]}
                   for name, (mode, oid) in tree.items()}
    else:
        raise AcceptanceError("consumed source binding has an unsupported execution basis")
    return {"schema_version": 1, "basis": basis, "materialization": _materialization_identity(entries)}, _mode_identity(modes)


def _source_input_fingerprint(source: Mapping[str, Any]) -> str:
    return _hash_parts([
        source["commit"].encode(), source["tree"].encode(), source["workspace_fingerprint"].encode(),
        source["source_inputs"]["fingerprint"].encode(), source["local_inputs"]["fingerprint"].encode(),
        source["source_modes"]["fingerprint"].encode(),
        json.dumps(source["execution"], sort_keys=True, separators=(",", ":")).encode(),
    ])


def _accepted_source_cache_key(source: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    """Use one clean-source cache policy for actual and isolated receipt lookup."""
    accepted_inputs = _source_input_fingerprint({**source, "workspace_fingerprint": _hash_parts([b"", b"", b""])})
    return _hash_parts([source["commit"].encode(), source["tree"].encode(), accepted_inputs.encode(), plan["fingerprint"].encode()])


def working_source_mode_identity(repo: Path) -> dict[str, Any]:
    """Bind actual tracked/nonignored source modes, including dirty contents."""
    repo = repo.resolve()
    modes = {}
    for name in _working_source_paths(repo):
        try:
            info = (repo / name).lstat()
            modes[name] = [stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode) & 0o777]
        except (FileNotFoundError, NotADirectoryError):
            modes[name] = None
    return _mode_identity(modes)


def source_identity(repo: Path, *, sha: str = "HEAD", execution_basis: str = "actual") -> dict[str, Any]:
    """Bind accepted materialization separately from the full working-source guard."""
    repo = repo.resolve()
    commit = _git_value(
        repo, ["rev-parse", "--verify", f"{sha}^{{commit}}"], "source revision is not a commit"
    )
    tree = _git_value(
        repo, ["rev-parse", "--verify", f"{commit}^{{tree}}"], "source tree is unavailable"
    )
    status, workspace = _workspace_fingerprint(repo)
    source_inputs = _source_inputs(repo, commit)
    execution, source_modes = _source_execution(repo, commit, execution_basis)
    if execution_basis == "isolated":
        actual = _materialization_identity(_materialized_source_entries(repo, sorted(_source_tree_entries(repo, commit))))
        if actual != execution["materialization"]:
            raise AcceptanceError("isolated source materialization differs from canonical Git inputs; checkout transformations are unsupported")
    working_materialization = working_source_materialization_identity(repo)
    local_inputs = _local_gate_inputs(repo)
    source = {
        "commit": commit,
        "tree": tree,
        "clean": not status,
        "status": status,
        "workspace_fingerprint": workspace,
        "source_inputs": source_inputs,
        "source_modes": source_modes,
        "execution": execution,
        "working_materialization": working_materialization,
        "local_inputs": local_inputs,
        "source_mode_entries": projected_source_modes(repo, commit) if execution_basis == "isolated" else None,
    }
    source["input_fingerprint"] = _source_input_fingerprint(source)
    return source


def isolated_input_identity(repo: Path, *, sha: str,
                             captured: Mapping[str, Any] | None = None,
                             scope: Sequence[str] = ()) -> dict[str, Any]:
    """Capture only immutable source and mutable inputs isolation consumes.

    Unrelated staged/untracked workspace bytes are neither mounted nor checked
    by the private gate. Owned paths are guarded separately at capture/finalize.
    """
    commit = _git_value(repo, ["rev-parse", "--verify", f"{sha}^{{commit}}"], "source unavailable")
    tree = _git_value(repo, ["rev-parse", "--verify", f"{commit}^{{tree}}"], "tree unavailable")
    entries = captured["source_mode_entries"] if captured is not None else projected_source_modes(repo, commit)
    execution, modes = _source_execution(repo, commit, "isolated", entries)
    metadata = {}
    for name in _regular_source_blobs(repo, commit):
        if scope and not any(name == path or name.startswith(path.rstrip("/") + "/") for path in scope):
            continue
        try:
            info = (repo / name).lstat()
            metadata[name] = [stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid, info.st_nlink]
        except OSError:
            metadata[name] = None
    return {"commit": commit, "tree": tree, "execution": execution, "source_modes": modes,
            "source_mode_entries": entries, "host_source_metadata": _mode_identity(metadata),
            "source_inputs": _source_inputs(repo, commit), "local_inputs": _local_gate_inputs(repo),
            "workspace_fingerprint": _hash_parts([b"", b"", b""])}


def _file_identity(path: Path, *, name: str, content: bytes | None = None) -> dict[str, Any]:
    try:
        if content is None:
            content = path.resolve(strict=True).read_bytes()
        return {
            "name": name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    except OSError:
        return {"name": name, "unavailable": True}


def _entrypoint_identity(path: Path, *, name: str, content: bytes | None = None) -> dict[str, Any]:
    # CLI_REFERENCE is consumed solely as Typer root help. Its prose never
    # chooses or configures the forwarded check execution path.
    try:
        module = ast.parse(path.read_text(encoding="utf-8") if content is None else content.decode("utf-8"))
        for statement in module.body:
            if isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "CLI_REFERENCE" for target in statement.targets):
                statement.value = ast.Constant(value="")
        content = ast.dump(module, include_attributes=False).encode()
        return {"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "format": "python_ast_without_root_help"}
    except (OSError, UnicodeError, SyntaxError):
        return _file_identity(path, name=name, content=content)


def _acceptance_plan(*, repo: Path | None = None, commit: str | None = None,
                     check_names: Sequence[str] = ("ruff", "types", "pytest", "biome", "tsc", "vitest", "security")) -> dict[str, Any]:
    # Bind content, not checkout location or extraction timestamps. The same
    # accepted source is installed in an immutable managed release directory.
    from cli.tool_registry import tool_registry_path
    backend = Path(__file__).resolve().parents[2]
    implementation = [path for path in sorted((backend / "cli" / "commands").glob("check*.py"))
                      if path.name != "check_codeql.py" and not path.name.startswith("checkpoints")]
    if repo is not None and commit is not None:
        implementation = [repo / name for name in sorted(_source_tree_entries(repo, commit))
                          if Path(name).parent == Path("backend/cli/commands") and Path(name).match("check*.py")
                          and Path(name).name != "check_codeql.py" and not Path(name).name.startswith("checkpoints")]
    implementation.extend([
        Path(__file__), backend / "cli" / "lib" / "acceptance_coordinator.py",
        backend / "cli" / "main.py", backend / "cli" / "tool_registry.py",
        backend / "cli" / "commands" / "done_task_acceptance.py",
        backend / "app" / "utils" / "heavy_work.py", backend / "app" / "utils" / "safe_subprocess.py",
        backend / "app" / "utils" / "transient_scratch.py",
        backend / "app" / "utils" / "host_retention_policy.py",
    ])

    def gate_identity(path: Path) -> dict[str, Any]:
        name = str(path.relative_to(backend.parent))
        content = None
        if repo is not None and commit is not None:
            result = _git(repo, ["show", f"{commit}:{name}"], text=False)
            if result.returncode:
                return {"name": name, "unavailable": True}
            content = result.stdout
        identify = _entrypoint_identity if path == backend / "cli" / "main.py" else _file_identity
        return identify(path, name=name, content=content)

    # Operator descriptions, prompts and unrelated tool catalogue entries are
    # not read by the full gate. Bind the effective selected check declarations.
    try:
        if repo is not None and commit is not None:
            result = _git(repo, ["show", f"{commit}:scripts/lib/tool-registry.json"], text=False)
            if result.returncode:
                raise ValueError("accepted tool registry is unavailable")
            registry = json.loads(result.stdout)
        else:
            registry = json.loads(tool_registry_path().read_text(encoding="utf-8"))
        checks = {item["name"]: item["check"] for item in registry.get("tools", [])
                  if isinstance(item, dict) and isinstance(item.get("check"), dict)
                  and item.get("name") in check_names}
        registry_identity = {"checks": checks}
    except (OSError, ValueError, AttributeError):
        registry_identity = gate_identity(tool_registry_path())
    plan: dict[str, Any] = {
        "commands": [list(command) for command in _ACCEPTANCE_COMMANDS],
        "toolchain": {"st": {"entrypoint": "cli.main:app"}},
        "remote_security": "not_run_local_acceptance_does_not_claim_codeql_equivalence",
        "gate_implementation": [gate_identity(path) for path in implementation],
        "check_configuration": registry_identity,
        "security_tools": {name: _file_identity(Path(path), name=name) if (path := shutil.which(name)) else {"unavailable": True}
                           for name in ("gitleaks", "semgrep", "osv-scanner")},
    }
    plan["fingerprint"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return plan


def _project_acceptance_plan(repo: Path, *, commit: str | None = None,
                              check_names: Sequence[str] | None = None) -> dict[str, Any]:
    import shlex

    from cli.commands.check import _resolve_command
    from cli.commands.check_native import (
        NativeCheckError,
        _environment_identity,
        native_plan,
        python_runtime_root,
    )
    from cli.commands.check_runner import _tool_configs, _workdir

    try:
        native = native_plan(repo, commit=commit)
    except NativeCheckError as exc:
        raise AcceptanceError(str(exc)) from exc
    names = list(check_names) if check_names is not None else native["legacy_tools"] if native is not None else ["ruff", "types", "pytest", "biome", "tsc", "vitest", "security"]
    # Isolation consumes this project's CLI from its selected Git tree. Other
    # projects still consume the separately installed shared gate unchanged.
    source_bound = commit is not None and Path(__file__).resolve().parents[3] == repo.resolve()
    plan = _acceptance_plan(repo=repo, commit=commit, check_names=names) if source_bound else _acceptance_plan()
    legacy_configs = dict(plan["check_configuration"].get("checks", {})) if source_bound else _tool_configs()
    if source_bound:
        for name in ("gitleaks", "semgrep", "osv", "security"):
            legacy_configs.setdefault(name, {"label": name.upper(), "internal_adapter": True})
    legacy = {name: legacy_configs[name] for name in names if name in legacy_configs}
    plan["legacy_tools"] = {}
    runtime_paths: set[Path] = set()
    for name, config in legacy.items():
        if config.get("internal_adapter"):
            continue
        command = _resolve_command(str(config.get("binary") or name), repo, _workdir(repo, config), shlex.split(str(config.get("args") or "")))
        plan["legacy_tools"][name] = _file_identity(Path(command[0]), name=name)
        parts = Path(command[0]).parts
        for marker in (".venv", "venv", "node_modules"):
            if marker in parts:
                runtime_paths.add(Path(*parts[:parts.index(marker) + 1]))
    plan["prepared_legacy_environment"] = [_environment_identity(repo, path, commit=commit) for path in sorted(runtime_paths)]
    if {"security", "semgrep", "gitleaks"}.intersection(names):
        from cli.commands.check_security import _semgrep_config

        rules = _semgrep_config(repo)
        gitleaks = Path(os.environ["GITLEAKS_CONFIG"]).expanduser() if os.environ.get("GITLEAKS_CONFIG") else repo / ".gitleaks.toml"
        plan["security_configuration"] = {
            "semgrep": _environment_identity(repo, rules) if rules is not None else {"state": "not-applicable", "reason": "no_local_rules"},
            "gitleaks": _environment_identity(repo, gitleaks),
        }
        for tool in plan.get("security_tools", {}).values():
            if not tool.get("unavailable"):
                executable = shutil.which(tool["name"])
                if executable:
                    runtime = python_runtime_root(Path(executable))
                    if runtime is not None:
                        runtime_paths.add(runtime)
        plan["prepared_legacy_environment"] = [_environment_identity(repo, path, commit=commit) for path in sorted(runtime_paths)]
    if native is not None:
        # Preserve and bind applicable approved legacy tools alongside declared
        # native stages. Native suite commands execute once, rather than again
        # through pytest/vitest unless explicitly listed in legacy_tools.
        plan["check_configuration"] = {"checks": legacy}
        if not {"security", "gitleaks", "semgrep", "osv"}.intersection(names):
            plan.pop("security_tools", None)
        plan["native"] = {**native, "environment": {
            key: {"sha256": hashlib.sha256(value.encode()).hexdigest()}
            for key, value in native["environment"].items()
        }}
    plan.pop("fingerprint", None)
    plan["fingerprint"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return plan


def _gate_evidence(detail: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    native = plan.get("native")
    if native is None:
        # Historical textual stages cannot be promoted to native coverage. A
        # missing declared suite/tool or deferred check is never full acceptance.
        incomplete = any(":DEFER:" in line or (":SKIP:" in line and any(
            reason in line for reason in ("tool_not_installed", "no_declared_tests", "no_tests", "required")
        )) for line in detail.splitlines())
        return {"coverage": "full", "state": "unavailable" if incomplete else "pass", "stages": [],
                "format": "legacy_aggregate"}
    try:
        lines = [line.removeprefix("NATIVE_EVIDENCE:") for line in detail.splitlines() if line.startswith("NATIVE_EVIDENCE:")]
        if len(lines) != 1:
            raise ValueError("native evidence missing or ambiguous")
        evidence = json.loads(lines[0])
        _validate_native_evidence(evidence, native, require_success=False)
        if evidence["state"] == "pass" and evidence["coverage"] == "full":
            _validate_native_evidence(evidence, native)
    except (ValueError, TypeError, KeyError) as exc:
        return {"coverage": "unknown", "state": "unavailable", "stages": [], "reason": str(exc)}
    return evidence


def _coverage_plan(repo: Path, plan: dict[str, Any], *, coverage: str,
                   scope: Sequence[str], required_stages: Sequence[str]) -> dict[str, Any]:
    if coverage not in {"task", "full"}:
        raise AcceptanceError("Acceptance coverage must be task or full")
    if coverage == "full":
        if required_stages:
            declared = {stage["id"] for stage in plan.get("native", {}).get("stages", [])}
            if not set(required_stages).issubset(declared):
                raise AcceptanceError("Required acceptance stage is missing from the native declaration")
        return plan
    if not scope:
        raise AcceptanceError("Task acceptance requires explicit literal owned scope")
    from cli.commands.done_task_acceptance import require_scope_matches_revision

    require_scope_matches_revision(repo, _git_value(repo, ["rev-parse", "HEAD"], "HEAD unavailable"), tuple(scope))
    declared = {stage["id"]: stage for stage in plan.get("native", {}).get("stages", [])}
    if any(name not in declared or not declared[name]["applicable"] for name in required_stages):
        raise AcceptanceError("Required acceptance stage is missing or not applicable")
    selected = sorted(set(required_stages))
    value = {**plan, "coverage": "task", "scope": list(scope), "required_stages": selected,
             "commands": [["st", "check", "--quick", "--changed-only"],
                          *[["st", "check", "--native", "--stage", name] for name in selected]]}
    value.pop("fingerprint", None)
    value["fingerprint"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value


def requested_plan(repo: Path, *, commit: str | None, coverage: str,
                    scope: Sequence[str], required_stages: Sequence[str]) -> dict[str, Any]:
    """Bind the actual gate selection, including quick tools for task proof."""
    from cli.commands.check_constants import _TOOL_SELECTIONS

    names = _TOOL_SELECTIONS["--quick"][0] if coverage == "task" else None
    plan = _project_acceptance_plan(repo, commit=commit, check_names=names)
    return _coverage_plan(repo, plan, coverage=coverage, scope=scope, required_stages=required_stages)


def _task_gate_evidence(repo: Path, detail: str, plan: Mapping[str, Any], command: Sequence[str]) -> dict[str, Any]:
    if "--stage" in command:
        stage_id = command[-1]
        selected = next(stage for stage in plan["native"]["stages"] if stage["id"] == stage_id)
        evidence = _gate_evidence(detail, {"native": {"stages": [selected], "legacy_tools": []}})
        _validate_task_evidence(evidence, selected)
        return evidence
    # Quick checkpoints intentionally defer cross-cutting suites. That is
    # honest task coverage, never full coverage; explicitly required native
    # stages execute separately. Missing tools and failed checks still block.
    blocked = ":OK:" not in detail or any(":FAIL:" in line or (":SKIP:" in line and any(
        reason in line for reason in ("tool_not_installed", "required", "no_tests"))) for line in detail.splitlines())
    digest = hashlib.sha256(detail.encode()).hexdigest()
    directory = _git_common_dir(repo) / "st" / "native-stages" / "artifacts"
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / digest
    artifact.write_bytes(detail.encode())
    return {"coverage": "task", "state": "fail" if blocked else "pass", "format": "scoped_aggregate",
            "stages": [{"id": "scoped-quality", "state": "fail" if blocked else "pass", "required": True,
                        "coverage": "task", "command": list(command), "artifacts": [{"path": "output",
                            "state": "present", "sha256": digest, "retained_path": str(artifact)}]}]}


def _validate_task_evidence(evidence: Mapping[str, Any], stage: Mapping[str, Any] | None = None,
                              command: Sequence[str] = ()) -> None:
    if evidence.get("state") != "pass":
        raise AcceptanceError("Task acceptance required evidence is failed or unavailable")
    if stage is None:
        if evidence.get("coverage") != "task" or evidence.get("format") != "scoped_aggregate":
            raise AcceptanceError("Task acceptance is missing scoped quality evidence")
        stages = evidence.get("stages")
        if (not isinstance(stages, list) or len(stages) != 1 or stages[0].get("id") != "scoped-quality"
                or stages[0].get("state") != "pass" or stages[0].get("coverage") != "task"
                or stages[0].get("required") is not True or stages[0].get("command") != list(command)
                or not stages[0].get("artifacts")):
            raise AcceptanceError("Task acceptance is missing its required scoped quality stage")
        for artifact in stages[0]["artifacts"]:
            if (artifact.get("state") != "present" or artifact.get("path") != "output"
                    or not isinstance(artifact.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
                raise AcceptanceError("Task acceptance is missing scoped quality artifacts")
        return
    stages = evidence.get("stages")
    if not isinstance(stages, list) or len(stages) != 1:
        raise AcceptanceError("Task acceptance is missing its required native stage")
    outcome = stages[0]
    if (outcome.get("id") != stage["id"] or outcome.get("command") != stage["argv"]
            or outcome.get("state") != "pass" or outcome.get("returncode") != 0
            or any(outcome.get(key) != stage[key] for key in ("tool", "cwd", "coverage", "required"))):
        raise AcceptanceError("Task acceptance required native stage identity or success differs")
    if stage.get("evidence"):
        artifacts = outcome.get("artifacts")
        expected = stage["evidence"].get("source", "file")
        expected = stage["evidence"]["path"] if expected == "file" else expected
        if (not isinstance(artifacts, list) or not artifacts or artifacts[0].get("path") != expected
                or any(item.get("state") != "present" or not isinstance(item.get("sha256"), str)
                       or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in artifacts)):
            raise AcceptanceError("Task acceptance is missing required native artifacts")
    if stage["kind"] == "test":
        counts = outcome.get("counts", {})
        if (any(type(counts.get(key)) is not int or counts[key] < 0 for key in ("executed", "failed", "skipped"))
                or not counts["executed"] or counts["failed"] or counts["skipped"] > counts.get("not_applicable", 0)):
            raise AcceptanceError("Task acceptance required native tests were empty, failed or skipped")


def _validate_native_evidence(evidence: Any, native: Mapping[str, Any], *, require_success: bool = True) -> None:
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1 or evidence.get("coverage") not in {"full", "focused"} or evidence.get("state") not in {"pass", "fail"}:
        raise ValueError("invalid native evidence envelope")
    if require_success and (evidence["coverage"] != "full" or evidence["state"] != "pass"):
        raise ValueError("native evidence does not record successful full coverage")
    if native.get("legacy_tools"):
        legacy = evidence.get("legacy")
        if not isinstance(legacy, dict) or legacy.get("coverage") != "full" or (require_success and legacy.get("state") != "pass"):
            raise ValueError("native evidence omits applicable legacy checks")
    stages = evidence.get("stages")
    expected = native["stages"]
    if not isinstance(stages, list) or len(stages) != len(expected):
        raise ValueError("native evidence omits declared stages")
    for outcome, stage in zip(stages, expected, strict=True):
        if not isinstance(outcome, dict) or any(outcome.get(key) != stage[key] for key in ("id", "required", "coverage", "cwd", "tool")) or outcome.get("command") != stage["argv"]:
            raise ValueError("native stage identity differs from declaration")
        if require_success and stage["required"] and (outcome.get("state") != "pass" or outcome.get("coverage") != "full" or type(outcome.get("returncode")) is not int or outcome["returncode"] != 0):
            raise ValueError("required native stage was failed, unavailable, skipped or focused")
        if outcome.get("state") not in {"pass", "fail", "unavailable", "not-applicable"}:
            raise ValueError("unknown native stage outcome")
        if outcome.get("covered_by"):
            covering = next((item for item in stages if item.get("id") == outcome["covered_by"]), {})
            declaration = next((item for item in expected if item["id"] == outcome["covered_by"]), {})
            if (stage.get("covered_by") != outcome["covered_by"] or stage["required"]
                    or outcome["state"] != "not-applicable" or outcome.get("reason") != f"coverage_provided_by:{outcome['covered_by']}"
                    or covering.get("state") != "pass" or declaration.get("coverage") != "full"
                    or not declaration.get("required") or declaration.get("kind") != stage["kind"]):
                raise ValueError("focused stage coverage is not provided by successful required full coverage")
        if not isinstance(outcome.get("duration_ms"), (float, int)) or outcome["duration_ms"] < 0:
            raise ValueError("native stage duration missing")
        if stage["required"] and outcome.get("state") == "pass" and stage.get("evidence"):
            artifacts = outcome.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts or any(
                not isinstance(artifact, dict) or artifact.get("state") != "present"
                or not isinstance(artifact.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
                for artifact in artifacts
            ) or artifacts[0].get("path") != (stage["evidence"].get("source") if stage["evidence"].get("source") in {"stdout", "combined"} else stage["evidence"]["path"]):
                raise ValueError("required native artifact identity missing")
        if stage["required"] and outcome.get("state") == "pass" and stage["kind"] == "test":
            counts = outcome.get("counts")
            if not isinstance(counts, dict) or any(type(counts.get(key)) is not int or counts[key] < 0 for key in ("executed", "failed", "skipped")) or counts["executed"] < 1 or counts["failed"] or counts["skipped"] > counts.get("not_applicable", 0):
                raise ValueError("required native suite was empty, failed or skipped")
            if counts.get("not_applicable", 0) and (not stage.get("evidence", {}).get("not_applicable_tests") or type(counts["not_applicable"]) is not int or counts["not_applicable"] > counts["skipped"]):
                raise ValueError("native skipped cases lack an explicit not-applicable declaration")


def _validate_retained_native_artifacts(repo: Path, evidence: Mapping[str, Any], directory: Path | None = None) -> None:
    directory = directory or (_git_common_dir(repo) / "st" / "native-stages" / "artifacts")
    for stage in evidence["stages"]:
        if stage["state"] == "pass":
            for artifact in stage["artifacts"]:
                retained = directory / artifact["sha256"]
                if not artifact.get("retained_path") or hashlib.sha256(retained.read_bytes()).hexdigest() != artifact["sha256"]:
                    raise ValueError(f"{stage['id']}: native evidence artifact unavailable or changed")


def _run(command: list[str], cwd: Path, *, native_reuse: bool = True,
         scope: Sequence[str] = ()) -> subprocess.CompletedProcess[str]:
    if command and command[0] == "st":
        # Invoke the exact implementation fingerprinted above. Safe-path mode
        # excludes the target project's cwd from module lookup; a different
        # PATH launcher or target-owned cli module cannot replace this gate.
        # Bind this CLI's import lookup only, not PYTHONPATH inherited by a
        # different project's pytest/type/tool children.
        bootstrap = "import sys; sys.path.insert(0, sys.argv.pop(1)); from cli.main import app; app()"
        environment = _canonical_gate_environment()
        if scope:
            environment["ST_CHECK_CHANGED_FILES"] = "\n".join(scope)
        if not native_reuse:
            environment["ST_NATIVE_NO_REUSE"] = "1"
        return subprocess.run([sys.executable, "-P", "-c", bootstrap,
                               str(Path(__file__).resolve().parents[2]), *command[1:]],
                              cwd=cwd, env=environment, text=True, capture_output=True, check=False)
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


def acceptance_artifact_directory(repo: Path) -> Path:
    """The repository's canonical immutable acceptance evidence root."""
    return _git_common_dir(repo) / "st" / "acceptance"


def _receipt_path(repo: Path, key: str) -> Path:
    directory = acceptance_artifact_directory(repo)
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
            "working_tree_clean",
            "scope_digest",
            "receipt_reference",
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
        "scope_digest": scope_digest(receipt.get("scope", ())),
    }


def scope_digest(scope: Sequence[str]) -> str:
    """Authoritative literal-scope identity shared by proof and intent adapters."""
    normalized = sorted({path.strip() for path in scope if path.strip()})
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()


def validate_acceptance_receipt(
    repo: Path,
    receipt: Mapping[str, Any] | Path,
    *,
    sha: str | None = None,
    evidence_directory: Path | None = None,
) -> dict[str, Any]:
    """Validate a successful receipt and return its immutable source descriptor."""
    repo = repo.resolve()
    value, artifact = _load_receipt(receipt)
    acceptance_id = value.get("acceptance_id")
    if not isinstance(acceptance_id, str) or _receipt_digest(value) != acceptance_id:
        raise AcceptanceError("acceptance receipt integrity check failed")
    if value.get("schema_version") not in {2, _SCHEMA_VERSION} or value.get("state") != "success":
        raise AcceptanceError("acceptance receipt does not record successful full acceptance")
    coverage = value.get("coverage")
    if coverage not in {"full", "task"} or (coverage == "task" and value.get("schema_version") != 3):
        raise AcceptanceError("acceptance receipt does not record supported acceptance coverage")
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
    recorded_execution = inputs.get("execution")
    if (not isinstance(recorded_execution, dict) or recorded_execution.get("schema_version") != 1
            or recorded_execution.get("basis") not in {"actual", "isolated"}):
        raise AcceptanceError("acceptance receipt is missing a supported consumed source binding")
    mode_entries = inputs.get("source_mode_entries")
    if recorded_execution["basis"] == "isolated":
        if not isinstance(mode_entries, dict):
            raise AcceptanceError("Legacy isolated receipt lacks immutable source permission entries; fresh proof required")
        # The selected clone's ordinary permissions are immutable evidence.
        # Recheck owned permissions, not unrelated WIP bytes or projections.
        owned = value.get("scope", [])
        for name, mode in mode_entries.items():
            if any(name == path or name.startswith(path.rstrip("/") + "/") for path in owned):
                try:
                    info = (repo / name).lstat()
                except OSError as exc:
                    raise AcceptanceError("Owned source permission inputs are unavailable") from exc
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) & 0o777 != mode):
                    raise AcceptanceError("Owned source permission inputs no longer match")
    execution, source_modes = _source_execution(repo, commit, recorded_execution["basis"], mode_entries)
    if source_modes != inputs.get("source_modes"):
        raise AcceptanceError("accepted source permission inputs no longer match or were not recorded")
    if execution != recorded_execution:
        raise AcceptanceError("accepted source materialization no longer matches its consumed source binding")
    local_inputs = _local_gate_inputs(repo)
    if local_inputs != inputs.get("local_inputs"):
        raise AcceptanceError("accepted local environment/configuration inputs no longer match")
    current_plan = requested_plan(repo, commit=commit if recorded_execution["basis"] == "isolated" else None,
                                  coverage=coverage, scope=plan.get("scope", ()), required_stages=plan.get("required_stages", ()))
    if coverage == "task" and value.get("scope") != current_plan["scope"]:
        raise AcceptanceError("Task acceptance receipt belongs to a different owned scope")
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
    for check in checks:
        evidence = check.get("evidence")
        if coverage == "task":
            if not isinstance(evidence, dict):
                raise AcceptanceError("Task acceptance is missing required evidence")
            selected_stage = None
            if "--stage" in check["command"]:
                selected_stage = next(stage for stage in current_plan["native"]["stages"] if stage["id"] == check["command"][-1])
            _validate_task_evidence(evidence, selected_stage, check["command"])
            try:
                _validate_retained_native_artifacts(repo, evidence, evidence_directory)
            except (OSError, ValueError, KeyError) as exc:
                raise AcceptanceError(f"invalid task acceptance artifact: {exc}") from exc
            continue
        if not isinstance(evidence, dict) or evidence.get("coverage") != "full" or evidence.get("state") != "pass":
            raise AcceptanceError("acceptance check evidence does not record full coverage")
        if current_plan.get("native") is not None:
            try:
                _validate_native_evidence(evidence, current_plan["native"])
                _validate_retained_native_artifacts(repo, evidence, evidence_directory)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise AcceptanceError(f"invalid native acceptance evidence: {exc}") from exc
    immutable_artifact = acceptance_artifact_directory(repo) / f"{acceptance_id}.json"
    if immutable_artifact.is_file():
        artifact = immutable_artifact
    if artifact is None:
        artifact = immutable_artifact
    return _descriptor(value, artifact, reused=False)


def persist_validated_receipt(
    repo: Path,
    receipt: Mapping[str, Any] | Path,
    *,
    sha: str,
    evidence_directory: Path | None = None,
) -> dict[str, Any]:
    """Retain an isolated accepted-source proof while the caller holds repo_lock.

    The caller supplies the isolated native artifact directory explicitly.
    Source/config/toolchain and every artifact digest are checked against this
    repository before any receipt becomes reusable here.
    """
    repo = repo.resolve()
    validated = validate_acceptance_receipt(repo, receipt, sha=sha, evidence_directory=evidence_directory)
    value, _ = _load_receipt(validated)
    if evidence_directory is not None:
        destination = _git_common_dir(repo) / "st" / "native-stages" / "artifacts"
        destination.mkdir(parents=True, exist_ok=True)
        for check in value["checks"]:
            for stage in check["evidence"]["stages"]:
                for artifact in stage["artifacts"]:
                    content = (evidence_directory / artifact["sha256"]).read_bytes()
                    if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
                        raise AcceptanceError("isolated native artifact changed during retention")
                    target = destination / artifact["sha256"]
                    with tempfile.NamedTemporaryFile("wb", dir=destination, delete=False) as handle:
                        temporary = Path(handle.name)
                        handle.write(content)
                    temporary.replace(target)
    artifact = _receipt_path(repo, value["acceptance_id"])
    _write_receipt(artifact, value)
    key = _hash_parts([value["source"]["commit"].encode(), value["source"]["tree"].encode(),
                       value["inputs"]["fingerprint"].encode(), value["plan"]["fingerprint"].encode()])
    _write_receipt(_receipt_path(repo, key), value)
    return _descriptor(value, artifact, reused=False)


def accept_revision(
    repo: Path,
    *,
    sha: str,
    scope: Sequence[str] = (),
    task_id: str = "",
    reuse: bool = True,
    runner: AcceptanceRunner | None = None,
    execution_basis: str = "actual",
    coverage: str = "full",
    required_stages: Sequence[str] = (),
) -> dict[str, Any]:
    """Accept actual clean HEAD inputs, or a verified isolated Git materialization."""
    repo = repo.resolve()
    run = runner or (lambda command, cwd: _run(command, cwd, native_reuse=reuse,
                                               scope=normalized_scope if coverage == "task" else ()))
    with repo_lock(repo, purpose="full acceptance"):
        acceptance_started = time.monotonic()
        before = source_identity(repo, sha=sha, execution_basis=execution_basis)
        head = _git_value(repo, ["rev-parse", "--verify", "HEAD^{commit}"], "HEAD is unavailable")
        if before["commit"] != head:
            raise AcceptanceError("full acceptance requires the requested revision to be checked out at HEAD")
        plan_commit = before["commit"] if execution_basis == "isolated" else None
        normalized_scope = sorted({str(path).strip() for path in scope if str(path).strip()})
        plan = requested_plan(repo, commit=plan_commit, coverage=coverage, scope=normalized_scope, required_stages=required_stages)
        # A previously accepted immutable HEAD remains accepted while unrelated
        # WIP is present. Look up only its clean-source key; never certify that
        # WIP or run a fresh full gate over a dirty candidate.
        key = _accepted_source_cache_key(before, plan)
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
                    "working_tree_clean": before["clean"],
                    "reuse_lookup_ms": round((time.monotonic() - acceptance_started) * 1000, 3),
                }
        if not before["clean"]:
            raise AcceptanceError("full acceptance requires a clean checkout including nonignored untracked files; no reusable accepted-source receipt")

    started_at = datetime.now(UTC).isoformat()
    checks: list[dict[str, Any]] = []
    failed = False
    for command in plan["commands"]:
        check_started = time.monotonic()
        result = run(list(command), repo)
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        try:
            evidence = _task_gate_evidence(repo, detail, plan, command) if coverage == "task" else _gate_evidence(detail, plan)
        except AcceptanceError as exc:
            evidence = {"coverage": "task", "state": "fail", "stages": [], "reason": str(exc)}
        if (plan.get("native") is not None or coverage == "task") and evidence["state"] == "pass":
            try:
                _validate_retained_native_artifacts(repo, evidence)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                evidence = {**evidence, "state": "fail", "reason": f"native_artifact_unavailable: {exc}"}
        passed = result.returncode == 0 and evidence["state"] == "pass" and (coverage == "task" or evidence["coverage"] == "full")
        checks.append(
            {
                "command": command,
                "state": "success" if passed else "failed",
                "outcome": "pass" if passed else ("fail" if result.returncode else "unavailable"),
                "coverage": evidence["coverage"],
                "evidence": evidence,
                "returncode": result.returncode,
                "duration_ms": round((time.monotonic() - check_started) * 1000, 3),
                "output_bytes": len(detail.encode()),
                "detail": detail[-1200:],
            }
        )
        if not passed:
            failed = True
            break
    with repo_lock(repo, purpose="finalize acceptance"):
        try:
            after = source_identity(repo, sha=before["commit"], execution_basis=execution_basis)
            mutated = any(
                before[field] != after[field]
                for field in ("commit", "tree", "status", "workspace_fingerprint", "input_fingerprint", "working_materialization")
            )
        except (AcceptanceError, OSError):
            mutated = True
        try:
            plan_changed = requested_plan(repo, commit=plan_commit, coverage=coverage, scope=normalized_scope,
                                           required_stages=required_stages) != plan
        except AcceptanceError:
            plan_changed = True
        state = "blocked" if mutated or plan_changed else ("failed" if failed else "success")
        reason = (
            "source_changed_during_acceptance"
            if mutated
            else ("acceptance_plan_changed_during_acceptance" if plan_changed else "acceptance_checks_failed" if failed else "")
        )
        receipt: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "kind": "local_task_acceptance" if coverage == "task" else "local_full_acceptance",
            "coverage": "task" if coverage == "task" else "full" if all(check["coverage"] == "full" for check in checks) else "focused",
            "requested_coverage": coverage,
            "state": state,
            "reason": reason,
            "source": {"commit": before["commit"], "tree": before["tree"]},
            "inputs": {
                "fingerprint": before["input_fingerprint"],
                "workspace_fingerprint": before["workspace_fingerprint"],
                "source_inputs": before["source_inputs"],
                "source_modes": before["source_modes"],
                "source_mode_entries": before["source_mode_entries"],
                "execution": before["execution"],
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
        cache_artifact = artifact
        if state != "success":
            # A retry of these exact inputs may later pass. Its reusable cache
            # entry must not erase the failure artifact already given to users.
            artifact = _receipt_path(repo, receipt["acceptance_id"])
        else:
            artifact = _receipt_path(repo, receipt["acceptance_id"])
        _write_receipt(artifact, receipt)
        if state == "success":
            # The lookup entry can advance; the evidence hyperlink remains
            # immutable so reruns never overwrite an earlier accepted receipt.
            _write_receipt(cache_artifact, receipt)
        if state != "success":
            failed_check = next((check for check in checks if check["state"] == "failed"), None)
            failure_line = next(
                (line for line in (failed_check or {}).get("detail", "").splitlines() if ":FAIL:" in line),
                None,
            )
            summary = f"{reason}; {failure_line}" if failure_line else reason
            raise AcceptanceError(f"{summary}; acceptance evidence: {artifact}")
        return _descriptor(receipt, artifact, reused=False)
