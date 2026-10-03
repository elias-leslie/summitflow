"""CodeQL alert and complete analysis evidence for the live default source.

Scan completion alone never resolves an alert category. This reader performs
GETs only and retains diagnostic payloads separately from rolling task metadata.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from app.storage.projects import find_project_by_cwd
from app.storage.tasks.publication_repair import record_finding
from cli.lib.github_publish import GitHub, GitHubError

_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_UNAVAILABLE_CODEQL_MESSAGES = frozenset({
    "GitHub Code Security or GitHub Advanced Security must be enabled for this repository to use code scanning",
    "GitHub Advanced Security must be enabled for this repository to use code scanning",
    "Advanced Security must be enabled for this repository to use code scanning",
    "Code scanning is not enabled for this repository",
    "Code scanning is not enabled for this repository. Please enable code scanning in the repository settings",
})


def bind_codeql_alert_sources(evidence: dict[str, Any], alerts: Sequence[Mapping[str, Any]]) -> None:
    """Bind retained alerts to actual instances, never the observed branch tip."""
    evidence.pop("source_commit", None)
    evidence["source_bound"] = False
    instances = [alert.get("most_recent_instance") for alert in alerts]
    sources = [instance.get("commit_sha") for instance in instances if isinstance(instance, dict)]
    valid = [sha for sha in sources if isinstance(sha, str) and _SHA.fullmatch(sha)]
    evidence["alert_source_commits"] = sorted(set(valid))
    if len(valid) == len(alerts) and len(set(valid)) == 1:
        evidence["source_commit"] = valid[0]


def _language(value: str) -> str:
    return "javascript-typescript" if value in {"javascript", "typescript"} else value


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _fresh_analysis(analysis: dict[str, Any], setup: dict[str, Any]) -> bool:
    created, configured = _timestamp(analysis.get("created_at")), _timestamp(setup.get("updated_at"))
    return created is not None and configured is not None and created >= configured


def _default_scopes(setup: Any, analyses: list[dict[str, Any]]) -> tuple[set[str] | None, dict[str, dict[str, Any]]]:
    """Default setup overrides advanced workflows; its configured languages
    define coverage, not every historical key/environment tuple. Unknown or
    advanced configuration is pending rather than inferred from scan history.
    """
    if not isinstance(setup, dict) or setup.get("state") != "configured" or setup.get("query_suite") not in {"default", "extended"}:
        return None, {}
    languages = setup.get("languages")
    if (not isinstance(languages, list) or not languages or
            any(not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", value) for value in languages) or
            _timestamp(setup.get("updated_at")) is None):
        return None, {}
    expected = {_language(value) for value in languages}
    latest: dict[str, dict[str, Any]] = {}
    for analysis in analyses:  # API order is newest first.
        category = analysis.get("category")
        if not isinstance(category, str) or not category.startswith("/language:"):
            continue
        language = _language(category.removeprefix("/language:"))
        if language in expected and analysis.get("analysis_key") in {
            "dynamic/github-code-scanning/codeql:analyze", "dynamic/github-code-scanning/codeql:upload",
        }:
            latest.setdefault(language, analysis)
    return expected, latest


def observe_codeql(root: Path, repository: str, *, ref: str | None = None,
                   expected_sha: str | None = None) -> dict[str, Any]:
    """Read complete CodeQL scope state bracketed by exact live default SHA.

    The API returns analyses newest first. Verified active default setup defines
    required language scopes; unknown/advanced configuration remains pending.
    Explicit unavailable private coverage is neither a success nor a paid-plan
    upgrade requirement. Transport/auth errors are unknown coverage, not a new
    per-project defect; they never clear a previously retained alert category.
    """
    result: dict[str, Any] = {"state": "pending", "reason": "codeql_api_unavailable",
                              "observed_at": datetime.now(UTC).isoformat(),
                              "alert_count": 0, "alert_ids": [], "analysis_ids": []}
    private = False
    alerts: list[dict[str, Any]] = []
    github = GitHub(root, repository)
    try:
        metadata = github.api("")
        private = metadata.get("private") is True
        branch = metadata["default_branch"]
        if not isinstance(branch, str) or not branch:
            raise ValueError("Missing default branch")
        default_ref = "refs/heads/" + branch
        effective_ref = ref or default_ref
        before = github.api("git/ref/heads/" + quote(branch, safe=""))["object"]["sha"]
        if not isinstance(before, str) or not _SHA.fullmatch(before):
            raise ValueError("Missing exact default source")
        result["observed_live_commit"] = before
        params = urlencode({"state": "open", "ref": effective_ref, "tool_name": "CodeQL"})
        alerts = github.pages("code-scanning/alerts?" + params)
        if any(not isinstance(alert, dict) or not isinstance(alert.get("tool"), dict) or
               not isinstance(alert["tool"].get("name"), str) for alert in alerts):
            raise ValueError("Incomplete CodeQL alert response")
        alerts = [alert for alert in alerts if alert["tool"].get("name") == "CodeQL"]
        result.update(alert_count=len(alerts), alert_ids=[alert["number"] for alert in alerts
                                                       if type(alert.get("number")) is int])
        result["diagnostics"] = {"alerts": alerts, "ref": effective_ref}
        if alerts:
            result.update(state="failed", reason="codeql_alerts_open")
            bind_codeql_alert_sources(result, alerts)
        setup = github.api("code-scanning/default-setup")
        result["diagnostics"]["default_setup"] = setup
        analyses = github.pages("code-scanning/analyses?" + urlencode({"ref": default_ref, "tool_name": "CodeQL"}))
        if any(not isinstance(analysis, dict) or not isinstance(analysis.get("tool"), dict) or
               not isinstance(analysis["tool"].get("name"), str) for analysis in analyses):
            raise ValueError("Incomplete CodeQL analysis response")
        analyses = [analysis for analysis in analyses if analysis["tool"].get("name") == "CodeQL"]
        result["diagnostics"]["analyses"] = analyses
        expected, latest = _default_scopes(setup, analyses)
        for analysis in latest.values():
            if analysis.get("ref") != default_ref:
                raise ValueError("Analysis ref differs from request")
            if not isinstance(analysis.get("environment"), str):
                raise ValueError("Incomplete analysis scope")
            if type(analysis.get("id")) is not int or not isinstance(analysis.get("error"), str):
                raise ValueError("Incomplete analysis outcome")
        result["analysis_ids"] = [analysis["id"] for analysis in latest.values()
                                  if type(analysis.get("id")) is int]
        result["analysis_scope_count"] = len(latest)
        # An exact-source analysis can finish after the first alert read and
        # introduce alerts. Re-read the complete alert state after analyses,
        # then retain the final source/config bracket before any resolution.
        fresh = github.pages("code-scanning/alerts?" + params)
        if any(not isinstance(alert, dict) or not isinstance(alert.get("tool"), dict) or
               not isinstance(alert["tool"].get("name"), str) for alert in fresh):
            raise ValueError("Incomplete final CodeQL alert response")
        fresh = [alert for alert in fresh if alert["tool"].get("name") == "CodeQL"]
        result["diagnostics"]["initial_alerts"] = alerts
        result["diagnostics"]["alerts"] = fresh
        alerts = fresh
        result.update(alert_count=len(alerts), alert_ids=[alert["number"] for alert in alerts
                                                       if type(alert.get("number")) is int])
        if alerts:
            result.update(state="failed", reason="codeql_alerts_open")
            bind_codeql_alert_sources(result, alerts)
        else:
            result.update(state="pending", reason="codeql_api_unavailable")
            for key in ("source_commit", "source_bound", "alert_source_commits"):
                result.pop(key, None)
        after = github.api("git/ref/heads/" + quote(branch, safe=""))["object"]["sha"]
        after_branch = github.api("")["default_branch"]
        after_setup = github.api("code-scanning/default-setup")
        pending_reason = None
        if before != after or branch != after_branch or setup != after_setup or (expected_sha is not None and before != expected_sha) or effective_ref != default_ref:
            pending_reason = "codeql_source_pending"
        elif expected is None:
            pending_reason = "codeql_scope_coverage_unknown"
        elif (set(latest) != expected or any(analysis.get("commit_sha") != before for analysis in latest.values()) or
              any(not _fresh_analysis(analysis, setup) for analysis in latest.values())):
            pending_reason = "codeql_analysis_pending"
        if pending_reason:
            if not alerts:
                result.update(state="pending", reason=pending_reason)
            result["coverage_reason"] = pending_reason
            return result
        if alerts:
            result["source_bound"] = (result.get("source_commit") == before and all(
                isinstance(alert.get("most_recent_instance"), dict) and
                alert["most_recent_instance"].get("ref") == default_ref for alert in alerts))
            return result
        result.update(source_commit=before, source_bound=True)
        if any(analysis.get("error") for analysis in latest.values()):
            result.update(state="failed", reason="codeql_analysis_failed")
        elif any(type(analysis.get("rules_count")) is not int or analysis["rules_count"] <= 0 for analysis in latest.values()):
            result.update(state="pending", reason="codeql_scope_coverage_unknown")
        else:
            result.update(state="success", reason="codeql_default_source_verified")
    except GitHubError as exc:
        # The adapter sanitizes exception strings. Only an exact structured
        # feature response with the expected status establishes unavailable
        # coverage; stderr, auth failures and substring lookalikes do not.
        explicit_absence = (exc.status_code == 403 and isinstance(exc.response_message, str) and
                            exc.response_message.removesuffix(".") in _UNAVAILABLE_CODEQL_MESSAGES)
        if private and explicit_absence and not alerts:
            result.update(state="unavailable", reason="codeql_private_coverage_unavailable")
        result.setdefault("diagnostics", {})["error"] = str(exc)
    except (KeyError, TypeError, ValueError):
        if not alerts:
            result.update(state="failed", reason="codeql_evidence_incomplete")
    return result


def record_codeql_observation(root: Path, evidence: dict[str, Any], *, project_id: str | None = None) -> str | None:
    """Retain only machine reasons, counts, IDs and SHAs in one rolling category."""
    if evidence.get("state") not in {"failed", "success"}:
        return None
    if project_id is None:
        project = find_project_by_cwd(str(root))
        project_id = str(project["id"]) if project else None
    if project_id is None:
        return None
    fields = ("reason", "observed_at", "source_commit", "observed_live_commit", "alert_source_commits", "accepted_source_commit", "alert_count", "alert_ids", "analysis_ids", "analysis_scope_count")
    observation = {key: evidence[key] for key in fields if key in evidence}
    return record_finding(project_id, "codeql", observation, resolved=evidence["state"] == "success")


def codeql_metadata(evidence: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evidence.items() if key != "diagnostics"}
