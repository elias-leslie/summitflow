"""CodeQL alert-state check helpers for st check codeql."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import cast

from ..details import display_path, summary_hint, write_details
from ..output import output_error

_CODEQL_PAGE_SIZE = 100


def _normalize_codeql_ref(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped if stripped.startswith("refs/") else f"refs/heads/{stripped}"


def _alert_hint(alert: dict[str, object]) -> str:
    number = alert.get("number", "?")
    rule = alert.get("rule")
    rule_d = cast(dict[str, object], rule) if isinstance(rule, dict) else None
    rule_id = rule_d.get("id", "unknown") if rule_d is not None else "unknown"
    instance = alert.get("most_recent_instance")
    instance_d = cast(dict[str, object], instance) if isinstance(instance, dict) else None
    location = instance_d.get("location") if instance_d is not None else None
    location_d = cast(dict[str, object], location) if isinstance(location, dict) else None
    if location_d is not None:
        path = location_d.get("path") or "unknown"
        line = location_d.get("start_line")
        loc = f"{path}:{line}" if line else str(path)
    else:
        loc = "unknown"
    return f"#{number} {rule_id} {loc}"


def _parse_codeql_args(args: list[str]) -> tuple[str | None, int]:
    """Parse codeql subcommand args. Returns (explicit_ref, code) where code -1 means printed help."""
    remaining = args[1:] if args[:1] == ["--"] else args
    index = 0
    while index < len(remaining):
        arg = remaining[index]
        if arg in {"-h", "--help"}:
            print("Usage: st check codeql [--ref refs/heads/main]")
            return None, -1
        if arg == "--ref":
            if index + 1 >= len(remaining):
                output_error("--ref requires a value")
                return None, 2
            return _normalize_codeql_ref(remaining[index + 1]), 0
        output_error(f"Unknown st check codeql option: {arg}")
        return None, 2
    return None, 0


def _fetch_codeql_repo(root: Path) -> str | None:
    if shutil.which("gh") is None:
        return None
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _fetch_codeql_ref(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return _normalize_codeql_ref(result.stdout.strip())
    return None


def _fetch_codeql_alerts(
    root: Path,
    repo: str,
    ref: str | None,
) -> tuple[list[dict[str, object]], str, int]:
    alerts: list[dict[str, object]] = []
    page = 1
    error = ""
    exit_code = 0
    while True:
        params: dict[str, str] = {
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
    return alerts, error, exit_code


def _emit_codeql_result(
    root: Path,
    repo: str,
    ref: str | None,
    alerts: list[dict[str, object]],
    error: str,
    exit_code: int,
) -> int:
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
