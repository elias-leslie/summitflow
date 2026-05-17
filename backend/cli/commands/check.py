"""Canonical quality-check command surface."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

import typer

from ..details import display_path, summary_hint, write_details
from ..lib.architecture_check import run_architecture_check
from ..lib.cleanroom import main as cleanroom_main
from ..lib.usage import usage
from ..output import output_error
from ..tool_registry import load_tool_registry

_TOOL_FILE_SUFFIXES: dict[str, set[str]] = {
    "pytest": {".py", ".pyi"},
    "types": {".py", ".pyi"},
    "ruff": {".py", ".pyi"},
    "biome": {
        ".css",
        ".js",
        ".json",
        ".jsonc",
        ".jsx",
        ".md",
        ".mdx",
        ".scss",
        ".ts",
        ".tsx",
    },
    "tsc": {".js", ".jsx", ".ts", ".tsx"},
    "vitest": {".js", ".jsx", ".ts", ".tsx"},
    "sqlfluff": {".sql"},
    "squawk": {".sql"},
}

_TOOL_CONFIG_PATHS: dict[str, set[str]] = {
    "pytest": {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"},
    "biome": {
        "biome.json",
        "biome.jsonc",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    },
    "tsc": {
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "tsconfig.build.json",
        "yarn.lock",
    },
    "vitest": {
        "package.json",
        "pnpm-lock.yaml",
        "vite.config.ts",
        "vitest.config.ts",
        "yarn.lock",
    },
}

_CODEQL_PAGE_SIZE = 100

_TOOL_SELECTIONS: dict[str, tuple[tuple[str, ...], bool]] = {
    "--fix": (("ruff", "biome"), True),
    "--check": (("ruff", "types", "pytest", "biome", "tsc", "vitest"), False),
    "-c": (("ruff", "types", "pytest", "biome", "tsc", "vitest"), False),
    "--quick": (("ruff", "types", "pytest", "biome", "tsc"), False),
    "-q": (("ruff", "types", "pytest", "biome", "tsc"), False),
    "--frontend-only": (("biome", "tsc", "vitest"), False),
    "--fe": (("biome", "tsc", "vitest"), False),
}

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


def _resolve_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return Path.cwd()


def _tool_configs() -> dict[str, dict[str, Any]]:
    registry = load_tool_registry()
    configs: dict[str, dict[str, Any]] = {}
    for item in registry.get("tools", []):
        if not isinstance(item, dict):
            continue
        config = item.get("check")
        if not isinstance(config, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            configs[name] = config
    return configs


def _workdir(root: Path, config: dict[str, Any]) -> Path:
    kind = str(config.get("working_dir") or "")
    backend = root / "backend"
    frontend = root / "frontend"
    candidates = {"backend": backend, "frontend": frontend}
    if kind in candidates and candidates[kind].exists():
        return candidates[kind]
    if kind == "migrations":
        return backend if (backend / "alembic").exists() else root
    if kind == "test" and backend.exists():
        return backend
    return root


def _changed_files(root: Path) -> list[str]:
    override = os.environ.get("ST_CHECK_CHANGED_FILES", "").strip()
    if override:
        return sorted(
            {
                item.strip()
                for line in override.splitlines()
                for item in line.split(os.pathsep)
                if item.strip()
            }
        )
    files: set[str] = set()
    for args in (
        ["diff", "--name-only", "HEAD"],
        ["diff", "--cached", "--name-only"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            files.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(files)


def _is_pytest_test_path(path: Path) -> bool:
    return path.suffix in {".py", ".pyi"} and (
        "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")
    )


def _path_relevant_for_tool(name: str, rel_path: str) -> bool:
    return _path_matches_tool(name, Path(rel_path))


def _relative_changed_paths(root: Path, cwd: Path, changed_files: list[str]) -> list[Path]:
    cwd_resolved = cwd.resolve()
    paths: list[Path] = []
    for rel_path in changed_files:
        absolute = (root / rel_path).resolve()
        if not absolute.exists() or not absolute.is_file():
            continue
        if not absolute.is_relative_to(cwd_resolved):
            continue
        relative = absolute.relative_to(cwd)
        if relative not in paths:
            paths.append(relative)
    return paths


def _path_matches_tool(name: str, path: Path) -> bool:
    if path.name in _TOOL_CONFIG_PATHS.get(name, set()):
        return True
    if name == "pytest":
        return _is_pytest_test_path(path)
    return path.suffix in _TOOL_FILE_SUFFIXES.get(name, set())


def _changed_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, Any],
    changed_files: list[str],
) -> list[str]:
    if not changed_files or (name != "pytest" and not config.get("pass_path")):
        return []
    paths: list[str] = []
    for relative in _relative_changed_paths(root, cwd, changed_files):
        if not _path_matches_tool(name, relative):
            continue
        if name in {"ruff", "types"} and relative.suffix not in {".py", ".pyi"}:
            continue
        if name in {"sqlfluff", "squawk"} and relative.suffix != ".sql":
            continue
        rel_posix = relative.as_posix()
        if rel_posix not in paths:
            paths.append(rel_posix)
    return paths


def _bin_candidates(search_root: Path, binary: str) -> list[Path]:
    return [
        search_root / "node_modules" / ".bin" / binary,
        search_root / ".venv" / "bin" / binary,
    ]


def _first_existing(paths: list[Path]) -> Path | None:
    for candidate in paths:
        if candidate.exists():
            return candidate
    return None


def _resolve_command(binary: str, root: Path, cwd: Path, base_args: list[str]) -> list[str]:
    # npx foo -> search node_modules for foo, not for npx itself.
    if binary == "npx" and base_args:
        tool = base_args[0]
        for search_root in (cwd, root / "frontend", root):
            npx_candidate = search_root / "node_modules" / ".bin" / tool
            if npx_candidate.exists():
                return [str(npx_candidate), *base_args[1:]]
        npx = shutil.which("npx")
        return [npx or "npx", "--no-install", *base_args]

    found = _first_existing(_bin_candidates(cwd, binary))
    if found:
        return [str(found), *base_args]

    for search_root in (root / "frontend", root):
        found = _first_existing(_bin_candidates(search_root, binary))
        if found:
            return [str(found), *base_args]

    resolved = shutil.which(binary)
    return [resolved or binary, *base_args]


def _normalize_explicit_args(root: Path, cwd: Path, args: list[str]) -> list[str]:
    normalized: list[str] = []
    cwd_resolved = cwd.resolve()
    for arg in args:
        if arg.startswith("-"):
            normalized.append(arg)
            continue
        candidate = (root / arg).resolve()
        if candidate.exists():
            normalized.append(
                candidate.relative_to(cwd_resolved).as_posix()
                if candidate.is_relative_to(cwd_resolved)
                else str(candidate)
            )
            continue
        normalized.append(arg)
    return normalized


def _extract_check_options(args: list[str]) -> tuple[list[str], bool, bool]:
    changed_only = False
    args = [
        arg
        for arg in args
        if not (arg in {"--changed-only", "-d"} and (changed_only := True))
    ]
    fix = "--fix" in args
    args = ["--fix"] if args == ["--fix"] else [arg for arg in args if arg != "--fix"]
    return (["--quick"] if changed_only and not args else args), changed_only, fix


def _skip_reason(
    name: str,
    config: dict[str, Any],
    *,
    changed_only: bool,
    changed_files: list[str],
    scoped_args: list[str],
    explicit_args: bool = False,
) -> str | None:
    if not changed_only or explicit_args:
        return None
    has_relevant = any(
        _path_relevant_for_tool(name, rel_path) for rel_path in changed_files
    )
    if config.get("pass_path"):
        if not scoped_args and not has_relevant:
            return "no_changed_paths"
        return None
    if not has_relevant:
        return "no_relevant_changed_paths"
    return None


def _run_tool(name: str, config: dict[str, Any], extra_args: list[str]) -> int:
    root = _resolve_repo_root()
    cwd = _workdir(root, config)
    binary = str(config.get("binary") or name)
    base_args = shlex.split(str(config.get("args") or ""))
    if name == "biome" and any(not arg.startswith("-") for arg in extra_args):
        base_args = [arg for arg in base_args if arg != "."]
    if name == "pytest":
        has_path_arg = any(arg and not arg.startswith("-") for arg in extra_args)
        has_cov_control = any(arg == "--no-cov" or arg.startswith("--cov") for arg in extra_args)
        if has_path_arg and not has_cov_control:
            extra_args = ["--no-cov", *extra_args]
    command = [*_resolve_command(binary, root, cwd, base_args), *extra_args]
    label = str(config.get("label") or name.upper())
    print(f"{label}:{name}:start")

    env = os.environ.copy()
    paths: list[str] = []
    for candidate in (
        root / "backend" / ".venv" / "bin",
        root / ".venv" / "bin",
        root / "frontend" / "node_modules" / ".bin",
        root / "node_modules" / ".bin",
    ):
        if candidate.exists():
            paths.append(str(candidate))
    if paths:
        env["PATH"] = ":".join([*paths, env.get("PATH", "")])

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        output = f"{type(exc).__name__}: {exc}"
        details = write_details(root, name, output)
        print(
            f"{label}:FAIL:127|details:{display_path(root, details)}|hint:{summary_hint(output)}"
        )
        return 127
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    details = write_details(root, name, output)
    print(
        f"{label}:{'OK' if result.returncode == 0 else 'FAIL'}:{result.returncode}|"
        f"details:{display_path(root, details)}|hint:{summary_hint(output)}"
    )
    return result.returncode


def _normalize_codeql_ref(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped if stripped.startswith("refs/") else f"refs/heads/{stripped}"


def _alert_hint(alert: dict[str, Any]) -> str:
    number = alert.get("number", "?")
    rule = alert.get("rule")
    rule_id = rule.get("id") if isinstance(rule, dict) else "unknown"
    instance = alert.get("most_recent_instance")
    location = instance.get("location") if isinstance(instance, dict) else None
    if isinstance(location, dict):
        path = location.get("path") or "unknown"
        line = location.get("start_line")
        loc = f"{path}:{line}" if line else str(path)
    else:
        loc = "unknown"
    return f"#{number} {rule_id} {loc}"


def _run_codeql_alert_check(args: list[str]) -> int:

    explicit_ref: str | None = None
    remaining = args[1:] if args[:1] == ["--"] else args
    index = 0
    while index < len(remaining):
        arg = remaining[index]
        if arg in {"-h", "--help"}:
            print("Usage: st check codeql [--ref refs/heads/main]")
            return 0
        if arg == "--ref":
            if index + 1 >= len(remaining):
                output_error("--ref requires a value")
                return 2
            explicit_ref = _normalize_codeql_ref(remaining[index + 1])
            index += 2
            continue
        output_error(f"Unknown st check codeql option: {arg}")
        return 2

    root = _resolve_repo_root()

    repo: str | None = None
    if shutil.which("gh") is not None:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            repo = result.stdout.strip() or None

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

    ref = explicit_ref
    if ref is None:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            ref = _normalize_codeql_ref(result.stdout.strip())

    alerts: list[dict[str, Any]] = []
    page = 1
    error = ""
    exit_code = 0
    while True:
        params = {
            "state": "open",
            "per_page": str(_CODEQL_PAGE_SIZE),
            "page": str(page),
        }
        if ref:
            params["ref"] = ref
        endpoint = f"repos/{repo}/code-scanning/alerts?{urllib.parse.urlencode(params)}"
        result = subprocess.run(
            ["gh", "api", endpoint],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            exit_code = result.returncode
            error = result.stderr or result.stdout
            break
        try:
            page_alerts = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            exit_code = 1
            error = f"Unable to parse gh api response: {exc}"
            break
        if not isinstance(page_alerts, list):
            exit_code = 1
            error = "GitHub code scanning response was not a list"
            break
        alerts.extend(
            alert
            for alert in page_alerts
            if isinstance(alert, dict)
            and isinstance(alert.get("tool"), dict)
            and alert["tool"].get("name") == "CodeQL"
        )
        if len(page_alerts) < _CODEQL_PAGE_SIZE:
            break
        page += 1

    details_payload = {
        "repository": repo,
        "ref": ref,
        "alerts": alerts,
        "error": error or None,
    }
    details = write_details(root, "codeql", json.dumps(details_payload, indent=2))
    if exit_code != 0:
        print(
            f"CODEQL:FAIL:{exit_code}|details:{display_path(root, details)}|"
            f"hint:{summary_hint(error)}"
        )
        return exit_code
    if alerts:
        hint = "; ".join(_alert_hint(alert) for alert in alerts[:3])
        print(
            f"CODEQL:FAIL:1|details:{display_path(root, details)}|"
            f"hint:{len(alerts)} open CodeQL alerts: {hint}"
        )
        return 1
    ref_hint = ref or "default ref"
    print(
        f"CODEQL:OK:0|details:{display_path(root, details)}|"
        f"hint:0 open CodeQL alerts for {repo} {ref_hint}"
    )
    return 0


def _fix_args(name: str, fix: bool) -> list[str]:
    if not fix:
        return []
    return {"ruff": ["--fix"], "biome": ["--write"]}.get(name, [])


def _tool_failed(name: str, config: dict[str, Any], args: list[str]) -> bool:
    return _run_tool(name, config, args) != 0


def _run_selected(
    selected: list[str],
    configs: dict[str, dict[str, Any]],
    *,
    fix: bool,
    changed_only: bool,
) -> int:
    root = _resolve_repo_root()
    changed_files = _changed_files(root) if changed_only else []
    failures = int(run_architecture_check(root, changed_files if changed_only else None) != 0)
    for name in selected:
        config = configs[name]
        cwd = _workdir(root, config)
        scoped_args = _changed_args(name, root, cwd, config, changed_files)
        skip_reason = _skip_reason(
            name,
            config,
            changed_only=changed_only,
            changed_files=changed_files,
            scoped_args=scoped_args,
        )
        if skip_reason:
            label = config.get("label") or name.upper()
            print(f"{label!s}:SKIP:{name}:{skip_reason}")
            continue
        failures += int(_tool_failed(name, config, [*scoped_args, *_fix_args(name, fix)]))
    return int(failures != 0)


def _selected_tool_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, Any],
    changed_only: bool,
    fix: bool,
    args: list[str],
) -> tuple[list[str], bool]:
    stripped = args[1:]
    explicit_args = _normalize_explicit_args(root, cwd, stripped)
    changed_files = _changed_files(root) if changed_only else []
    scoped_args = [] if explicit_args else _changed_args(name, root, cwd, config, changed_files)
    skip_reason = _skip_reason(
        name,
        config,
        changed_only=changed_only,
        changed_files=changed_files,
        scoped_args=scoped_args,
        explicit_args=bool(explicit_args),
    )
    if skip_reason:
        label = config.get("label") or name.upper()
        print(f"{label!s}:SKIP:{name}:{skip_reason}")
        return [], True
    return [*explicit_args, *scoped_args, *_fix_args(name, fix)], False


def _run_named_tool(
    first: str,
    args: list[str],
    configs: dict[str, dict[str, Any]],
    *,
    changed_only: bool,
    fix: bool,
) -> int:
    if first == "codeql":
        return _run_codeql_alert_check(args[1:])
    if first not in configs:
        return 2
    root = _resolve_repo_root()
    config = configs[first]
    cwd = _workdir(root, config)
    extra_args, skipped = _selected_tool_args(first, root, cwd, config, changed_only, fix, args)
    if skipped:
        return 0
    return _run_tool(first, config, extra_args)


@app.callback(invoke_without_command=True)
@usage(
    surface="st.check",
    cmd="st check --quick --changed-only",
    when="pre-edit gates; pre-commit; before reporting done",
    precautions=(
        "use st check for all quality gates (ruff/biome/tsc/types/pytest)",
        "use st check codeql to verify GitHub CodeQL alert state after code-scanning work",
        "never run raw pytest/vitest/biome/tsc/ruff/sqlfluff/squawk",
    ),
    tier="mandate",
)
def _help_text(names: str) -> str:
    return (
        """Quality checks through st

Required path:
  Use st check for repo gates.
  Never run raw pytest, Vitest, Biome, TSC, Ruff, SQLFluff, Squawk, or legacy dt first.

Usage:
  st check --check
  st check --changed-only
  st check --quick [--changed-only]
  st check --frontend-only
  st check codeql [--ref refs/heads/main]
  st check cleanroom -- <command>
  st check <"""
        + names
        + "> [-- <tool args>]\n"
    )


def _run_cleanroom(args: list[str]) -> int:
    return cleanroom_main(["--project-root", str(_resolve_repo_root()), *args[1:]])


def _handle_check_args(ctx: typer.Context, configs: dict[str, dict[str, Any]]) -> int:
    args = list(ctx.args)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(_help_text("|".join(sorted(configs))))
        return 0

    args, changed_only, fix = _extract_check_options(args)
    first = args[0]
    if first == "cleanroom":
        return _run_cleanroom(args)

    if first == "codeql":
        return _run_codeql_alert_check(args[1:])
    if first in configs:
        return _run_named_tool(first, args, configs, changed_only=changed_only, fix=fix)

    selection = _TOOL_SELECTIONS.get(first)
    if selection is None:
        output_error(f"Unknown st check mode/tool: {first}")
        return 2
    names, selected_fix = selection
    selected = [name for name in names if name in configs]
    return _run_selected(selected, configs, fix=fix or selected_fix, changed_only=changed_only)


def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands."""
    if ctx.invoked_subcommand is not None:
        return
    raise typer.Exit(_handle_check_args(ctx, _tool_configs()))
