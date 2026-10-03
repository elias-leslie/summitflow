"""CodeQL alert-state check helpers for st check codeql."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from app.services.publication_security import (
    bind_codeql_alert_sources,
    observe_codeql,
    record_codeql_observation,
)

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
        _record_codeql_unavailable(root)
        return None
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            cwd=root, text=True, capture_output=True, check=False, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    _record_codeql_unavailable(root)
    return None


def _record_codeql_unavailable(root: Path) -> None:
    try:
        record_codeql_observation(root, {"state": "pending", "reason": "codeql_cli_unavailable",
                                         "observed_at": datetime.now(UTC).isoformat(), "alert_count": 0,
                                         "alert_ids": [], "analysis_ids": []})
    except Exception:
        print("CODEQL:INGEST:UNAVAILABLE|hint:rolling repair evidence could not be recorded")


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
        if page > 100:
            return alerts, "Incomplete CodeQL alert pagination", 1
        params: dict[str, str] = {
            "state": "open",
            "per_page": str(_CODEQL_PAGE_SIZE),
            "page": str(page),
        }
        if ref:
            params["ref"] = ref
        endpoint = f"repos/{repo}/code-scanning/alerts?{urllib.parse.urlencode(params)}"
        try:
            result = subprocess.run(
                ["gh", "api", endpoint], cwd=root, text=True,
                capture_output=True, check=False, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return alerts, "CodeQL API unavailable: " + type(exc).__name__, 1
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
    evidence = observe_codeql(root, repo, ref=ref)
    # A failed paginated read must never be replaced by a second green read.
    if exit_code != 0 and evidence.get("state") not in {"unavailable", "failed"}:
        evidence.update(state="pending", reason="codeql_api_unavailable")
    elif alerts:
        evidence.update(state="failed", reason="codeql_alerts_open", alert_count=len(alerts),
                        alert_ids=[alert["number"] for alert in alerts if type(alert.get("number")) is int])
        bind_codeql_alert_sources(evidence, alerts)
    try:
        record_codeql_observation(root, evidence)
    except Exception:
        print("CODEQL:INGEST:UNAVAILABLE|hint:rolling repair evidence could not be recorded")
    details_payload = {
        "repository": repo,
        "ref": ref,
        "alerts": alerts,
        "error": error or None,
        "source_evidence": evidence,
    }
    details = write_details(root, "codeql", json.dumps(details_payload, indent=2))
    if evidence.get("state") == "unavailable":
        print(f"CODEQL:UNAVAILABLE:0|details:{display_path(root, details)}|hint:private CodeQL coverage unavailable; existing findings retained")
        return 0
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
    if evidence.get("state") == "failed":
        print(f"CODEQL:FAIL:1|details:{display_path(root, details)}|hint:{evidence['reason']}")
        return 1
    if evidence.get("state") == "pending":
        print(f"CODEQL:PENDING:0|details:{display_path(root, details)}|hint:{evidence['reason']}; existing findings retained")
        return 0
    ref_hint = ref or "default ref"
    print(
        f"CODEQL:OK:0|details:{display_path(root, details)}|"
        f"hint:0 open CodeQL alerts for {repo} {ref_hint}; resolution={evidence['state']}"
    )
    return 0
