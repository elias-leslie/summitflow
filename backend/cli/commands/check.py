"""Canonical quality-check command surface."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import resource
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import typer

from app.utils.heavy_work import HeavyWork, heavy_work

from ..details import detail_path, display_path, summary_hint, write_details
from ..lib import ci_parity, remote_runner
from ..lib.acceptance import AcceptanceError
from ..lib.architecture_check import run_architecture_check
from ..lib.cleanroom import main as cleanroom_main
from ..lib.task_claims import TaskClaimRenewalError, renew_owned_claim
from ..lib.usage import usage
from ..output import output_error
from .check_artifacts import write_check_details
from .check_changed import (
    _changed_args,
    _changed_files,
    _pytest_requires_full_scope,
    _skip_reason,
)
from .check_codeql import (
    _emit_codeql_result,
    _fetch_codeql_alerts,
    _fetch_codeql_ref,
    _fetch_codeql_repo,
    _parse_codeql_args,
)
from .check_constants import _FIX_ARGS, _TOOL_SELECTIONS
from .check_dispatch import (
    CheckRuntime,
    extract_check_options,
    handle_check_args,
    help_text,
    run_named_tool,
    run_selected,
    selected_tool_args,
)
from .check_execution import (
    adjusted_tool_args,
    missing_tool_skip,
    read_tool_paths,
    tool_env,
    tool_not_installed,
    tool_output,
    tool_paths,
    tool_result_line,
)
from .check_native import (
    NativeCheckError,
    blocked_native_result,
    legacy_applicability,
    native_plan,
    run_native,
)
from .check_project_identity import run_project_identity_check
from .check_runner import (
    _normalize_explicit_args,
    _resolve_repo_root,
    _tool_configs,
    _workdir,
)
from .check_security import run_local_security_check

if TYPE_CHECKING:
    from ..lib.acceptance_coordinator import Materialization

app = typer.Typer(
    help=(
        "Quality checks through st. Use st check for repo gates; never run raw "
        "pytest, Vitest, Biome, TSC, Ruff, SQLFluff, Squawk, or legacy dt first."
    ),
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
    add_help_option=False,
)


def _resolve_command(binary: str, root: Path, cwd: Path, base_args: list[str], *,
                     search_path: str | None = None) -> list[str]:
    """Project-local tools first, then PATH (or the acceptance gate's fixed lookup path)."""
    # npx foo -> search node_modules for foo, not for npx itself.
    if binary == "npx" and base_args:
        tool = base_args[0]
        if tool == "biome" and "biome" in (declared_paths := read_tool_paths(root)):
            declared = declared_paths["biome"]
            declared_candidate = root / declared / tool
            if declared and declared_candidate.is_file():
                return [str(declared_candidate), *base_args[1:]]
            # Preserve the declared path as authoritative, including an empty
            # declaration. The caller reports the missing binary before npx.
            return [shutil.which("npx", path=search_path) or "npx", "--no-install", *base_args]
        for search_root in (cwd, root / "frontend", root):
            npx_candidate = search_root / "node_modules" / ".bin" / tool
            if npx_candidate.exists():
                return [str(npx_candidate), *base_args[1:]]
        npx = shutil.which("npx", path=search_path)
        return [npx or "npx", "--no-install", *base_args]

    for search_root in (cwd, root / "frontend", root):
        for candidate in (
            search_root / "node_modules" / ".bin" / binary,
            search_root / ".venv" / "bin" / binary,
        ):
            if candidate.exists():
                return [str(candidate), *base_args]

    resolved = shutil.which(binary, path=search_path)
    return [resolved or binary, *base_args]


_FRONTEND_TEST_TIMEOUT = 600
# Seconds-scale linters that must not queue behind full suites and builds.
_LIGHT_TOOLS = frozenset({"ruff", "biome", "actionlint", "shellcheck", "squawk"})
# Name the admission holder in result lines once queueing becomes noticeable.
_QUEUE_NOTICE_MS = 1000.0
# Measured per project: a vitest suite whose last run took seconds and little
# memory (aico: 470 tests, 6.7 s, 164 MB peak) joins the light lane instead of
# queueing behind full suites. Unmeasured or larger suites stay heavy.
# Type checks of one file, or of a whole project that takes no paths (tsc),
# join it when the same scope last ran in about 2 s: a 0.08 s basedpyright
# check waited 66.9 s behind a full pytest suite in the heavy lane.
_MEASURED_LIGHT = {  # execution ms, peak child RSS KiB
    "vitest": (30_000.0, 1024 * 1024),
    "types": (2_000.0, 1024 * 1024),
    "tsc": (2_000.0, 1024 * 1024),
}
_SCOPED_MEASUREMENTS = frozenset({"types", "tsc"})


def _measurement_key(name: str, extra_args: Sequence[str] = ()) -> str | None:
    """Where a run's timing is kept; None when its scope is not lane-eligible."""
    if name not in _SCOPED_MEASUREMENTS:
        return name
    paths = sum(1 for arg in extra_args if arg and not arg.startswith("-"))
    return {0: f"{name}:project", 1: f"{name}:file"}.get(paths)


def _lane_measurements(root: Path) -> Path | None:
    state = root / ".git" / "st"
    return state / "lane-measurements.json" if state.is_dir() else None


def _measured_light(root: Path, name: str, extra_args: Sequence[str] = ()) -> bool:
    limits, path, key = _MEASURED_LIGHT.get(name), _lane_measurements(root), _measurement_key(name, extra_args)
    if limits is None or path is None or key is None:
        return False
    try:
        last = json.loads(path.read_text()).get(key) or {}
        return float(last["execution_ms"]) <= limits[0] and int(last["max_rss_kb"]) <= limits[1]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _record_measurement(root: Path, name: str, execution_ms: float, max_rss_kb: int, returncode: int,
                        extra_args: Sequence[str] = ()) -> None:
    path, key = _lane_measurements(root), _measurement_key(name, extra_args)
    if name not in _MEASURED_LIGHT or path is None or key is None or returncode not in {0, 1}:
        return
    try:
        values = json.loads(path.read_text()) if path.is_file() else {}
        values = values if isinstance(values, dict) else {}
        values[key] = {"execution_ms": round(execution_ms, 3), "max_rss_kb": max_rss_kb}
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(values, sort_keys=True))
        os.replace(temporary, path)
    except (OSError, ValueError):
        return


def _run_frontend_script(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Cap arbitrary manifest scripts and clean up their process group on timeout."""
    with heavy_work("frontend tests") as work:
        try:
            return work.run(
                command, cwd=cwd, env={**env, "CI": "true", "NODE_ENV": "test"},
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_FRONTEND_TEST_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
            return subprocess.CompletedProcess(
                command, 124, stdout, f"{stderr}\nFrontend tests exceeded {_FRONTEND_TEST_TIMEOUT}s; process group stopped."
            )


@contextmanager
def _tool_environment(root: Path, cwd: Path, name: str, *, parity: bool
                      ) -> Iterator[tuple[dict[str, str], ci_parity.CiJob | None, list[str]]]:
    """The host env for routine checks; a scrubbed CI-like env for acceptance."""
    if not parity:
        yield tool_env(root, os.environ, name), None, []
        return
    job = ci_parity.pytest_job(root, cwd) if name == "pytest" else None
    with ci_parity.scratch_directory() as scratch:
        env = ci_parity.environment(root, tool_dirs=tool_paths(root, name), job=job, scratch=scratch)
        if name in {"vitest", "frontend-test"}:
            env["NODE_ENV"] = "test"
        with ci_parity.services(job, env) as service_names:
            yield env, job, service_names


def _run_parity_pytest(work: HeavyWork, cwd: Path, command: list[str], extra_args: list[str],
                       job: ci_parity.CiJob | None, env: dict[str, str], report: Path | None,
                       service_names: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the CI job's own pytest invocation(s), with its migration steps first."""
    seed = ci_parity.seed()
    if job is None or not job.tests:
        commands, setup = [ci_parity.seeded(command, seed)], job.setup if job else []
    else:
        tests = [[*job.tests[0], *extra_args]] if extra_args else [list(argv) for argv in job.tests]
        commands, setup = [ci_parity.seeded(argv, seed) for argv in tests], job.setup
        if report is not None:
            commands[-1].append(f"--junitxml={report}")
    source = f"{job.workflow}:{job.name}" if job else "local-gate"
    print(f"CI_PARITY:pytest|job:{source}|seed:{seed if seed is not None else 'none'}"
          f"|services:{','.join(service_names) or 'none'}|repro:{ci_parity.repro_command(seed)}", flush=True)
    stdout: list[str] = []
    stderr: list[str] = []
    returncode = 0
    for argv in [*setup, *commands]:
        step = work.run(argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", check=False)
        stdout.append(step.stdout or "")
        stderr.append(step.stderr or "")
        returncode = returncode or step.returncode
        if returncode and argv in setup:
            break
    return subprocess.CompletedProcess(commands[-1], returncode, "\n".join(stdout), "\n".join(stderr))


def _run_on_ci_runner(
    root: Path, command: list[str], cwd: Path, report: Path | None,
) -> tuple[subprocess.CompletedProcess[str], str] | None:
    """Full suite on the Proxmox runner while the workstation is busy; None runs it locally."""
    offload = remote_runner.offload_reason(root)
    if offload is None:
        return None
    runner, reason = offload
    print(f"[st] {reason}; running on the CI runner", file=sys.stderr, flush=True)
    started = time.monotonic()
    try:
        result = remote_runner.run(runner, root, command, cwd=cwd, env=tool_env(root, os.environ, "pytest"),
                                   fetch=[report] if report is not None else [])
    except (remote_runner.RunnerUnavailable, OSError, subprocess.CalledProcessError) as exc:
        print(f"[st] CI runner unavailable ({exc}); running locally", file=sys.stderr, flush=True)
        return None
    return result, f"|runner:proxmox|execution_ms:{(time.monotonic() - started) * 1000:.3f}"


def _tool_failure(root: Path, label: str, name: str, output: str) -> int:
    """Record why a tool could not run and print its 127 result line."""
    details = write_check_details(root, name, output)
    print(tool_result_line(label, name, 127, display_path(root, details), summary_hint(output)))
    return 127


def _npx_preflight(name: str, binary: str, base_args: list[str], resolved_command: list[str],
                   root: Path, label: str) -> int | None:
    """Skip or fail an npx tsc/biome that would fall back to an uninstalled package; None runs it."""
    if (name == "tsc" and binary == "npx" and base_args[:1] == ["tsc"]
            and resolved_command[1:2] == ["--no-install"] and tool_not_installed(name, root)):
        # Without project node_modules, npx would run whatever cached package
        # is named `tsc` (an unrelated one): no type check ran, so skip.
        print(f"{label}:SKIP:{name}:{missing_tool_skip(name, root)}")
        return 0
    if (
        name == "biome"
        and binary == "npx"
        and base_args[:1] == ["biome"]
        and resolved_command[1:2] == ["--no-install"]
    ):
        if tool_not_installed(name, root):
            print(f"{label}:SKIP:{name}:{missing_tool_skip(name, root)}")
            return 0
        return _tool_failure(root, label, name, (
            "Biome is declared for this project, but no project-local "
            "node_modules/.bin/biome was found. Install the project's frontend "
            "dependencies or fix its .st-check.toml [paths].biome declaration."
        ))
    return None


def _add_pytest_report(root: Path, name: str, command: list[str]) -> Path | None:
    """Append --junitxml to `command` in place for pytest without a report; return the report path."""
    # A real full-suite failure produced empty stdout/stderr. Retain pytest's
    # built-in report from this same run, not a second diagnostic test run.
    pytest_options = " ".join([*command, os.environ.get("PYTEST_ADDOPTS", "")])
    if name != "pytest" or re.search(r"(?:^|\s)--junit-?xml(?:=|\s)|no:junitxml", pytest_options):
        return None
    report = detail_path(root, f"pytest-{uuid4().hex}").with_suffix(".xml")
    command.append(f"--junitxml={report}")
    return report


def _execute_tool(root: Path, cwd: Path, name: str, binary: str, base_args: list[str], command: list[str],
                  extra_args: list[str], report: Path | None) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the tool where it belongs and return its result with the timing suffix."""
    if name == "frontend-test":
        return _run_frontend_script(command, cwd, tool_env(root, os.environ, name)), ""
    queued = time.monotonic()
    # Only direct adapters of fast, low-memory linters are light.
    # Configured wrappers and all other tools retain the heavy default.
    direct = binary == name or (binary == "npx" and base_args[:1] == [name])
    work_class = "light" if (name in _LIGHT_TOOLS and direct) or _measured_light(root, name, extra_args) else "heavy"
    parity = ci_parity.active() and ci_parity.has_ci(root)
    remote = (_run_on_ci_runner(root, command, cwd, report)
              if name == "pytest" and work_class == "heavy" and not extra_args and not parity else None)
    if remote is not None:
        return remote
    with (heavy_work(f"check {name}", work_class=work_class, project=root.name) as work,
          _tool_environment(root, cwd, name, parity=parity) as (env, job, service_names)):
        started = time.monotonic()
        queue_ms = (started - queued) * 1000
        if parity and name == "pytest":
            result = _run_parity_pytest(work, cwd, command, extra_args, job, env, report, service_names)
        else:
            result = work.run(
                command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        execution_ms = (time.monotonic() - started) * 1000
        # Largest single child so far: conservative when earlier tools ran first.
        _record_measurement(root, name, execution_ms,
                            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, result.returncode, extra_args)
        timing = (f"|lane:{work.lane}|queue_ms:{queue_ms:.3f}"
                  f"|execution_ms:{execution_ms:.3f}")
        if work.waited_behind and queue_ms >= _QUEUE_NOTICE_MS:
            timing += f"|queued_behind:{work.waited_behind}"
    return result, timing


def _run_tool(name: str, config: dict[str, object], extra_args: list[str]) -> int:
    root = _resolve_repo_root()
    cwd = _workdir(root, config)
    binary = str(config.get("binary") or name)
    base_args = shlex.split(str(config.get("args") or ""))
    base_args, extra_args = adjusted_tool_args(name, base_args, extra_args, root)
    # Acceptance resolves gate binaries on a fixed path so its receipt names
    # the same tools whichever shell or worker validates it later.
    resolved_command = _resolve_command(binary, root, cwd, base_args,
                                        search_path=ci_parity.canonical_tool_path() if ci_parity.active() else None)
    command = [*resolved_command, *extra_args]
    label = str(config.get("label") or name.upper())
    print(f"{label}:{name}:start")
    preflight = _npx_preflight(name, binary=binary, base_args=base_args, resolved_command=resolved_command,
                               root=root, label=label)
    if preflight is not None:
        return preflight
    report = _add_pytest_report(root, name, command)
    try:
        result, timing = _execute_tool(root, cwd, name, binary=binary, base_args=base_args, command=command,
                                       extra_args=extra_args, report=report)
    except ci_parity.CiParityError as exc:
        return _tool_failure(root, label, name, f"CI parity unavailable: {exc}")
    except OSError as exc:
        if name not in {"vitest", "frontend-test"} and isinstance(exc, FileNotFoundError):
            # A missing tool skips when it was never installable, or when the
            # repo has none of its sources even though an environment exists.
            skip = missing_tool_skip(name, root)
            if skip == "no_relevant_paths" or tool_not_installed(name, root):
                print(f"{label}:SKIP:{name}:{skip}")
                return 0
        return _tool_failure(root, label, name, f"{type(exc).__name__}: {exc}")
    output = tool_output(result.stdout, result.stderr)
    if name == "pytest" and not output.strip():
        output = f"pytest exited {result.returncode} with no console output."
        if report is not None and not report.is_file():
            output += " The requested JUnit report was not written."
    details = write_check_details(root, name, output)
    print(
        tool_result_line(
            label,
            name,
            result.returncode,
            display_path(root, details),
            summary_hint(output),
        ) + timing + (f"|report:{display_path(root, report)}" if report is not None and report.is_file() else "")
    )
    return result.returncode


def _run_codeql_alert_check(args: list[str]) -> int:
    """Run the CodeQL alert check using this module's _resolve_repo_root (patchable by tests)."""
    explicit_ref, parse_code = _parse_codeql_args(args)
    if parse_code == -1:
        return 0
    if parse_code != 0:
        return parse_code
    root = _resolve_repo_root()
    repo = _fetch_codeql_repo(root)
    if repo is None:
        details = write_details(
            root,
            "codeql",
            "GitHub CLI is unavailable, unauthenticated, or cannot resolve this repository.",
        )
        print(
            f"CODEQL:FAIL:127|details:{display_path(root, details)}|"
            "hint:install/auth gh and run from a GitHub repository"
        )
        return 127
    ref = explicit_ref if explicit_ref is not None else _fetch_codeql_ref(root)
    alerts, error, exit_code = _fetch_codeql_alerts(root, repo, ref)
    return _emit_codeql_result(root, repo, ref, alerts, error, exit_code)


def _runtime() -> CheckRuntime:
    return CheckRuntime(
        fix_args=_FIX_ARGS,
        tool_selections=_TOOL_SELECTIONS,
        cleanroom_main=cleanroom_main,
        run_architecture_check=run_architecture_check,
        run_project_identity_check=run_project_identity_check,
        output_error=output_error,
        resolve_repo_root=_resolve_repo_root,
        workdir=_workdir,
        normalize_explicit_args=_normalize_explicit_args,
        changed_files=_changed_files,
        changed_args=_changed_args,
        pytest_requires_full_scope=_pytest_requires_full_scope,
        skip_reason=_skip_reason,
        run_tool=_run_tool,
        run_codeql_alert_check=_run_codeql_alert_check,
        run_local_security_check=run_local_security_check,
    )


def _extract_check_options(args: list[str]) -> tuple[list[str], bool, bool]:
    return extract_check_options(args)


def _run_selected(
    selected: list[str],
    configs: dict[str, dict[str, object]],
    *,
    fix: bool,
    changed_only: bool,
) -> int:
    return run_selected(selected, configs, fix=fix, changed_only=changed_only, runtime=_runtime())


def _selected_tool_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, object],
    changed_only: bool,
    fix: bool,
    args: list[str],
) -> tuple[list[str], bool]:
    return selected_tool_args(
        name,
        root,
        cwd,
        config,
        changed_only,
        fix,
        args,
        runtime=_runtime(),
    )


def _run_named_tool(
    first: str,
    args: list[str],
    configs: dict[str, dict[str, object]],
    *,
    changed_only: bool,
    fix: bool,
) -> int:
    return run_named_tool(
        first,
        args,
        configs,
        changed_only=changed_only,
        fix=fix,
        runtime=_runtime(),
    )


@app.callback(invoke_without_command=True)
def _help_text(names: str) -> str:
    return help_text(names)


def _acceptance_summary(receipt: dict[str, object]) -> str:
    source = receipt.get("source")
    source_commit = receipt.get("source_commit")
    if not source_commit and isinstance(source, dict):
        source_commit = cast(dict[str, object], source).get("commit")
    checks = receipt.get("checks")
    check_count = receipt.get("check_count")
    if check_count is None and isinstance(checks, list):
        check_count = len(checks)
    return "|".join(
        (
            f"ACCEPTANCE:state={receipt.get('state', 'unknown')}",
            f"source={source_commit or 'unknown'}",
            f"id={receipt.get('acceptance_id') or 'unknown'}",
            f"artifact={receipt.get('acceptance_artifact') or 'unknown'}",
            f"reused={str(bool(receipt.get('reused'))).lower()}",
            f"duration_ms={receipt.get('duration_ms', 'unknown')}",
            f"checks={check_count if check_count is not None else 'unknown'}",
        )
    )


def _handle_check_args(ctx: typer.Context, configs: dict[str, dict[str, object]]) -> int:
    args = list(ctx.args)
    mode = args[0] if args else None
    if mode in {"--native", "--check", "-c"}:
        code = _native_mode(args, configs)
        if code is not None:
            return code
    if mode == "--ci-repro":
        return _ci_repro(args[1:], configs)
    if mode == "budget":
        return _budget_mode(args)
    if mode == "--deep":
        return _deep_mode(args)
    if mode == "--acceptance":
        return _acceptance_mode(args)
    return handle_check_args(ctx, configs, runtime=_runtime())


def _native_options(args: list[str]) -> tuple[str | None, bool, bool]:
    """Return (stage_id, json_output, reuse) for a native gate invocation."""
    native_args = args[1:]
    json_output = "--json" in native_args
    reuse = "--no-reuse" not in native_args and os.environ.get("ST_NATIVE_NO_REUSE") != "1"
    native_args = [arg for arg in native_args if arg not in {"--json", "--no-reuse"}]
    if not native_args:
        return None, json_output, reuse
    if args[0] != "--native" or len(native_args) != 2 or native_args[0] != "--stage":
        raise NativeCheckError("native full gates do not accept scope/fix arguments; use --native --stage ID")
    return native_args[1], json_output, reuse


def _native_mode(args: list[str], configs: dict[str, dict[str, object]]) -> int | None:
    """Run a declared native gate; None lets an undeclared --check/-c fall through to the tool gates."""
    try:
        root = _resolve_repo_root()
        plan = native_plan(root)
        if plan is None:
            if args[0] == "--native":
                raise NativeCheckError("project has no versioned native stage declaration")
            return None
        stage_id, json_output, reuse = _native_options(args)
        full_gate = args[0] in {"--check", "-c"}
        legacy = _native_legacy_checks(root, plan, configs, print_output=not json_output) if full_gate and plan["legacy_tools"] else None
        result = (blocked_native_result(plan, "cheap_legacy_gate_failed") if legacy and legacy["state"] != "pass"
                  else run_native(root, plan, stage_id=stage_id, reuse=reuse, full_gate=full_gate))
        if legacy is not None:
            result["legacy"] = legacy
        if not json_output:
            for stage in result["stages"]:
                print(f"NATIVE:{stage['state']}:{stage['id']}|coverage:{stage['coverage']}|reason:{stage['reason']}")
        print("NATIVE_EVIDENCE:" + json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["state"] == "pass" else 1
    except NativeCheckError as exc:
        output_error(str(exc))
        return 2


def _budget_mode(args: list[str]) -> int:
    from cli.lib.quality_budget import BudgetConfigError, report
    try:
        return report(_resolve_repo_root(), json_output="--json" in args)
    except BudgetConfigError as exc:
        output_error(str(exc))
        return 2


def _deep_mode(args: list[str]) -> int:
    from cli.lib.deep_lane import DeepLaneError, run_deep
    try:
        result = run_deep(_resolve_repo_root())
    except DeepLaneError as exc:
        output_error(str(exc))
        return 2
    for stage in result["stages"]:
        print(f"DEEP:{stage['state']}:{stage['id']}|reason:{stage['reason']}|duration_ms:{stage['duration_ms']}")
        for line in stage["failures"]:
            print(f"  {line}")
    if "--json" in args:
        print("DEEP_EVIDENCE:" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["state"] == "pass" else 1


@dataclass
class _AcceptanceOptions:
    sha: str = "HEAD"
    task_id: str = ""
    scope: list[str] = field(default_factory=list)
    coverage: str = "full"
    required_stages: list[str] = field(default_factory=list)
    reuse: bool = True
    json_output: bool = False


def _parse_acceptance_args(args: list[str]) -> _AcceptanceOptions | int:
    """Parse the options after --acceptance; an int is the exit code to return instead (help or error)."""
    if any(option in {"-h", "--help"} for option in args):
        print(
            "Usage: st check --acceptance [--sha REV] [--task TASK] "
            "[--scope PATH] [--coverage full|task] [--stage ID] [--no-reuse] [--json]"
        )
        return 0
    options = _AcceptanceOptions()
    index = 0
    while index < len(args):
        option = args[index]
        if option == "--no-reuse":
            options.reuse = False
            index += 1
            continue
        if option == "--json":
            options.json_output = True
            index += 1
            continue
        if option not in {"--sha", "--task", "--scope", "--coverage", "--stage"} or index + 1 >= len(args):
            output_error(f"Unknown or incomplete st check --acceptance option: {option}")
            return 2
        value = args[index + 1]
        if option == "--sha":
            options.sha = value
        elif option == "--task":
            options.task_id = value
        elif option == "--coverage":
            if value not in {"task", "full"}:
                output_error("Acceptance coverage must be task or full")
                return 2
            options.coverage = value
        elif option == "--stage":
            options.required_stages.append(value)
        else:
            options.scope.append(value)
        index += 2
    return options


def _acceptance_materialization(root: Path, sha: str) -> Materialization:
    """A historical revision or a dirty tree is accepted in isolation; otherwise per the project's basis.

    A historical full acceptance needs no task: the isolated clone runs exactly
    that commit, which is what publishing an older accepted commit needs.
    """
    from cli.lib.acceptance_coordinator import select_materialization
    from cli.lib.commit_workflow import run_git
    selected = run_git(root, ["rev-parse", "--verify", f"{sha}^{{commit}}"])
    head = run_git(root, ["rev-parse", "HEAD"])
    historical = selected.returncode == 0 and head.returncode == 0 and selected.stdout.strip() != head.stdout.strip()
    dirty = run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    return select_materialization(root, dirty=historical or (dirty.returncode == 0 and bool(dirty.stdout.strip())))


def _acceptance_mode(args: list[str]) -> int:
    options = _parse_acceptance_args(args[1:])
    if isinstance(options, int):
        return options
    try:
        root = _resolve_repo_root()
        owned_task = None
        if options.task_id:
            owned_task = renew_owned_claim(root, options.task_id)
        from cli.lib.acceptance_coordinator import Coverage, accept_source
        materialization = _acceptance_materialization(root, options.sha)
        receipt = accept_source(root, sha=options.sha, materialization=materialization, task_id=options.task_id,
                                scope=options.scope, reuse=options.reuse, coverage=cast(Coverage, options.coverage),
                                required_stages=options.required_stages).to_dict()
        if owned_task and receipt.get("state") == "success":
            from cli.lib.task_claims import attach_owned_acceptance
            if not attach_owned_acceptance(root, owned_task, receipt):
                output_error("Acceptance artifact retained; task proof was not attached because the local claim/evidence changed or the API is remote. Reclaim and revalidate before completion.")
    except (AcceptanceError, TaskClaimRenewalError) as exc:
        output_error(str(exc))
        return 2
    if options.json_output:
        print("ACCEPTANCE:" + json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    else:
        print(_acceptance_summary(receipt))
    return 0 if receipt.get("state") == "success" else 1


def _ci_repro(args: list[str], configs: dict[str, dict[str, object]]) -> int:
    """Replay acceptance's tests in the working tree with CI's env and a given order seed."""
    if any(option in {"-h", "--help"} for option in args):
        print("Usage: st check --ci-repro [--seed N] [PYTEST_ARGS...]  "
              "(seed from the acceptance failure's `reproduce:` hint)")
        return 0
    seed: int | None = None
    if args[:1] == ["--seed"]:
        if len(args) < 2 or not args[1].isdigit():
            output_error("--seed needs the integer seed printed by acceptance")
            return 2
        seed, args = int(args[1]), args[2:]
    os.environ[ci_parity.PARITY_FLAG] = "1"
    os.environ[ci_parity.SEED_VAR] = str(seed if seed is not None else ci_parity.new_seed())
    root = _resolve_repo_root()
    try:
        plan = native_plan(root)
    except NativeCheckError as exc:
        output_error(str(exc))
        return 2
    if plan is not None:
        if args:
            output_error("native projects replay their declared test stages; pytest arguments are not accepted")
            return 2
        print(f"CI_PARITY:native|seed:{os.environ[ci_parity.SEED_VAR]}")
        result = run_native(root, plan, reuse=False, full_gate=True)
        for stage in result["stages"]:
            print(f"NATIVE:{stage['state']}:{stage['id']}|coverage:{stage['coverage']}|reason:{stage['reason']}")
        return 0 if result["state"] == "pass" else 1
    if "pytest" not in configs:
        output_error("no pytest check is configured")
        return 2
    return _run_tool("pytest", configs["pytest"], args)


def _native_legacy_checks(root: Path, plan: dict[str, object], configs: dict[str, dict[str, object]], *, print_output: bool) -> dict[str, object]:
    started = time.monotonic()
    selected, outcomes = legacy_applicability(root, cast(list[str], plan["legacy_tools"]))
    missing = [name for name in selected if name not in configs]
    outcomes.extend({"id": name, "state": "unavailable", "reason": "check_configuration_missing"} for name in missing)
    captured = io.StringIO()
    with redirect_stdout(captured):
        code = _run_selected([name for name in selected if name in configs], configs, fix=False, changed_only=False)
    output = captured.getvalue()
    if print_output:
        print(output, end="")
    for line in output.splitlines():
        skipped = re.search(r"^([^:]+):SKIP:([^:]+):(.+)$", line)
        if skipped:
            reason = skipped[3]
            applicable_skip = any(value in reason for value in ("no_local_rules", "no_candidate_lockfiles", "no_candidate_files", "no_tsconfig", "no_relevant_paths", "no_package_manifest"))
            outcomes.append({"id": skipped[2], "state": "not-applicable" if applicable_skip else "unavailable", "reason": reason})
        elif ":OK:" in line or ":FAIL:" in line:
            outcomes.append({"id": line.split(":", 1)[0].lower(), "state": "fail" if ":FAIL:" in line else "pass", "result": line})
    for name in selected:
        labels = {str(configs.get(name, {}).get("label") or name.upper())}
        if name == "security":
            labels = {"GITLEAKS", "SEMGREP", "OSV"}
        if any(not any(line.startswith(label + ":") and any(marker in line for marker in (":OK:", ":FAIL:", ":SKIP:")) for line in output.splitlines()) for label in labels):
            outcomes.append({"id": name, "state": "unavailable", "reason": "check_outcome_missing"})
    unavailable = bool(missing) or any(outcome["state"] == "unavailable" for outcome in outcomes)
    return {"coverage": "full", "state": "pass" if code == 0 and not unavailable else "fail", "stages": outcomes,
            "duration_ms": round((time.monotonic() - started) * 1000, 3), "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "detail": output[-1200:], "security_coverage": "local_candidate_codeql_equivalence_not_claimed"}


@usage(
    surface="st.check",
    cmd="st check --quick --changed-only",
    when="iterate on a failing check; st commit already runs the quick check",
    precautions=(
        "never raw pytest/vitest/biome/tsc/ruff/sqlfluff/squawk",
        "st check codeql: GitHub CodeQL alert state after code-scanning work",
    ),
    tier="mandate",
)
def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands."""
    if ctx.invoked_subcommand is not None:
        return
    raise typer.Exit(_handle_check_args(ctx, _tool_configs()))
