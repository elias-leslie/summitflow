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
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import cast
from uuid import uuid4

import typer

from app.utils.heavy_work import heavy_work

from ..details import detail_path, display_path, summary_hint, write_details
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


def _resolve_command(binary: str, root: Path, cwd: Path, base_args: list[str]) -> list[str]:
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
            return [shutil.which("npx") or "npx", "--no-install", *base_args]
        for search_root in (cwd, root / "frontend", root):
            npx_candidate = search_root / "node_modules" / ".bin" / tool
            if npx_candidate.exists():
                return [str(npx_candidate), *base_args[1:]]
        npx = shutil.which("npx")
        return [npx or "npx", "--no-install", *base_args]

    for search_root in (cwd, root / "frontend", root):
        for candidate in (
            search_root / "node_modules" / ".bin" / binary,
            search_root / ".venv" / "bin" / binary,
        ):
            if candidate.exists():
                return [str(candidate), *base_args]

    resolved = shutil.which(binary)
    return [resolved or binary, *base_args]


_FRONTEND_TEST_TIMEOUT = 600
# Seconds-scale linters that must not queue behind full suites and builds.
_LIGHT_TOOLS = frozenset({"ruff", "biome", "actionlint", "shellcheck", "squawk"})
# Name the admission holder in result lines once queueing becomes noticeable.
_QUEUE_NOTICE_MS = 1000.0
# Measured per project: a vitest suite whose last run took seconds and little
# memory (aico: 470 tests, 6.7 s, 164 MB peak) joins the light lane instead of
# queueing behind full suites. Unmeasured or larger suites stay heavy.
_MEASURED_LIGHT = {"vitest": (30_000.0, 1024 * 1024)}  # execution ms, peak child RSS KiB


def _lane_measurements(root: Path) -> Path | None:
    state = root / ".git" / "st"
    return state / "lane-measurements.json" if state.is_dir() else None


def _measured_light(root: Path, name: str) -> bool:
    limits, path = _MEASURED_LIGHT.get(name), _lane_measurements(root)
    if limits is None or path is None:
        return False
    try:
        last = json.loads(path.read_text()).get(name) or {}
        return float(last["execution_ms"]) <= limits[0] and int(last["max_rss_kb"]) <= limits[1]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _record_measurement(root: Path, name: str, execution_ms: float, max_rss_kb: int, returncode: int) -> None:
    path = _lane_measurements(root)
    if name not in _MEASURED_LIGHT or path is None or returncode not in {0, 1}:
        return
    try:
        values = json.loads(path.read_text()) if path.is_file() else {}
        values = values if isinstance(values, dict) else {}
        values[name] = {"execution_ms": round(execution_ms, 3), "max_rss_kb": max_rss_kb}
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


def _run_tool(name: str, config: dict[str, object], extra_args: list[str]) -> int:
    root = _resolve_repo_root()
    cwd = _workdir(root, config)
    binary = str(config.get("binary") or name)
    base_args = shlex.split(str(config.get("args") or ""))
    base_args, extra_args = adjusted_tool_args(name, base_args, extra_args, root)
    resolved_command = _resolve_command(binary, root, cwd, base_args)
    command = [*resolved_command, *extra_args]
    label = str(config.get("label") or name.upper())
    print(f"{label}:{name}:start")
    if (
        name == "biome"
        and binary == "npx"
        and base_args[:1] == ["biome"]
        and resolved_command[1:2] == ["--no-install"]
    ):
        if tool_not_installed(name, root):
            print(f"{label}:SKIP:{name}:{missing_tool_skip(name, root)}")
            return 0
        output = (
            "Biome is declared for this project, but no project-local "
            "node_modules/.bin/biome was found. Install the project's frontend "
            "dependencies or fix its .st-check.toml [paths].biome declaration."
        )
        details = write_check_details(root, name, output)
        print(tool_result_line(label, name, 127, display_path(root, details), summary_hint(output)))
        return 127
    report: Path | None = None
    timing = ""
    # A real full-suite failure produced empty stdout/stderr. Retain pytest's
    # built-in report from this same run, not a second diagnostic test run.
    pytest_options = " ".join([*command, os.environ.get("PYTEST_ADDOPTS", "")])
    if name == "pytest" and not re.search(r"(?:^|\s)--junit-?xml(?:=|\s)|no:junitxml", pytest_options):
        report = detail_path(root, f"pytest-{uuid4().hex}").with_suffix(".xml")
        command.append(f"--junitxml={report}")
    try:
        if name == "frontend-test":
            result = _run_frontend_script(command, cwd, tool_env(root, os.environ, name))
        else:
            queued = time.monotonic()
            # Only direct adapters of fast, low-memory linters are light.
            # Configured wrappers and all other tools retain the heavy default.
            direct = binary == name or (binary == "npx" and base_args[:1] == [name])
            work_class = "light" if (name in _LIGHT_TOOLS and direct) or _measured_light(root, name) else "heavy"
            with heavy_work(f"check {name}", work_class=work_class, project=root.name) as work:
                started = time.monotonic()
                queue_ms = (started - queued) * 1000
                result = work.run(
                    command,
                    cwd=cwd,
                    env=tool_env(root, os.environ, name),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                execution_ms = (time.monotonic() - started) * 1000
                # Largest single child so far: conservative when earlier tools ran first.
                _record_measurement(root, name, execution_ms,
                                    resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, result.returncode)
                timing = (f"|lane:{work.lane}|queue_ms:{queue_ms:.3f}"
                          f"|execution_ms:{execution_ms:.3f}")
                if work.waited_behind and queue_ms >= _QUEUE_NOTICE_MS:
                    timing += f"|queued_behind:{work.waited_behind}"
    except OSError as exc:
        if name not in {"vitest", "frontend-test"} and isinstance(exc, FileNotFoundError):
            # A missing tool skips when it was never installable, or when the
            # repo has none of its sources even though an environment exists.
            skip = missing_tool_skip(name, root)
            if skip == "no_relevant_paths" or tool_not_installed(name, root):
                print(f"{label}:SKIP:{name}:{skip}")
                return 0
        output = f"{type(exc).__name__}: {exc}"
        details = write_check_details(root, name, output)
        print(
            tool_result_line(
                label,
                name,
                127,
                display_path(root, details),
                summary_hint(output),
            )
        )
        return 127
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
    if args and args[0] in {"--native", "--check", "-c"}:
        try:
            root = _resolve_repo_root()
            plan = native_plan(root)
            if plan is not None:
                stage_id = None
                native_args = args[1:]
                json_output = "--json" in native_args
                native_reuse = "--no-reuse" not in native_args and os.environ.get("ST_NATIVE_NO_REUSE") != "1"
                native_args = [arg for arg in native_args if arg not in {"--json", "--no-reuse"}]
                if native_args:
                    if args[0] != "--native" or len(native_args) != 2 or native_args[0] != "--stage":
                        raise NativeCheckError("native full gates do not accept scope/fix arguments; use --native --stage ID")
                    stage_id = native_args[1]
                full_gate = args[0] in {"--check", "-c"}
                legacy = _native_legacy_checks(root, plan, configs, print_output=not json_output) if full_gate and plan["legacy_tools"] else None
                result = (blocked_native_result(plan, "cheap_legacy_gate_failed") if legacy and legacy["state"] != "pass"
                          else run_native(root, plan, stage_id=stage_id, reuse=native_reuse, full_gate=full_gate))
                if legacy is not None:
                    result["legacy"] = legacy
                if not json_output:
                    for stage in result["stages"]:
                        print(f"NATIVE:{stage['state']}:{stage['id']}|coverage:{stage['coverage']}|reason:{stage['reason']}")
                print("NATIVE_EVIDENCE:" + json.dumps(result, sort_keys=True, separators=(",", ":")))
                return 0 if result["state"] == "pass" else 1
            if args[0] == "--native":
                raise NativeCheckError("project has no versioned native stage declaration")
        except NativeCheckError as exc:
            output_error(str(exc))
            return 2
    if args and args[0] == "--acceptance":
        if any(option in {"-h", "--help"} for option in args[1:]):
            print(
                "Usage: st check --acceptance [--sha REV] [--task TASK] "
                "[--scope PATH] [--coverage full|task] [--stage ID] [--no-reuse] [--json]"
            )
            return 0
        sha = "HEAD"
        task_id = ""
        scope: list[str] = []
        coverage = "full"
        required_stages: list[str] = []
        reuse = True
        json_output = False
        index = 1
        while index < len(args):
            option = args[index]
            if option == "--no-reuse":
                reuse = False
                index += 1
                continue
            if option == "--json":
                json_output = True
                index += 1
                continue
            if option not in {"--sha", "--task", "--scope", "--coverage", "--stage"} or index + 1 >= len(args):
                output_error(f"Unknown or incomplete st check --acceptance option: {option}")
                return 2
            value = args[index + 1]
            if option == "--sha":
                sha = value
            elif option == "--task":
                task_id = value
            elif option == "--coverage":
                if value not in {"task", "full"}:
                    output_error("Acceptance coverage must be task or full")
                    return 2
                coverage = value
            elif option == "--stage":
                required_stages.append(value)
            else:
                scope.append(value)
            index += 2
        try:
            root = _resolve_repo_root()
            owned_task = None
            if task_id:
                owned_task = renew_owned_claim(root, task_id)
            from cli.lib.acceptance_coordinator import Coverage, Materialization, accept_source
            from cli.lib.commit_workflow import run_git
            selected = run_git(root, ["rev-parse", "--verify", f"{sha}^{{commit}}"])
            head = run_git(root, ["rev-parse", "HEAD"])
            if (selected.returncode == 0 and head.returncode == 0 and selected.stdout.strip() != head.stdout.strip()
                    and (not task_id or not scope)):
                raise AcceptanceError("Historical acceptance requires --task and explicit --scope task-owned paths")
            dirty = run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"])
            materialization = "isolated" if dirty.returncode == 0 and dirty.stdout.strip() else "actual"
            if selected.returncode == 0 and head.returncode == 0 and selected.stdout.strip() != head.stdout.strip():
                materialization = "isolated"
            receipt = accept_source(root, sha=sha, materialization=cast(Materialization, materialization), task_id=task_id,
                                    scope=scope, reuse=reuse, coverage=cast(Coverage, coverage),
                                    required_stages=required_stages).to_dict()
            if owned_task and receipt.get("state") == "success":
                from cli.lib.task_claims import attach_owned_acceptance
                if not attach_owned_acceptance(root, owned_task, receipt):
                    output_error("Acceptance artifact retained; task proof was not attached because the local claim/evidence changed or the API is remote. Reclaim and revalidate before completion.")
        except (AcceptanceError, TaskClaimRenewalError) as exc:
            output_error(str(exc))
            return 2
        if json_output:
            print("ACCEPTANCE:" + json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        else:
            print(_acceptance_summary(receipt))
        return 0 if receipt.get("state") == "success" else 1
    return handle_check_args(ctx, configs, runtime=_runtime())


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
            applicable_skip = any(value in reason for value in ("no_local_rules", "no_candidate_lockfiles", "no_candidate_files", "no_tsconfig", "no_relevant_paths"))
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
    when="verify implementation changes; before committing or claiming a fix",
    precautions=(
        "never run raw pytest/vitest/biome/tsc/ruff/sqlfluff/squawk",
        "st check codeql verifies GitHub CodeQL alert state after code-scanning work",
    ),
    tier="mandate",
)
def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands."""
    if ctx.invoked_subcommand is not None:
        return
    raise typer.Exit(_handle_check_args(ctx, _tool_configs()))
