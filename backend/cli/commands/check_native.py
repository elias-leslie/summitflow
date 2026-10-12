"""Versioned, explicitly prepared project-native quality stages."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import tempfile
import time
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.utils.heavy_work import heavy_work
from app.utils.transient_scratch import ScratchError, managed_temp_parent

_CONTENT_HASHES: dict[tuple[int, int, int, int, int], str] = {}
_RACY_NS = 2_000_000_000


def _content_hash(path: Path) -> str:
    info = path.stat()
    key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if key in _CONTENT_HASHES:
        return _CONTENT_HASHES[key]
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    # Timestamps are coarse: a same-size rewrite within one tick keeps the key,
    # so only files settled for a while are cached (git's "racy" rule).
    if time.time_ns() - max(info.st_mtime_ns, info.st_ctime_ns) > _RACY_NS:
        _CONTENT_HASHES[key] = digest
    return digest


class NativeCheckError(ValueError):
    """A native plan is malformed or cannot establish its declared coverage."""


def _local(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise NativeCheckError("native paths must be relative to the project")
    candidate = root / path
    if candidate != root and not candidate.parent.resolve().is_relative_to(root.resolve()):
        raise NativeCheckError("native path parent escapes the project")
    return candidate


def identity(root: Path, path: Path) -> dict[str, Any]:
    name = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    try:
        info = path.stat()
        digest = _content_hash(path)
    except OSError:
        return {"path": name, "state": "unavailable"}
    value = {"path": name, "state": "present", "size": info.st_size, "mode": stat.S_IMODE(info.st_mode), "sha256": digest}
    if path.is_symlink():
        value["link_target"] = os.readlink(path)
    return value


def python_runtime_root(executable: Path) -> Path | None:
    """Bind Python launchers without treating standalone ELF tools as venvs."""
    runtime = next((candidate for candidate in (executable.parent.parent, executable.resolve().parent.parent)
                    if (candidate / "pyvenv.cfg").is_file()), None)
    if runtime is None:
        return None
    try:
        with executable.open("rb") as stream:
            header = stream.read(256).split(b"\n", 1)[0]
        python = executable.name.startswith("python") or (header.startswith(b"#!") and b"python" in header)
        return runtime if python else None
    except OSError:
        return runtime


def _environment_identity(root: Path, path: Path, *, commit: str | None = None,
                          prune: frozenset[str] = frozenset()) -> dict[str, Any]:
    if not path.is_dir():
        return identity(root, path)
    entries = []
    seen: set[tuple[int, int]] = set()
    tree: dict[str, tuple[str, str]] = {}
    modes: dict[str, int] = {}
    if commit is not None:
        from cli.lib.acceptance import _source_tree_entries, projected_source_modes

        tree = _source_tree_entries(root, commit)
        modes = projected_source_modes(root, commit)

    def workspace_source(candidate: Path, resolved_directory: Path) -> str | None:
        if not tree:
            return None
        resolved = candidate.resolve() if candidate.is_symlink() else resolved_directory / candidate.name
        if not resolved.is_relative_to(resolved_root):
            return None
        relative = resolved.relative_to(resolved_root)
        # Source-backed workspace links resolve through the accepted tree in
        # bwrap, not through the host's ignored dist/WIP. Prepared package-local
        # node_modules still has its explicit read-only dependency mount.
        if len(relative.parts) < 2 or relative.parts[0] != "packages" or "node_modules" in relative.parts:
            return None
        package = Path(*relative.parts[:2]).as_posix() + "/"
        return relative.as_posix() if any(name.startswith(package) for name in tree) else None

    try:
        # Resolve invariant ancestors once; individual symlinks still need their
        # target resolved before deciding whether they project accepted source.
        resolved_root = root.resolve() if tree else root
        for directory, subdirs, files in os.walk(path, followlinks=True):
            current = Path(directory)
            info = current.stat()
            if (info.st_dev, info.st_ino) in seen:
                subdirs[:] = []
                continue
            seen.add((info.st_dev, info.st_ino))
            resolved_directory = current.resolve() if tree else current
            # Prepared executable caches can be consumed by tool runtimes.
            # Bind them conservatively; native Python writes to a fresh prefix.
            subdirs[:] = sorted(name for name in subdirs if name not in prune and (
                not (relative := workspace_source(current / name, resolved_directory))
                or relative in tree or any(item.startswith(relative + "/") for item in tree)))
            # Vitest rewrites its run-order cache on every test run; it is not a
            # dependency input, and binding it makes acceptance drift mid-check.
            if path.name == "node_modules" and current == path / ".vite":
                subdirs[:] = [name for name in subdirs if name != "vitest"]
            for name in subdirs:
                candidate = current / name
                if candidate.is_symlink():
                    entries.append({"path": candidate.relative_to(path).as_posix(), "state": "present", "kind": "directory_link", "target": os.readlink(candidate)})
            for name in sorted(files):
                candidate = current / name
                item = identity(path, candidate)
                if relative := workspace_source(candidate, resolved_directory):
                    if relative not in tree:
                        continue
                    from cli.lib.acceptance import _git

                    selected = _git(root, ["show", f"{commit}:{relative}"], text=False)
                    if selected.returncode or tree[relative][0] not in {"100644", "100755"}:
                        raise OSError("selected workspace dependency source unavailable")
                    item = {"path": candidate.relative_to(path).as_posix(), "state": "present",
                            "size": len(selected.stdout), "mode": modes[relative],
                            "sha256": hashlib.sha256(selected.stdout).hexdigest()}
                if item["state"] != "present":
                    raise OSError("prepared environment entry unavailable")
                entries.append(item)
        return {"path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
                "state": "present", "file_count": len(entries), "sha256": _digest(entries)}
    except OSError:
        return {"path": str(path), "state": "unavailable"}


# Installer-written manifests that pin what a prepared runtime contains.
_NODE_LOCK_MANIFESTS = (".pnpm/lock.yaml", ".package-lock.json", ".yarn-state.yml", ".yarn-integrity")
_PYTHON_CACHE_NAMES = frozenset({"__pycache__"})


def _python_environment_manifest(root: Path, path: Path) -> list[dict[str, Any]]:
    """Bind a virtualenv by its installed distributions, not by its caches.

    Each distribution's RECORD (or METADATA) pins its files' install-time
    hashes. Top-level site-packages entries no distribution claims are still
    bound by content, so hand-placed modules keep invalidating reuse.
    """
    entries: list[dict[str, Any]] = [{"manifest": "pyvenv.cfg", **identity(path, path / "pyvenv.cfg")}]
    binaries = path / "bin"
    if binaries.is_dir():
        for candidate in sorted(binaries.iterdir()):
            if candidate.is_symlink():
                entries.append({"bin": candidate.name, "target": os.readlink(candidate)})
            elif candidate.is_file():
                entries.append({"bin": candidate.name, "sha256": _content_hash(candidate)})
    seen: set[Path] = set()
    for site in sorted(path.glob("lib*/python*/site-packages")):
        # lib64 is conventionally a link to lib; bind each real directory once.
        if not site.is_dir() or site.resolve() in seen:
            continue
        seen.add(site.resolve())
        claimed: set[str] = set()
        names = sorted(item.name for item in site.iterdir())
        for name in names:
            if not name.endswith((".dist-info", ".egg-info")):
                continue
            distribution = site / name
            record = next((distribution / item for item in ("RECORD", "METADATA", "PKG-INFO") if (distribution / item).is_file()), None)
            if record is None:
                raise OSError("installed distribution lacks a manifest")
            content = record.read_bytes()
            entries.append({"distribution": f"{site.relative_to(path).as_posix()}/{name}", "manifest": record.name,
                            "sha256": hashlib.sha256(content).hexdigest()})
            claimed.add(name)
            if record.name == "RECORD":
                for line in content.decode("utf-8", "replace").splitlines():
                    top = line.split(",", 1)[0].split("/", 1)[0]
                    if top and top not in {".", ".."}:
                        claimed.add(top)
        for name in names:
            if name in claimed or name in _PYTHON_CACHE_NAMES:
                continue
            entries.append({"unclaimed": f"{site.relative_to(path).as_posix()}/{name}",
                            **_environment_identity(root, site / name, prune=_PYTHON_CACHE_NAMES)})
    return entries


def _node_modules_manifest(root: Path, path: Path, *, commit: str | None) -> list[dict[str, Any]]:
    """Bind node_modules by package links/versions and the installer's lock.

    Store links name exact package versions; the installed lockfile pins their
    integrity. Workspace links into this repository are bound by content.
    """
    entries: list[dict[str, Any]] = []
    stores: set[Path] = set()
    resolved_root = root.resolve()

    def package(candidate: Path, name: str) -> None:
        if candidate.is_symlink():
            target = candidate.resolve()
            entries.append({"package": name, "target": os.readlink(candidate)})
            if "node_modules" in target.parts:
                store = Path(*target.parts[:target.parts.index("node_modules") + 1])
                stores.add(store)
            elif target.is_relative_to(resolved_root):
                entries.append({"workspace": name, **_environment_identity(root, candidate, commit=commit,
                                                                         prune=frozenset({"node_modules"}))})
                nested = target / "node_modules"
                if nested.is_dir():
                    entries.append({"workspace_modules": name, "entries": _node_modules_manifest(root, nested, commit=commit)})
            else:
                entries.append({"external": name, **_environment_identity(root, candidate)})
        elif candidate.is_dir():
            manifest = candidate / "package.json"
            entries.append({"package": name, **(identity(candidate, manifest) if manifest.is_file()
                                                else _environment_identity(root, candidate))})
        elif candidate.is_file():
            entries.append({"file": name, "sha256": _content_hash(candidate)})

    for candidate in sorted(path.iterdir()):
        name = candidate.name
        if name == ".bin":
            for binary in sorted(candidate.iterdir()):
                entries.append({"bin": binary.name, **({"target": os.readlink(binary)} if binary.is_symlink()
                                                       else {"sha256": _content_hash(binary)})})
        elif name.startswith("@") and candidate.is_dir() and not candidate.is_symlink():
            for scoped in sorted(candidate.iterdir()):
                package(scoped, f"{name}/{scoped.name}")
        elif not name.startswith("."):
            package(candidate, name)
    stores.add(path)
    for store in sorted(stores):
        for manifest in _NODE_LOCK_MANIFESTS:
            if (store / manifest).is_file():
                label = store.relative_to(resolved_root).as_posix() if store.is_relative_to(resolved_root) else str(store)
                entries.append({"lock": f"{label}/{manifest}", "sha256": _content_hash(store / manifest)})
    return entries


def _prepared_identity(root: Path, path: Path, *, commit: str | None = None) -> dict[str, Any]:
    """Bind a prepared runtime by lockfile plus installed-manifest identity.

    Virtualenvs and node_modules rewrite caches (pyc, Vite/Vitest results) on
    every run; those bytes are not dependency inputs. Other prepared runtimes
    keep their complete content walk.
    """
    if not path.is_dir():
        return identity(root, path)
    name = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    try:
        if (path / "pyvenv.cfg").is_file():
            entries, kind = _python_environment_manifest(root, path), "python_distributions"
        elif path.name == "node_modules":
            entries, kind = _node_modules_manifest(root, path, commit=commit), "node_packages"
        else:
            return _environment_identity(root, path, commit=commit)
        if any(entry.get("state") == "unavailable" for entry in entries):
            raise OSError("prepared environment entry unavailable")
    except OSError:
        return {"path": name, "state": "unavailable"}
    return {"path": name, "state": "present", "identity": kind, "entry_count": len(entries), "sha256": _digest(entries)}


def _expand_home_tools(tools: Any) -> Any:
    """Expand a leading '~/' in native.tools to the invoking account's home.

    The account database is used instead of $HOME so isolated stages that
    override HOME still bind the same executables.
    """
    if not isinstance(tools, dict):
        return tools
    home = pwd.getpwuid(os.getuid()).pw_dir
    return {
        name: f"{home}/{path[2:]}" if isinstance(path, str) and path.startswith("~/") else path
        for name, path in tools.items()
    }


def native_plan(root: Path, *, commit: str | None = None) -> dict[str, Any] | None:
    """Load declarations strictly; legacy projects remain on their existing gate."""
    config = root / ".st-check.toml"
    if commit is None and not config.exists():
        return None
    try:
        if commit is None:
            content = config.read_text(encoding="utf-8")
        else:
            from cli.lib.acceptance import _git

            selected = _git(root, ["show", f"{commit}:.st-check.toml"])
            if selected.returncode:
                return None
            content = selected.stdout
        data = tomllib.loads(content)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise NativeCheckError(f"invalid .st-check.toml: {exc}") from exc
    native = data.get("native")
    if native is None:
        return None
    if not isinstance(native, dict) or native.get("schema_version") != 1:
        raise NativeCheckError("native.schema_version must be 1")
    locks = native.get("locks")
    paths = native.get("paths", [])
    tools = _expand_home_tools(native.get("tools", {}))
    legacy_tools = native.get("legacy_tools", ["ruff", "types", "biome", "tsc", "security"])
    environment = native.get("environment", {})
    environment_inputs = native.get("environment_inputs", [])
    managed_environment_inputs = native.get("managed_environment_inputs", [])
    stages = native.get("stages")
    if not isinstance(locks, list) or not locks or any(not isinstance(p, str) or not p for p in locks):
        raise NativeCheckError("native.locks must name the prepared project's lock/configuration inputs")
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p for p in paths):
        raise NativeCheckError("native.paths must contain project-local tool directories")
    if not isinstance(environment_inputs, list) or any(not isinstance(path, str) or not path for path in environment_inputs):
        raise NativeCheckError("native.environment_inputs must contain project-local prepared runtime files/directories")
    if not isinstance(managed_environment_inputs, list) or any(not isinstance(path, str) or not Path(path).is_absolute() for path in managed_environment_inputs):
        raise NativeCheckError("native.managed_environment_inputs must explicitly name prepared managed runtime paths")
    if not isinstance(legacy_tools, list) or any(tool not in {"ruff", "types", "pytest", "biome", "tsc", "vitest", "security", "gitleaks", "semgrep", "osv", "actionlint", "shellcheck", "govulncheck"} for tool in legacy_tools):
        raise NativeCheckError("native.legacy_tools must name supported local check tools")
    if not isinstance(tools, dict) or any(
        not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
        or not isinstance(path, str) or not Path(path).is_absolute()
        for name, path in tools.items()
    ):
        raise NativeCheckError("native.tools must explicitly name managed executable absolute paths")
    if not isinstance(environment, dict) or any(
        not isinstance(k, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", k) or not isinstance(v, str)
        for k, v in environment.items()
    ) or {"PATH", "ST_HEAVY_LEASE"}.intersection(environment):
        raise NativeCheckError("native.environment must contain literal strings; PATH is declared through native.paths")
    if not isinstance(stages, list) or not stages:
        raise NativeCheckError("native.stages must declare at least one required stage")
    normalized = []
    ids: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise NativeCheckError("native stage must be a table")
        stage_id = stage.get("id")
        argv = stage.get("argv")
        required = stage.get("required", True)
        applicable = stage.get("applicable", True)
        cwd = stage.get("cwd", ".")
        kind = stage.get("kind", "check")
        coverage = stage.get("coverage")
        evidence = stage.get("evidence")
        timeout = stage.get("timeout_seconds", 600)
        if not isinstance(stage_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", stage_id) or stage_id in ids:
            raise NativeCheckError("native stage ids must be unique nonempty identifiers")
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
            raise NativeCheckError(f"{stage_id}: argv must be a nonempty string array")
        wrapper = Path(argv[0]).name
        if wrapper in {"npx", "corepack", "pip", "pip3"} or (
            wrapper in {"npm", "pnpm", "yarn", "bun", "uv"}
            and any(arg in {"install", "add", "sync", "exec", "dlx", "x"} for arg in argv[1:3])
        ):
            raise NativeCheckError(f"{stage_id}: dependency preparation must be explicit and separate from checks")
        if type(required) is not bool or type(applicable) is not bool or kind not in {"test", "check"} or coverage not in {"full", "focused"}:
            raise NativeCheckError(f"{stage_id}: declare required/applicable booleans, kind and full/focused coverage")
        if type(timeout) is not int or timeout < 1 or timeout > 86400:
            raise NativeCheckError(f"{stage_id}: timeout_seconds must be between 1 and 86400")
        if not applicable and (required or not isinstance(stage.get("reason"), str) or not stage["reason"].strip()):
            raise NativeCheckError(f"{stage_id}: not-applicable stages must be optional with a reason")
        if not isinstance(cwd, str):
            raise NativeCheckError(f"{stage_id}: cwd must be project-local")
        _local(root, cwd)
        if not _local(root, cwd).resolve().is_relative_to(root.resolve()):
            raise NativeCheckError(f"{stage_id}: cwd escapes the project")
        if argv[0] in tools:
            executable = Path(tools[argv[0]])
        elif Path(argv[0]).is_absolute() and argv[0] in tools.values():
            executable = Path(argv[0])
        elif "/" in argv[0]:
            executable = _local(root, argv[0])
        else:
            executable = next((_local(root, p) / argv[0] for p in paths if (_local(root, p) / argv[0]).is_file()),
                              _local(root, paths[0]) / argv[0] if paths else root / argv[0])
        if kind == "test" and not isinstance(evidence, dict):
            raise NativeCheckError(f"{stage_id}: test stages require fresh counted evidence")
        if evidence is not None:
            if not isinstance(evidence, dict) or evidence.get("format") not in {"junit", "json", "go-test-json", "text"}:
                raise NativeCheckError(f"{stage_id}: unsupported evidence format")
            if evidence.get("source", "file") not in {"file", "stdout", "combined"}:
                raise NativeCheckError(f"{stage_id}: evidence.source must be file, stdout or combined")
            exemptions = evidence.get("not_applicable_tests", {})
            if not isinstance(exemptions, dict) or any(not isinstance(key, str) or not key or not isinstance(reason, str) or not reason.strip() for key, reason in exemptions.items()):
                raise NativeCheckError(f"{stage_id}: not_applicable_tests must name exact cases with reasons")
            if exemptions and evidence["format"] != "go-test-json":
                raise NativeCheckError(f"{stage_id}: exact not_applicable_tests currently requires Go test JSON")
            if evidence.get("source", "file") == "file":
                if not isinstance(evidence.get("path"), str) or not evidence["path"]:
                    raise NativeCheckError(f"{stage_id}: evidence.path must be project-local")
                _local(root, evidence["path"])
                if not _local(root, evidence["path"]).resolve().is_relative_to(root.resolve()):
                    raise NativeCheckError(f"{stage_id}: evidence escapes the project")
            if evidence["format"] == "text":
                for key in ("success_pattern", "failure_pattern", "executed_pattern"):
                    pattern = evidence.get(key)
                    if not isinstance(pattern, str) or not pattern:
                        raise NativeCheckError(f"{stage_id}: text evidence requires {key}")
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        raise NativeCheckError(f"{stage_id}: invalid {key}") from exc
        for key in ("inputs", "exclude"):
            patterns = stage.get(key, [])
            if (not isinstance(patterns, list) or any(not isinstance(item, str) or not item or item.startswith("/")
                                                       or ".." in Path(item).parts for item in patterns)):
                raise NativeCheckError(f"{stage_id}: {key} must list project-relative path globs")
        if stage.get("exclude") and not stage.get("inputs"):
            raise NativeCheckError(f"{stage_id}: exclude narrows declared inputs; declare inputs first")
        ids.add(stage_id)
        normalized.append({**stage, "id": stage_id, "argv": argv, "cwd": cwd, "kind": kind,
                           "coverage": coverage, "required": required, "applicable": applicable,
                           "tool": identity(root, executable),
                           "executable": executable.relative_to(root).as_posix() if executable.is_relative_to(root) else str(executable)})
    if not any(stage["required"] for stage in normalized):
        raise NativeCheckError("native plan must include a required stage")
    preceding: dict[str, dict[str, Any]] = {}
    for stage in normalized:
        if "covered_by" in stage:
            covering = preceding.get(stage["covered_by"]) if isinstance(stage["covered_by"], str) else None
            if (stage["required"] or stage["coverage"] != "focused" or not covering
                    or not covering["required"] or not covering["applicable"]
                    or covering["coverage"] != "full" or covering["kind"] != stage["kind"]):
                raise NativeCheckError("covered_by requires an earlier applicable required full stage of the same kind")
        preceding[stage["id"]] = stage
    runtime_paths = {_local(root, path) for path in environment_inputs} | {Path(path) for path in managed_environment_inputs}
    for path in paths:
        _local(root, path)
    for path in [*paths, *(stage["executable"] for stage in normalized if not Path(stage["executable"]).is_absolute())]:
        parts = Path(path).parts
        for marker in (".venv", "venv", "node_modules"):
            if marker in parts:
                runtime_paths.add(root.joinpath(*parts[:parts.index(marker) + 1]))
    for name, tool in tools.items():
        runtime = python_runtime_root(Path(tool))
        if runtime is not None:
            runtime_paths.add(runtime)
        if name == "go" and (Path(tool).resolve().parent.parent / "src/runtime").is_dir():
            runtime_paths.add(Path(tool).resolve().parent.parent)
    return {"schema_version": 1, "locks": [identity(root, _local(root, path)) for path in locks],
            "paths": paths, "environment": environment, "stages": normalized,
            "tools": {name: identity(root, Path(path)) for name, path in tools.items()},
            "legacy_tools": list(dict.fromkeys(legacy_tools)),
            "prepared_environment": [_prepared_identity(root, path, commit=commit) for path in sorted(runtime_paths)],
            "preparation": "explicit_only_no_installation"}


def legacy_applicability(root: Path, names: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """Retain configured local checks where the project has applicable inputs."""
    from .check_execution import tool_not_installed

    excluded = {".git", ".venv", "venv", "node_modules", ".tools", ".dev-tools", "vendor", "build", "dist", ".next"}
    python = False
    for _directory, subdirs, files in os.walk(root):
        subdirs[:] = [part for part in subdirs if part not in excluded]
        if any(Path(file).suffix in {".py", ".pyi"} or file == "pyproject.toml" for file in files):
            python = True
            break
    applicable, outcomes = [], []
    for name in names:
        reason = None
        if name in {"ruff", "types", "pytest"} and not python:
            reason = "no_python_inputs"
        elif name == "biome" and tool_not_installed(name, root):
            reason = "no_declared_biome_configuration"
        elif name == "tsc" and not any((directory / "tsconfig.json").is_file() for directory in (root, root / "frontend")):
            reason = "no_tsconfig"
        if reason:
            outcomes.append({"id": name, "state": "not-applicable", "reason": reason})
        else:
            applicable.append(name)
    return applicable, outcomes


def _counts(evidence: dict[str, Any], content: str) -> dict[str, int]:
    format_name = evidence["format"]
    if format_name == "junit":
        root = ET.fromstring(content)
        cases = list(root.iter("testcase"))
        return {"executed": sum(case.find("skipped") is None for case in cases),
                "failed": sum(case.find("failure") is not None or case.find("error") is not None for case in cases),
                "skipped": sum(case.find("skipped") is not None for case in cases)}
    if format_name == "json":
        value = json.loads(content)
        if not isinstance(value, dict) or any(type(value.get(key)) is not int or value[key] < 0 for key in ("passed", "failed", "skipped")):
            raise NativeCheckError("JSON evidence must contain nonnegative integer passed/failed/skipped counts")
        return {"executed": value["passed"] + value["failed"], "failed": value["failed"], "skipped": value["skipped"]}
    if format_name == "go-test-json":
        events = [json.loads(line) for line in content.splitlines() if line.strip()]
        terminal = [event for event in events if isinstance(event, dict) and event.get("Test") and event.get("Action") in {"pass", "fail", "skip"}]
        counts = {"executed": sum(event["Action"] != "skip" for event in terminal),
                "failed": sum(isinstance(event, dict) and event.get("Action") == "fail" for event in events),
                "skipped": sum(event["Action"] == "skip" for event in terminal)}
        if evidence.get("not_applicable_tests"):
            counts["not_applicable"] = sum(event["Action"] == "skip" and f"{event.get('Package', '')}.{event['Test']}" in evidence["not_applicable_tests"] for event in terminal)
        return counts
    if not re.search(evidence["success_pattern"], content, re.MULTILINE):
        raise NativeCheckError("text evidence lacks its success marker")
    return {"executed": len(re.findall(evidence["executed_pattern"], content, re.MULTILINE)),
            "failed": len(re.findall(evidence["failure_pattern"], content, re.MULTILINE)), "skipped": 0}


def run_native(root: Path, plan: dict[str, Any], *, stage_id: str | None = None, reuse: bool = True, full_gate: bool = True) -> dict[str, Any]:
    """Run fresh stages under admission without inheriting credentials or tool PATH."""
    # Exact named aliases allow prepared Go/Godot/OS tools without importing an
    # ambient /usr/bin or package-manager PATH into the project's stage.
    # Keep tool aliases visible at their same host path when nested bwrap
    # replaces /tmp; the sandbox's private /tmp itself is the short scratch root.
    try:
        host_scratch = managed_temp_parent("st-native", label="Native check")
    except ScratchError as exc:
        raise NativeCheckError(str(exc)) from exc
    with (tempfile.TemporaryDirectory(prefix="", dir=host_scratch) as directory,
          tempfile.TemporaryDirectory(prefix="", dir=host_scratch) as scratch):
        aliases = Path(directory) / "bin"
        aliases.mkdir(mode=0o700)
        for name, tool in plan["tools"].items():
            target = Path(tool["path"])
            # Point at the declared executable itself, rather than an inherited
            # alias that a nested private temporary-directory overlay can hide.
            target = target if target.is_absolute() else _local(root, tool["path"])
            (aliases / name).symlink_to(target.resolve())
        return _run_native(root, plan, aliases=aliases, scratch=Path(scratch), stage_id=stage_id, reuse=reuse, full_gate=full_gate)


def blocked_native_result(plan: dict[str, Any], reason: str, *, stage_id: str | None = None,
                           full_gate: bool = True) -> dict[str, Any]:
    """Record every declared stage honestly when cheap preparation blocks work."""
    stages = [stage for stage in plan["stages"] if stage_id is None or stage["id"] == stage_id]
    if not stages:
        raise NativeCheckError(f"unknown native stage: {stage_id}")
    return {"schema_version": 1, "coverage": "full" if full_gate and stage_id is None else "focused",
            "state": "fail", "stages": [{"id": stage["id"], "coverage": stage["coverage"],
                "required": stage["required"], "command": stage["argv"], "cwd": stage["cwd"],
                "tool": stage["tool"], "state": "unavailable", "returncode": None,
                "duration_ms": 0, "reason": reason, "artifacts": [], "reused": False} for stage in stages]}


def _run_native(root: Path, plan: dict[str, Any], *, aliases: Path, scratch: Path, stage_id: str | None, reuse: bool, full_gate: bool) -> dict[str, Any]:
    from cli.lib.acceptance import AcceptanceError

    stages = [stage for stage in plan["stages"] if stage_id is None or stage["id"] == stage_id]
    if not stages:
        raise NativeCheckError(f"unknown native stage: {stage_id}")
    # Validate all required preparation before acquiring any expensive stage
    # lease. A missing later tool must not waste an earlier suite execution.
    if any(item["state"] != "present" for item in [*plan["locks"], *plan["prepared_environment"]]):
        return blocked_native_result(plan, "locked_environment_unavailable; prepare explicitly", stage_id=stage_id, full_gate=full_gate)
    for stage in stages:
        if not (stage["required"] or stage_id is not None):
            continue
        executable = Path(stage["executable"]) if Path(stage["executable"]).is_absolute() else _local(root, stage["executable"])
        if not executable.is_file() or not os.access(executable, os.X_OK) or not _local(root, stage["cwd"]).is_dir():
            return blocked_native_result(plan, "project_tool_or_cwd_unavailable; prepare explicitly", stage_id=stage_id, full_gate=full_gate)
    environment = {"HOME": str(root), "LANG": "C.UTF-8", "CI": "true",
                   "XDG_CONFIG_HOME": str(aliases / "config"), "XDG_DATA_HOME": str(aliases / "data"),
                   "XDG_CACHE_HOME": str(aliases / "cache"), "XDG_STATE_HOME": str(aliases / "state"), **plan["environment"],
                   "TMPDIR": str(scratch), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(aliases / "pycache"),
                   "ST_NATIVE_TOOL_ALIAS_ROOT": str(aliases.parent),
                   "UV_NO_SYNC": "1", "UV_OFFLINE": "1", "CARGO_NET_OFFLINE": "true", "GOTOOLCHAIN": "local",
                   "GOPROXY": "off", "GOSUMDB": "off", "npm_config_offline": "true", "COREPACK_ENABLE_NETWORK": "0",
                   "PATH": os.pathsep.join([str(aliases), *(str(_local(root, path)) for path in plan["paths"])])}
    # The sandbox's explicit scratch mapping is needed by Docker bind mounts.
    # Preserve that single execution input without admitting ambient secrets.
    if host_scratch := os.environ.get("ST_NATIVE_TMP_HOST_ROOT"):
        environment["ST_NATIVE_TMP_HOST_ROOT"] = host_scratch
        environment["TMPDIR"] = "/tmp"
    outcomes = []
    try:
        before = _native_source(root)
    except (AcceptanceError, OSError):
        before = None  # Fresh observations outside Git never seed source reuse.
    cache = _stage_cache(root, plan, before) if stage_id is None and full_gate else None
    artifact_store = cache or _artifact_storage(root)
    # Stages whose fresh outcome (pass, or a deterministic failure) is cached.
    passed_stages: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for stage in stages:
        started = time.monotonic()
        outcome: dict[str, Any] = {"id": stage["id"], "coverage": stage["coverage"], "required": stage["required"],
                                   "command": stage["argv"], "cwd": stage["cwd"], "tool": stage["tool"], "artifacts": [],
                                   "state": "unavailable", "returncode": None, "reason": ""}
        if not stage["applicable"]:
            # Declared inapplicability needs no cache lookup or execution.
            outcomes.append({**outcome, "state": "not-applicable", "reason": stage["reason"], "duration_ms": 0,
                             "output_bytes": 0, "detail": "", "reused": False})
            continue
        cached = _reuse_stage(cache, stage) if reuse else None
        if cached is None and reuse:
            cached = _prior_failure(cache, stage)
        if cached is not None:
            outcomes.append({**cached, "reused": True, "reuse_lookup_ms": round((time.monotonic() - started) * 1000, 3)})
            continue
        if (stage_id is None and full_gate and stage.get("covered_by")
                and any(item["id"] == stage["covered_by"] and item["state"] == "pass" for item in outcomes)):
            outcomes.append({**outcome, "state": "not-applicable", "covered_by": stage["covered_by"],
                             "reason": f"coverage_provided_by:{stage['covered_by']}", "duration_ms": 0,
                             "output_bytes": 0, "reused": False})
            continue
        evidence = stage.get("evidence")
        report = _local(root, evidence["path"]) if evidence and evidence.get("source", "file") == "file" else None
        previous = report.stat().st_mtime_ns if report is not None and report.is_file() else None
        cwd = _local(root, stage["cwd"])
        executable = Path(stage["executable"]) if Path(stage["executable"]).is_absolute() else _local(root, stage["executable"])
        output = ""
        stdout_output = ""
        if any(lock["state"] != "present" for lock in [*plan["locks"], *plan["prepared_environment"]]):
            outcome["reason"] = "locked_environment_unavailable; prepare explicitly"
        elif not executable.is_file() or not os.access(executable, os.X_OK) or not cwd.is_dir():
            outcome["reason"] = "project_tool_or_cwd_unavailable; prepare explicitly"
        else:
            try:
                with heavy_work(f"native check {stage['id']}") as work:
                    queue_seconds = getattr(work, "queue_seconds", 0.0)
                    if isinstance(queue_seconds, (int, float)):
                        outcome["queue_ms"] = round(queue_seconds * 1000, 3)
                    result = work.run([str(executable), *stage["argv"][1:]], cwd=cwd, env=environment,
                                      capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=stage.get("timeout_seconds", 600), check=False)
                output = "\n".join(part for part in (result.stdout, result.stderr) if part)
                stdout_output = result.stdout
                unavailable = result.returncode == 127 or "NATIVE_UNAVAILABLE:" in output
                outcome.update(returncode=result.returncode, state="unavailable" if unavailable else "pass" if result.returncode == 0 else "fail")
                if unavailable:
                    outcome["reason"] = next((line for line in output.splitlines() if "NATIVE_UNAVAILABLE:" in line), "project_preparation_unavailable")
                if evidence is not None and not unavailable:
                    if report is not None:
                        if not report.is_file() or report.stat().st_mtime_ns == previous or not report.resolve().is_relative_to(root.resolve()):
                            raise NativeCheckError("required evidence unavailable, stale or outside project")
                        report_bytes = report.read_bytes()
                        content = report_bytes.decode("utf-8")
                        outcome["artifacts"].append({"path": report.relative_to(root).as_posix(), "state": "present",
                                                     "size": len(report_bytes), "sha256": hashlib.sha256(report_bytes).hexdigest()})
                    else:
                        content = output if evidence.get("source") == "combined" else result.stdout
                        outcome["artifacts"].append({"path": evidence.get("source", "stdout"), "state": "present", "size": len(content.encode()),
                                                     "sha256": hashlib.sha256(content.encode()).hexdigest()})
                    counts = _counts(evidence, content)
                    outcome["counts"] = counts
                    if counts.get("not_applicable", 0):
                        outcome["not_applicable_tests"] = evidence["not_applicable_tests"]
                    if counts["failed"]:
                        outcome.update(state="fail", reason="evidence_records_failures")
                    elif outcome["state"] == "pass" and stage["kind"] == "test" and (not counts["executed"] or counts["skipped"] > counts.get("not_applicable", 0)):
                        outcome.update(state="unavailable", reason="empty_or_skipped_required_tests")
            except subprocess.TimeoutExpired:
                outcome.update(state="fail", reason="stage_timeout", returncode=124)
            except (OSError, ValueError, ET.ParseError) as exc:
                outcome.update(state="fail" if outcome["returncode"] else "unavailable", reason=str(exc))
        outcome.update(duration_ms=round((time.monotonic() - started) * 1000, 3),
                       output_bytes=len(output.encode()), detail=output[-1200:],
                       output_sha256=hashlib.sha256(output.encode()).hexdigest(), reused=False)
        if output:
            outcome["artifacts"].append({"path": "output", "state": "present", "size": len(output.encode()), "sha256": outcome["output_sha256"]})
        if artifact_store is not None:
            _retain_artifacts(root, artifact_store, outcome, stdout_output, output)
        if cache is not None and stage["coverage"] == "full" and (
                outcome["state"] == "pass" or _deterministic_failure(outcome)):
            passed_stages.append((stage, outcome))
        outcomes.append(outcome)
    full = full_gate and stage_id is None and all(stage["coverage"] == "full" for stage in stages if stage["required"])
    changed = False
    if before is not None:
        try:
            changed = _native_source(root) != before
        except (AcceptanceError, OSError):
            changed = True
        if changed:
            for outcome in outcomes:
                if outcome["state"] == "pass":
                    outcome.update(state="fail", reason="source_inputs_changed_during_native_check")
    if cache is not None and passed_stages and not changed:
        _save_stages(root, cache, passed_stages)
    passed = all(outcome["state"] == "pass" for outcome in outcomes if outcome["required"])
    return {"schema_version": 1, "coverage": "full" if full else "focused",
            "state": "pass" if passed else "fail", "stages": outcomes}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _native_source(root: Path) -> dict[str, Any]:
    from cli.lib.acceptance import (
        _git_value,
        _local_gate_inputs,
        _workspace_fingerprint,
        working_source_materialization_identity,
        working_source_mode_identity,
    )

    status, workspace = _workspace_fingerprint(root)
    return {"commit": _git_value(root, ["rev-parse", "--verify", "HEAD^{commit}"], "source unavailable"),
            "tree": _git_value(root, ["rev-parse", "--verify", "HEAD^{tree}"], "tree unavailable"),
            "clean": not status, "workspace_fingerprint": workspace, "local_inputs": _local_gate_inputs(root),
            "source_modes": working_source_mode_identity(root),
            "materialization": working_source_materialization_identity(root)}


def _glob_pattern(pattern: str) -> re.Pattern[str]:
    """Path glob: ``**`` spans directories, ``*`` and ``?`` stay within one."""
    pattern = pattern.rstrip("/")
    expression = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            expression += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            expression += ".*"
            index += 2
        elif pattern[index] == "*":
            expression += "[^/]*"
            index += 1
        elif pattern[index] == "?":
            expression += "[^/]"
            index += 1
        else:
            expression += re.escape(pattern[index])
            index += 1
    # A literal directory also selects everything beneath it.
    return re.compile(expression + "(?:/.*)?" if not pattern.endswith("*") else expression)


def _selected(path: str, patterns: list[str]) -> bool:
    return any(_glob_pattern(pattern).fullmatch(path) for pattern in patterns)


def stage_inputs(stage: dict[str, Any], tree: dict[str, tuple[str, str]]) -> list[str]:
    """Tracked paths a stage declares as its inputs; empty means the whole tree."""
    inputs, exclude = stage.get("inputs") or [], stage.get("exclude") or []
    return sorted(path for path in tree if _selected(path, inputs) and not _selected(path, exclude))


def _stage_key(root: Path, cache: dict[str, Any], plan: dict[str, Any], stage: dict[str, Any]) -> str:
    """Whole-tree stages bind the tree; declared stages bind only their inputs.

    A declared key covers the stage declaration and tools, the Git OIDs, modes
    and checkout bytes of its input paths, locks among its inputs, prepared
    environments it runs in, local gate configuration and the gate version.
    """
    if not stage.get("inputs"):
        return cache["key"]
    from cli.lib.acceptance import _materialization_identity, _materialized_source_entries

    tree = cache["tree"]
    selected = stage_inputs(stage, tree)
    executable = stage["executable"]
    cwd = stage["cwd"].rstrip("/")
    environments = [item for item in plan["prepared_environment"]
                    if cwd in {".", ""} or item["path"] == cwd or item["path"].startswith(cwd + "/")
                    or executable.startswith(item["path"].rstrip("/") + "/")]
    return _digest({
        "schema_version": 2, "stage": stage, "implementation": cache["implementation"],
        "inputs": {path: tree[path] for path in selected},
        "materialization": _materialization_identity(_materialized_source_entries(root, selected)),
        "locks": [lock for lock in plan["locks"] if _selected(lock["path"], stage["inputs"])],
        "prepared_environment": environments, "tools": plan["tools"], "paths": plan["paths"],
        "environment": plan["environment"], "local_inputs": cache["source"]["local_inputs"],
    })


def _stage_cache(root: Path, plan: dict[str, Any], source: dict[str, Any] | None) -> dict[str, Any] | None:
    from cli.lib.acceptance import AcceptanceError, _git_common_dir, _source_tree_entries

    try:
        if source is None or not source["clean"]:
            return None
        directory = _git_common_dir(root) / "st" / "native-stages"
        directory.mkdir(parents=True, exist_ok=True)
        implementation = _native_implementation()
        # The tree, not the commit: a commit with an identical tree reuses.
        whole_tree = {key: value for key, value in source.items() if key != "commit"}
        cache = {"directory": directory, "source": source, "plan": _digest(plan), "implementation": implementation,
                 "key": _digest({"source": whole_tree, "plan": plan, "implementation": implementation}),
                 "tree": _source_tree_entries(root, "HEAD") if any(stage.get("inputs") for stage in plan["stages"]) else {}}
        cache["stage_keys"] = {stage["id"]: _stage_key(root, cache, plan, stage) for stage in plan["stages"]}
        return cache
    except (AcceptanceError, OSError):
        # A non-Git/dirty project can still run fresh checks; only exact clean
        # source proofs are reusable. Cache failure must never skip a check.
        return None


def _artifact_storage(root: Path) -> dict[str, Any] | None:
    from cli.lib.acceptance import AcceptanceError, _git_common_dir

    try:
        directory = _git_common_dir(root) / "st" / "native-stages"
        directory.mkdir(parents=True, exist_ok=True)
        return {"directory": directory}
    except (AcceptanceError, OSError):
        return None


def _native_implementation() -> str:
    from cli.lib.acceptance import GATE_VERSION

    return _digest({"gate_version": GATE_VERSION})


def _reuse_stage(cache: dict[str, Any] | None, stage: dict[str, Any]) -> dict[str, Any] | None:
    # The cache key was derived once from this run's source, plan and gate.
    # Source drift during the run fails every passed or reused stage at the end.
    if cache is None or stage["coverage"] != "full":
        return None
    key = cache["stage_keys"][stage["id"]]
    path = cache["directory"] / f"{key}-{stage['id']}.json"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        digest = receipt.pop("digest")
        outcome = receipt["outcome"]
        if digest != _digest(receipt) or receipt["key"] != key or receipt["schema_version"] != 1:
            return None
        if outcome["state"] != "pass" or outcome["coverage"] != "full" or outcome["returncode"] != 0 or outcome["command"] != stage["argv"] or any(outcome[key] != stage[key] for key in ("id", "cwd", "required", "tool")):
            return None
        if stage["kind"] == "test" and (outcome["counts"]["executed"] < 1 or outcome["counts"]["failed"] or outcome["counts"]["skipped"] > outcome["counts"].get("not_applicable", 0)):
            return None
        if stage.get("evidence") and not outcome["artifacts"]:
            return None
        for artifact in outcome["artifacts"]:
            retained = cache["directory"] / "artifacts" / artifact["sha256"]
            if hashlib.sha256(retained.read_bytes()).hexdigest() != artifact["sha256"]:
                return None
        return outcome
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _retain_artifacts(root: Path, cache: dict[str, Any], outcome: dict[str, Any], stdout: str, output: str) -> None:
    try:
        for artifact in outcome["artifacts"]:
            content = (stdout.encode() if artifact["path"] == "stdout" else output.encode()
                       if artifact["path"] in {"combined", "output"} else _local(root, artifact["path"]).read_bytes())
            if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
                continue
            directory = cache["directory"] / "artifacts"
            directory.mkdir(exist_ok=True)
            retained = directory / artifact["sha256"]
            retained.write_bytes(content)
            artifact["retained_path"] = str(retained)
    except (NativeCheckError, OSError):
        return


# A stage failing identically this many times on one key is reported from the
# record instead of rerun; ``--no-reuse`` (or ST_NATIVE_NO_REUSE=1) retries.
_FAILURE_REPEATS = 2


def _deterministic_failure(outcome: dict[str, Any]) -> bool:
    """A completed run whose own evidence failed; never timeouts or unavailability."""
    return (outcome["state"] == "fail" and type(outcome.get("returncode")) is int
            and outcome["returncode"] > 0 and outcome["returncode"] != 124 and outcome.get("reason") != "stage_timeout")


def _failure_path(cache: dict[str, Any], stage: dict[str, Any]) -> Path:
    return cache["directory"] / f"{cache['stage_keys'][stage['id']]}-{stage['id']}.failure.json"


def _prior_failure(cache: dict[str, Any] | None, stage: dict[str, Any]) -> dict[str, Any] | None:
    if cache is None or stage["coverage"] != "full":
        return None
    try:
        record = json.loads(_failure_path(cache, stage).read_text(encoding="utf-8"))
        digest = record.pop("digest")
        outcome = record["outcome"]
        if (digest != _digest(record) or record["schema_version"] != 1 or record["key"] != cache["stage_keys"][stage["id"]]
                or record["repeats"] < _FAILURE_REPEATS or not _deterministic_failure(outcome)
                or outcome["id"] != stage["id"] or outcome["command"] != stage["argv"]):
            return None
        return {**outcome, "reason": f"identical_inputs_failed_{record['repeats']}x:{outcome.get('reason') or 'failed'}; "
                                     "rerun with --no-reuse to retry"}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _save_stages(root: Path, cache: dict[str, Any], observed: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    from cli.lib.acceptance import AcceptanceError, _write_receipt

    try:
        # Tool/config/lock/environment identities must still match after
        # execution; the caller already rechecked the complete tracked source.
        if _digest(native_plan(root)) != cache["plan"] or _native_implementation() != cache["implementation"]:
            return
        for stage, outcome in observed:
            key = cache["stage_keys"][stage["id"]]
            failure = _failure_path(cache, stage)
            if outcome["state"] != "pass":
                try:
                    previous = json.loads(failure.read_text(encoding="utf-8"))
                    repeats = int(previous["repeats"]) + 1 if previous.get("key") == key else 1
                except (OSError, ValueError, TypeError, KeyError):
                    repeats = 1
                record = {"schema_version": 1, "key": key, "repeats": repeats, "outcome": outcome}
                record["digest"] = _digest(record)
                _write_receipt(failure, record)
                continue
            failure.unlink(missing_ok=True)
            if any(not artifact.get("retained_path") or hashlib.sha256(Path(artifact["retained_path"]).read_bytes()).hexdigest() != artifact["sha256"]
                   for artifact in outcome["artifacts"]):
                continue
            receipt = {"schema_version": 1, "key": key, "outcome": outcome}
            receipt["digest"] = _digest(receipt)
            _write_receipt(cache["directory"] / f"{key}-{stage['id']}.json", receipt)
    except (AcceptanceError, NativeCheckError, OSError):
        return


def transfer_native_stage_receipts(source: Path, destination: Path) -> None:
    """Retain successful observations, not acceptance, across private attempts.

    Admission still requires the exact source/plan/implementation cache key and
    artifact checks in _reuse_stage. Malformed or incomplete observations never
    become reuse candidates. No directories, symlinks, or arbitrary paths cross.
    """
    from cli.lib.acceptance import _write_receipt

    if not source.is_dir():
        return
    for path in source.glob("*.json"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            digest = receipt.pop("digest")
            outcome = receipt["outcome"]
            key = receipt["key"]
            stage_id = outcome["id"]
            if (digest != _digest(receipt) or receipt["schema_version"] != 1
                    or not re.fullmatch(r"[0-9a-f]{64}", key)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", stage_id)
                    or path.name != f"{key}-{stage_id}.json"
                    or outcome["state"] != "pass" or outcome["coverage"] != "full" or outcome["returncode"] != 0):
                continue
            artifacts = []
            for artifact in outcome["artifacts"]:
                sha = artifact["sha256"]
                if not re.fullmatch(r"[0-9a-f]{64}", sha):
                    raise ValueError("invalid artifact identity")
                retained = source / "artifacts" / sha
                if retained.is_symlink():
                    raise ValueError("linked artifact")
                content = retained.read_bytes()
                if hashlib.sha256(content).hexdigest() != sha:
                    raise ValueError("artifact changed")
                artifacts.append((sha, content))
            destination.mkdir(parents=True, exist_ok=True)
            storage = destination / "artifacts"
            storage.mkdir(exist_ok=True)
            for sha, content in artifacts:
                with tempfile.NamedTemporaryFile("wb", dir=storage, delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(content)
                temporary.replace(storage / sha)
            _write_receipt(destination / path.name, {**receipt, "digest": digest})
        except (OSError, ValueError, TypeError, KeyError):
            continue
