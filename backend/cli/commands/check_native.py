"""Versioned, explicitly prepared project-native quality stages."""

from __future__ import annotations

import hashlib
import json
import os
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

_CONTENT_HASHES: dict[tuple[int, int, int, int, int], str] = {}


def _content_hash(path: Path) -> str:
    info = path.stat()
    key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if key not in _CONTENT_HASHES:
        with path.open("rb") as stream:
            _CONTENT_HASHES[key] = hashlib.file_digest(stream, "sha256").hexdigest()
    return _CONTENT_HASHES[key]


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


def _environment_identity(root: Path, path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return identity(root, path)
    entries = []
    seen: set[tuple[int, int]] = set()
    try:
        for directory, subdirs, files in os.walk(path, followlinks=True):
            current = Path(directory)
            info = current.stat()
            if (info.st_dev, info.st_ino) in seen:
                subdirs[:] = []
                continue
            seen.add((info.st_dev, info.st_ino))
            # Prepared executable caches can be consumed by tool runtimes.
            # Bind them conservatively; native Python writes to a fresh prefix.
            subdirs[:] = sorted(subdirs)
            for name in subdirs:
                candidate = current / name
                if candidate.is_symlink():
                    entries.append({"path": candidate.relative_to(path).as_posix(), "state": "present", "kind": "directory_link", "target": os.readlink(candidate)})
            for name in sorted(files):
                candidate = current / name
                item = identity(path, candidate)
                if item["state"] != "present":
                    raise OSError("prepared environment entry unavailable")
                entries.append(item)
        return {"path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
                "state": "present", "file_count": len(entries), "sha256": _digest(entries)}
    except OSError:
        return {"path": str(path), "state": "unavailable"}


def native_plan(root: Path) -> dict[str, Any] | None:
    """Load declarations strictly; legacy projects remain on their existing gate."""
    config = root / ".st-check.toml"
    if not config.exists():
        return None
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise NativeCheckError(f"invalid .st-check.toml: {exc}") from exc
    native = data.get("native")
    if native is None:
        return None
    if not isinstance(native, dict) or native.get("schema_version") != 1:
        raise NativeCheckError("native.schema_version must be 1")
    locks = native.get("locks")
    paths = native.get("paths", [])
    tools = native.get("tools", {})
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
        ids.add(stage_id)
        normalized.append({**stage, "id": stage_id, "argv": argv, "cwd": cwd, "kind": kind,
                           "coverage": coverage, "required": required, "applicable": applicable,
                           "tool": identity(root, executable),
                           "executable": executable.relative_to(root).as_posix() if executable.is_relative_to(root) else str(executable)})
    if not any(stage["required"] for stage in normalized):
        raise NativeCheckError("native plan must include a required stage")
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
            "prepared_environment": [_environment_identity(root, path) for path in sorted(runtime_paths)],
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
    host_scratch = os.environ.get("ST_NATIVE_TMP_HOST_ROOT")
    with tempfile.TemporaryDirectory(prefix="", dir=host_scratch) as directory:
        aliases = Path(directory) / "bin"
        aliases.mkdir(mode=0o700)
        for name, tool in plan["tools"].items():
            target = Path(tool["path"])
            (aliases / name).symlink_to(target if target.is_absolute() else _local(root, tool["path"]))
        return _run_native(root, plan, aliases=aliases, stage_id=stage_id, reuse=reuse, full_gate=full_gate)


def _run_native(root: Path, plan: dict[str, Any], *, aliases: Path, stage_id: str | None, reuse: bool, full_gate: bool) -> dict[str, Any]:
    from cli.lib.acceptance import AcceptanceError

    stages = [stage for stage in plan["stages"] if stage_id is None or stage["id"] == stage_id]
    if not stages:
        raise NativeCheckError(f"unknown native stage: {stage_id}")
    temporary = aliases.parent
    environment = {"HOME": str(root), "LANG": "C.UTF-8", "CI": "true",
                   "XDG_CONFIG_HOME": str(aliases / "config"), "XDG_DATA_HOME": str(aliases / "data"),
                   "XDG_CACHE_HOME": str(aliases / "cache"), "XDG_STATE_HOME": str(aliases / "state"), **plan["environment"],
                   "TMPDIR": str(temporary), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(aliases / "pycache"),
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
    cache = _stage_cache(root, plan) if stage_id is None and full_gate else None
    artifact_store = cache or _artifact_storage(root)
    for stage in stages:
        started = time.monotonic()
        cached = _reuse_stage(root, cache, stage) if reuse else None
        if cached is not None:
            outcomes.append({**cached, "reused": True, "reuse_lookup_ms": round((time.monotonic() - started) * 1000, 3)})
            continue
        outcome: dict[str, Any] = {"id": stage["id"], "coverage": stage["coverage"], "required": stage["required"],
                                   "command": stage["argv"], "cwd": stage["cwd"], "tool": stage["tool"], "artifacts": [],
                                   "state": "unavailable", "returncode": None, "reason": ""}
        evidence = stage.get("evidence")
        report = _local(root, evidence["path"]) if evidence and evidence.get("source", "file") == "file" else None
        previous = report.stat().st_mtime_ns if report is not None and report.is_file() else None
        cwd = _local(root, stage["cwd"])
        executable = Path(stage["executable"]) if Path(stage["executable"]).is_absolute() else _local(root, stage["executable"])
        output = ""
        stdout_output = ""
        if not stage["applicable"]:
            outcome.update(state="not-applicable", reason=stage["reason"])
        elif any(lock["state"] != "present" for lock in [*plan["locks"], *plan["prepared_environment"]]):
            outcome["reason"] = "locked_environment_unavailable; prepare explicitly"
        elif not executable.is_file() or not os.access(executable, os.X_OK) or not cwd.is_dir():
            outcome["reason"] = "project_tool_or_cwd_unavailable; prepare explicitly"
        else:
            try:
                with heavy_work(f"native check {stage['id']}") as work:
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
        if cache is not None and outcome["state"] == "pass" and stage["coverage"] == "full":
            _save_stage(root, cache, stage, outcome)
        outcomes.append(outcome)
    full = full_gate and stage_id is None and all(stage["coverage"] == "full" for stage in stages if stage["required"])
    if before is not None:
        try:
            changed = _native_source(root) != before
        except (AcceptanceError, OSError):
            changed = True
        if changed:
            for outcome in outcomes:
                if outcome["state"] == "pass":
                    outcome.update(state="fail", reason="source_inputs_changed_during_native_check")
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


def _stage_cache(root: Path, plan: dict[str, Any]) -> dict[str, Any] | None:
    from cli.lib.acceptance import AcceptanceError, _git_common_dir

    try:
        source = _native_source(root)
        if not source["clean"]:
            return None
        directory = _git_common_dir(root) / "st" / "native-stages"
        directory.mkdir(parents=True, exist_ok=True)
        implementation = _native_implementation()
        return {"directory": directory, "source": source, "plan": _digest(plan), "implementation": implementation,
                "key": _digest({"source": source, "plan": plan, "implementation": implementation})}
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
    from app.utils import heavy_work as admission
    from app.utils import safe_subprocess
    from cli.lib import acceptance

    return _digest({name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ("native", __file__), ("source", acceptance.__file__),
        ("admission", admission.__file__), ("subprocess", safe_subprocess.__file__),
    )})


def _reuse_stage(root: Path, cache: dict[str, Any] | None, stage: dict[str, Any]) -> dict[str, Any] | None:
    if cache is None or stage["coverage"] != "full":
        return None
    path = cache["directory"] / f"{cache['key']}-{stage['id']}.json"
    try:
        from cli.lib.acceptance import AcceptanceError

        if _native_source(root) != cache["source"] or _digest(native_plan(root)) != cache["plan"] or _native_implementation() != cache["implementation"]:
            return None
        receipt = json.loads(path.read_text(encoding="utf-8"))
        digest = receipt.pop("digest")
        outcome = receipt["outcome"]
        if digest != _digest(receipt) or receipt["key"] != cache["key"] or receipt["schema_version"] != 1:
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
    except (AcceptanceError, OSError, ValueError, TypeError, KeyError):
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


def _save_stage(root: Path, cache: dict[str, Any], stage: dict[str, Any], outcome: dict[str, Any]) -> None:
    from cli.lib.acceptance import AcceptanceError, _write_receipt

    try:
        # Tool/config/lock/environment and complete tracked source identities
        # must still match after execution; no partial/transitive-source claims.
        if _native_source(root) != cache["source"] or _digest(native_plan(root)) != cache["plan"] or _native_implementation() != cache["implementation"]:
            return
        for artifact in outcome["artifacts"]:
            if not artifact.get("retained_path") or hashlib.sha256(Path(artifact["retained_path"]).read_bytes()).hexdigest() != artifact["sha256"]:
                return
        receipt = {"schema_version": 1, "key": cache["key"], "outcome": outcome}
        receipt["digest"] = _digest(receipt)
        _write_receipt(cache["directory"] / f"{cache['key']}-{stage['id']}.json", receipt)
    except (AcceptanceError, NativeCheckError, OSError):
        return
