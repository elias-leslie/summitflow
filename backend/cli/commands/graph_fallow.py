"""Fallow and optional graph-tool profiling helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..details import display_path, strip_ansi, summary_hint, write_details

_GITNEXUS_PACKAGE = "gitnexus"
_FALLOW_PACKAGE = "fallow"
_FALLOW_MODES = {"audit", "changed", "health", "plugins", "flags", "dead-code", "dupes"}


def run_measured(command: list[str], *, cwd: Path, timeout: int = 180) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output = "\n".join(
            part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part
        )
        exit_code = result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        output = str(exc)
        exit_code = 1
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    return {
        "command": command,
        "exit_code": exit_code,
        "elapsed_ms": elapsed_ms,
        "output_chars": len(output),
        "estimated_tokens": (len(output) + 3) // 4 if output else 0,
        "output_preview": output[:1200],
    }


def extract_json_payload(output: str) -> dict[str, Any] | None:
    text = strip_ansi(output)
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index >= 0:
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        return payload if isinstance(payload, dict) else None
    return None


def fallow_command(mode: str, *, changed_since: str, top: int) -> list[str]:
    fallow_bin = shutil.which("fallow") or "fallow"
    if mode == "audit":
        return [fallow_bin, "audit", "--format", "json", "--quiet"]
    if mode == "changed":
        return [
            fallow_bin,
            "dead-code",
            "--changed-since",
            changed_since,
            "--format",
            "json",
            "--quiet",
            "--summary",
        ]
    if mode == "health":
        return [fallow_bin, "health", "--format", "json", "--quiet", "--score"]
    if mode == "plugins":
        return [fallow_bin, "list", "--format", "json", "--plugins"]
    if mode == "flags":
        return [fallow_bin, "flags", "--format", "json", "--quiet"]
    if mode == "dead-code":
        return [fallow_bin, "dead-code", "--format", "json", "--quiet"]
    return [fallow_bin, "dupes", "--format", "json", "--quiet", "--top", str(top)]


def dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def list_field(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def fallow_hint(mode: str, payload: dict[str, Any] | None, output: str) -> str:
    if not payload:
        return summary_hint(output)
    if mode == "audit":
        summary = dict_field(payload, "summary")
        attribution = dict_field(payload, "attribution")
        return (
            f"verdict={payload.get('verdict', '-')}"
            f" changed={payload.get('changed_files_count', 0)}"
            f" dead={summary.get('dead_code_issues', 0)}"
            f" complexity={summary.get('complexity_findings', 0)}"
            f" dupes={summary.get('duplication_clone_groups', 0)}"
            f" introduced={attribution.get('dead_code_introduced', 0)}"
        )
    if mode in {"changed", "dead-code"}:
        summary = dict_field(payload, "summary")
        return (
            f"issues={payload.get('total_issues', summary.get('total_issues', 0))}"
            f" files={summary.get('unused_files', 0)}"
            f" exports={summary.get('unused_exports', 0)}"
            f" deps={summary.get('unused_dependencies', 0)}"
            f" circular={summary.get('circular_dependencies', 0)}"
        )
    if mode == "health":
        score = dict_field(payload, "health_score")
        summary = dict_field(payload, "summary")
        return (
            f"score={score.get('score', '-')}"
            f" grade={score.get('grade', '-')}"
            f" functions={summary.get('functions_analyzed', 0)}"
            f" above={summary.get('functions_above_threshold', 0)}"
        )
    if mode == "plugins":
        plugins = list_field(payload, "plugins")
        names = [str(item.get("name")) for item in plugins if isinstance(item, dict) and item.get("name")]
        return f"plugins={','.join(names) if names else '-'}"
    if mode == "flags":
        return f"flags={payload.get('total_flags', 0)}"
    stats = dict_field(payload, "stats")
    groups = list_field(payload, "clone_groups")
    group_count = len(groups) if isinstance(groups, list) else stats.get("clone_groups", 0)
    return f"clone_groups={group_count} duplicated_pct={stats.get('duplication_percentage', 0)}"


def run_fallow_compact(root: Path, mode: str, *, changed_since: str, top: int, timeout: int) -> int:
    if mode not in _FALLOW_MODES:
        print(f"FALLOW:ERROR:unknown_mode:{mode}|valid={','.join(sorted(_FALLOW_MODES))}")
        return 2
    command = fallow_command(mode, changed_since=changed_since, top=top)
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        exit_code = result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        output = f"{type(exc).__name__}: {exc}"
        exit_code = 127
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    details = write_details(root, f"fallow-{mode}", output)
    clean_output = strip_ansi(output)
    payload = extract_json_payload(output)
    byte_count = len(clean_output.encode("utf-8"))
    token_count = (len(clean_output) + 3) // 4 if clean_output else 0
    print(
        f"FALLOW:{mode}:{'OK' if exit_code == 0 else 'FAIL'}:{exit_code}|"
        f"elapsed_ms={elapsed_ms}|bytes={byte_count}|tokens={token_count}|"
        f"details:{display_path(root, details)}|hint:{fallow_hint(mode, payload, output)}"
    )
    return exit_code


def gitnexus_profile(root: Path) -> dict[str, Any]:
    gitnexus_bin = shutil.which("gitnexus")
    npm_bin = shutil.which("npm")
    npx_bin = shutil.which("npx")
    metadata = (
        run_measured(
            [npm_bin, "view", _GITNEXUS_PACKAGE, "version", "description", "license", "--json"],
            cwd=root,
            timeout=30,
        )
        if npm_bin
        else {"tool": "npm", "available": False}
    )
    startup: dict[str, Any] | None = None
    local_status: dict[str, Any] | None = None
    context_probe: dict[str, Any] | None = None
    impact_probe: dict[str, Any] | None = None
    if gitnexus_bin:
        startup = run_measured([gitnexus_bin, "--version"], cwd=root, timeout=30)
        local_status = run_measured([gitnexus_bin, "status"], cwd=root, timeout=60)
        context_probe = run_measured([gitnexus_bin, "context", "graphify_status"], cwd=root, timeout=60)
        impact_probe = run_measured(
            [gitnexus_bin, "impact", "graphify_status", "--depth", "2"],
            cwd=root,
            timeout=60,
        )
    return {
        "tool": "gitnexus",
        "worth": "optional",
        "available": bool(gitnexus_bin),
        "npx_available": bool(npx_bin),
        "metadata": metadata,
        "startup": startup,
        "local_status": local_status,
        "context_probe": context_probe,
        "impact_probe": impact_probe,
        "fills_real_gaps": [
            "MCP tools for Codex/editor agents",
            "impact and detect_changes blast-radius analysis",
            "multi-repo groups and contract queries",
        ],
        "not_default_reasons": [
            "overlaps Graphify topology/search",
            "PolyForm Noncommercial license requires explicit fit check",
            "first install is heavy enough to keep explicit",
            "query/detect_changes need local validation before relying on them",
        ],
        "recommended_use": "Use after st search/st graph when work needs symbol context, impact radius, MCP-fed agent context, or multi-repo contract queries.",
        "manual_commands": {
            "install_user_prefix": ["npm", "install", "--global", "--prefix", "~/.local", "gitnexus@1.6.3"],
            "index_current_repo": [
                "gitnexus",
                "analyze",
                ".",
                "--skip-agents-md",
                "--no-stats",
                "--max-file-size",
                "1024",
            ],
            "codex_mcp": ["codex", "mcp", "add", "gitnexus", "--", "gitnexus", "mcp"],
            "status_after_install": ["gitnexus", "status"],
        },
    }


def fallow_profile(root: Path) -> dict[str, Any]:
    fallow_bin = shutil.which("fallow")
    fallow_mcp_bin = shutil.which("fallow-mcp")
    npm_bin = shutil.which("npm")
    metadata = (
        run_measured(
            [npm_bin, "view", _FALLOW_PACKAGE, "version", "description", "license", "bin", "--json"],
            cwd=root,
            timeout=30,
        )
        if npm_bin
        else {"tool": "npm", "available": False}
    )
    startup: dict[str, Any] | None = None
    plugins_probe: dict[str, Any] | None = None
    audit_probe: dict[str, Any] | None = None
    health_score_probe: dict[str, Any] | None = None
    changed_dead_code_probe: dict[str, Any] | None = None
    if fallow_bin:
        startup = run_measured([fallow_bin, "--version"], cwd=root, timeout=30)
        plugins_probe = run_measured([fallow_bin, "list", "--format", "json", "--plugins"], cwd=root, timeout=60)
        audit_probe = run_measured([fallow_bin, "audit", "--format", "json", "--quiet"], cwd=root, timeout=120)
        health_score_probe = run_measured(
            [fallow_bin, "health", "--format", "json", "--quiet", "--score"],
            cwd=root,
            timeout=120,
        )
        changed_dead_code_probe = run_measured(
            [fallow_bin, "dead-code", "--changed-since", "main", "--format", "json", "--quiet", "--summary"],
            cwd=root,
            timeout=120,
        )
    return {
        "tool": "fallow",
        "worth": "recommended_optional",
        "available": bool(fallow_bin),
        "mcp_available": bool(fallow_mcp_bin),
        "metadata": metadata,
        "startup": startup,
        "plugins_probe": plugins_probe,
        "audit_probe": audit_probe,
        "health_score_probe": health_score_probe,
        "changed_dead_code_probe": changed_dead_code_probe,
        "fills_real_gaps": [
            "TypeScript/JavaScript dead-code analysis across the module graph",
            "changed-file audit for AI-generated frontend code",
            "duplication, complexity, feature-flag, and dependency-use evidence",
            "typed MCP tools for agents that should not parse large CLI output manually",
        ],
        "not_default_reasons": [
            "full dead-code, duplication, and health output can be very large",
            "static findings need trace commands or tests before deletion",
            "does not analyze Python backend code",
            "overlaps lint/type/test gates only as codebase-level evidence, not replacement",
        ],
        "recommended_use": "Use `fallow audit --format json --quiet` after frontend JS/TS changes; use targeted trace commands before deleting exports, files, or dependencies.",
        "manual_commands": {
            "install_user_prefix": ["npm", "install", "--global", "--prefix", "~/.local", "fallow@2.57.0"],
            "codex_mcp": ["codex", "mcp", "add", "fallow", "--", "fallow-mcp"],
            "audit_changed": ["fallow", "audit", "--format", "json", "--quiet"],
            "health_score": ["fallow", "health", "--format", "json", "--quiet", "--score"],
            "project_plugins": ["fallow", "list", "--format", "json", "--plugins"],
            "trace_dependency": ["fallow", "dead-code", "--trace-dependency", "<package>", "--format", "json"],
        },
    }
