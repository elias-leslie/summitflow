"""Read-only CodeQL evidence: complete scopes and exact live default source."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import Mock

import pytest

from app.services import publication_security as security
from cli.lib import github_publish
from cli.lib.github_publish import GitHubError

SHA = "c" * 40


def analysis(**changes):
    return {"id": 1, "ref": "refs/heads/main", "commit_sha": SHA, "category": "/language:python",
            "analysis_key": "dynamic/github-code-scanning/codeql:analyze", "environment": "{}", "error": "",
            "created_at": "2026-10-02T12:00:00Z",
            "rules_count": 10, "tool": {"name": "CodeQL"}, **changes}


def setup(**changes):
    return {"state": "configured", "languages": ["python"], "query_suite": "default",
            "updated_at": "2026-10-01T12:00:00Z", **changes}


@pytest.fixture
def github(monkeypatch):
    client = Mock()
    client.api.side_effect = [{"private": False, "default_branch": "main"},
                              {"object": {"sha": SHA}}, setup(), {"object": {"sha": SHA}},
                              {"default_branch": "main"}, setup()]
    client.pages.side_effect = [[], [analysis()], []]
    monkeypatch.setattr(security, "GitHub", Mock(return_value=client))
    return client


def test_current_complete_scope_resolves_exact_default(tmp_path, github):
    result = security.observe_codeql(tmp_path, "fixture/project", expected_sha=SHA)
    assert result["state"] == "success"
    assert result["source_commit"] == SHA and result["analysis_scope_count"] == 1
    assert result["analysis_ids"] == [1]
    assert len(github.api.call_args_list) == 6
    assert all("tool_name=CodeQL" in call.args[0] for call in github.pages.call_args_list)


@pytest.mark.parametrize("analyses,reason", [
    ([], "codeql_analysis_pending"),
    ([analysis(commit_sha="a" * 40)], "codeql_analysis_pending"),
    ([analysis(rules_count=0)], "codeql_scope_coverage_unknown"),
    ([analysis(error="scan failed")], "codeql_analysis_failed"),
    ([analysis(error=None)], "codeql_evidence_incomplete"),
    ([analysis(analysis_key=None)], "codeql_analysis_pending"),
    ([analysis(ref="refs/heads/other")], "codeql_evidence_incomplete"),
    ([analysis(), analysis(tool={})], "codeql_evidence_incomplete"),
])
def test_incomplete_stale_or_failed_scope_never_resolves(tmp_path, github, analyses, reason):
    github.pages.side_effect = [[], analyses, []]
    result = security.observe_codeql(tmp_path, "fixture/project")
    assert result["state"] != "success" and result["reason"] == reason


def test_latest_scope_can_supersede_old_failure_but_not_another_scope(tmp_path, github):
    github.pages.side_effect = [[], [analysis(id=3), analysis(id=1, error="previous failure")], []]
    assert security.observe_codeql(tmp_path, "fixture/project")["state"] == "success"


@pytest.mark.parametrize("change", ["moving", "expected", "branch", "default"])
def test_source_binding_cannot_be_replaced_by_scan_green(tmp_path, github, change):
    if change == "moving":
        github.api.side_effect = [{"default_branch": "main"}, {"object": {"sha": SHA}},
                                  setup(), {"object": {"sha": "a" * 40}}, {"default_branch": "main"}, setup()]
    if change == "default":
        github.api.side_effect = [{"default_branch": "main"}, {"object": {"sha": SHA}},
                                  setup(), {"object": {"sha": SHA}}, {"default_branch": "master"}, setup()]
    result = security.observe_codeql(tmp_path, "fixture/project",
                                    expected_sha="b" * 40 if change == "expected" else None,
                                    ref="refs/heads/work" if change == "branch" else None)
    assert result["state"] == "pending" and result["reason"] == "codeql_source_pending"


def test_alerts_are_actionable_even_when_scan_is_successful(tmp_path, github):
    alerts = [{"number": 12, "tool": {"name": "CodeQL"}, "secret": "raw diagnostic"}]
    github.pages.side_effect = [alerts, [analysis()], alerts]
    result = security.observe_codeql(tmp_path, "fixture/project")
    assert result["state"] == "failed" and result["alert_ids"] == [12]
    assert github.pages.call_count == 3


def test_feature_alert_does_not_claim_default_source(tmp_path, github):
    alerts = [{"number": 12, "tool": {"name": "CodeQL"}}]
    github.pages.side_effect = [alerts, [analysis()], alerts]
    result = security.observe_codeql(tmp_path, "fixture/project", ref="refs/heads/work")
    assert result["state"] == "failed" and "source_commit" not in result


@pytest.mark.parametrize("private,message,state", [
    (True, "Advanced Security must be enabled", "pending"),
    (False, "Advanced Security must be enabled", "pending"),
    (True, "HTTP 403 Bad credentials", "pending"),
    (True, "GitHub pagination limit reached", "pending"),
    (True, "GitHub GET unavailable: TimeoutExpired", "pending"),
])
def test_feature_absence_is_explicit_not_auth_or_incomplete_read(tmp_path, github, private, message, state):
    github.api.side_effect = [{"private": private, "default_branch": "main"}, {"object": {"sha": SHA}}]
    github.pages.side_effect = GitHubError(message)
    assert security.observe_codeql(tmp_path, "fixture/project")["state"] == state


@pytest.mark.parametrize("private,status,message,state", [
    (True, 403, "GitHub Code Security or GitHub Advanced Security must be enabled for this repository to use code scanning", "unavailable"),
    (True, 403, "GitHub Advanced Security must be enabled for this repository to use code scanning.", "unavailable"),
    (True, 403, "Advanced Security must be enabled for this repository to use code scanning.", "unavailable"),
    (True, 403, "Code scanning is not enabled for this repository", "unavailable"),
    (True, 403, "Resource not accessible by integration", "pending"),
    (True, 403, "Bad credentials", "pending"),
    (True, 403, "Bad credentials: Advanced Security must be enabled for this repository to use code scanning", "pending"),
    (True, 401, "Advanced Security must be enabled for this repository to use code scanning", "pending"),
    (False, 403, "Advanced Security must be enabled for this repository to use code scanning", "pending"),
])
def test_real_github_http_envelope_distinguishes_feature_absence_from_auth(tmp_path, monkeypatch, private, status, message, state):
    # Exercise the real adapter: its exception string is deliberately sanitized,
    # and only the typed HTTP status and structured response carry this meaning.
    responses = iter([
        (200, {"private": private, "default_branch": "main"}),
        (200, {"object": {"sha": SHA}}),
        (status, {"message": message}),
    ])
    calls = []

    def run(args, **_kwargs):
        calls.append(args)
        code, payload = next(responses)
        envelope = f"HTTP/2.0 {code} Response\r\nX-Request: fixture\r\n\r\n{json.dumps(payload)}"
        return subprocess.CompletedProcess(args, int(code >= 400), envelope,
                                           "Advanced Security must be enabled; fixture-private-diagnostic")

    monkeypatch.setattr(github_publish.subprocess, "run", run)
    record = Mock()
    monkeypatch.setattr(security, "record_finding", record)
    evidence = security.observe_codeql(tmp_path, "fixture/project")
    assert evidence["state"] == state
    assert evidence["diagnostics"]["error"] == "GitHub request unavailable"
    assert all("--include" in args and args[args.index("--method") + 1] == "GET" for args in calls)
    assert len(calls) == 3
    assert security.record_codeql_observation(tmp_path, evidence, project_id="project") is None
    record.assert_not_called()  # Neither create a project defect nor clear one.


@pytest.mark.parametrize("message", [
    "Advanced Security must be enabled for this repository to use code scanning",
    "Bad credentials",
])
def test_later_feature_or_auth_error_cannot_clear_retained_alert(tmp_path, github, monkeypatch, message):
    old = "a" * 40
    alerts = [{"number": 12, "tool": {"name": "CodeQL"},
               "most_recent_instance": {"commit_sha": old, "ref": "refs/heads/main"}}]
    github.api.side_effect = [{"private": True, "default_branch": "main"}, {"object": {"sha": SHA}},
                              GitHubError("GitHub request unavailable", status_code=403, response_message=message)]
    github.pages.side_effect = [alerts]
    record = Mock()
    monkeypatch.setattr(security, "record_finding", record)
    evidence = security.observe_codeql(tmp_path, "fixture/project")
    assert evidence["state"] == "failed" and evidence["source_commit"] == old
    assert evidence["source_bound"] is False
    security.record_codeql_observation(tmp_path, evidence, project_id="project")
    assert record.call_args.kwargs == {"resolved": False}
    assert record.call_args.args[2]["source_commit"] == old


@pytest.mark.parametrize("state", ["pending", "unavailable", "failed", "success"])
def test_rolling_category_metadata_only_never_clears_on_pending(tmp_path, monkeypatch, state):
    record = Mock(return_value="repair")
    monkeypatch.setattr(security, "record_finding", record)
    evidence = {"state": state, "reason": "codeql_analysis_pending", "source_commit": SHA,
                "alert_count": 0, "alert_ids": [12], "analysis_ids": [1],
                "observed_at": "2026-10-02T10:00:00+00:00", "diagnostics": {"error": "private contents"}}
    result = security.record_codeql_observation(tmp_path, evidence, project_id="project")
    if state in {"pending", "unavailable"}:
        assert result is None
        record.assert_not_called()
    else:
        assert result == "repair"
        assert record.call_args.args[:2] == ("project", "codeql")
        assert "diagnostics" not in record.call_args.args[2]
        assert record.call_args.kwargs == {"resolved": state == "success"}


def test_completed_publication_callback_uses_repository_path_and_merge_source(tmp_path, monkeypatch):
    from app.tasks.backup_publish import _codeql_after_publication

    observe = Mock(return_value={"state": "pending", "reason": "codeql_analysis_pending", "diagnostics": {"alerts": []}})
    record = Mock()
    monkeypatch.setattr(security, "observe_codeql", observe)
    monkeypatch.setattr(security, "record_codeql_observation", record)
    result = _codeql_after_publication(tmp_path, {"project_id": "project"}, ("github.com", None, "fixture/project"),
                                      {"merge_sha": SHA}, "a" * 40)
    observe.assert_called_once_with(tmp_path, "fixture/project", expected_sha=SHA)
    assert "diagnostics" not in result
    assert record.call_args.kwargs == {"project_id": "project"}
    assert (tmp_path / ".dev-tools/codeql-details.txt").exists()


@pytest.mark.parametrize("verified", [False, True])
def test_callback_keeps_actual_merge_source_distinct_from_proven_accepted_source(tmp_path, monkeypatch, verified):
    from app.tasks.backup_publish import _codeql_after_publication

    head = "a" * 40
    record = Mock()
    monkeypatch.setattr(security, "record_codeql_observation", record)
    monkeypatch.setattr(security, "observe_codeql", lambda *_args, **_kw: {
        "state": "failed", "reason": "codeql_alerts_open", "source_commit": SHA, "source_bound": True})
    delivery = {"publication_complete": True, "sha": head, "merge_sha": SHA,
                "ci": {"state": "success", "sha": SHA, "pr_checks": {"sha": head if verified else "b" * 40}}}
    result = _codeql_after_publication(tmp_path, {"project_id": "project"}, ("github.com", None, "fixture/project"), delivery, head)
    assert result["source_commit"] == SHA
    assert (result.get("accepted_source_commit") == head) is verified


def test_pagination_limit_is_failure_not_partial_zero_alerts(tmp_path, monkeypatch):
    from cli.lib.github_publish import GitHub

    reader = GitHub(tmp_path, "fixture/project")
    monkeypatch.setattr(reader, "api", lambda *_: [analysis()] * 100)
    with pytest.raises(GitHubError, match="pagination limit"):
        reader.pages("code-scanning/analyses")


def test_unknown_api_coverage_never_creates_or_resolves_project_task(tmp_path, github, monkeypatch):
    record = Mock()
    monkeypatch.setattr(security, "record_finding", record)
    github.pages.side_effect = GitHubError("Shared authentication outage")
    evidence = security.observe_codeql(tmp_path, "fixture/project")
    assert evidence["state"] == "pending"
    assert security.record_codeql_observation(tmp_path, evidence, project_id="project") is None
    record.assert_not_called()


def test_verified_default_setup_retires_old_key_environment_and_removed_language(tmp_path, github):
    github.pages.side_effect = [[], [analysis(),
        analysis(id=2, analysis_key="dynamic/github-code-scanning/codeql:upload", environment="old", commit_sha="a" * 40),
        analysis(id=3, analysis_key=".github/workflows/old.yml:analyze", environment="old", commit_sha="a" * 40),
        analysis(id=4, category="/language:ruby", commit_sha="a" * 40)], []]
    result = security.observe_codeql(tmp_path, "fixture/project")
    assert result["state"] == "success" and result["analysis_ids"] == [1]


@pytest.mark.parametrize("configuration", [setup(state="not-configured"), setup(languages=[]),
                                            setup(updated_at=None), {}, setup(query_suite=None)])
def test_unverified_or_advanced_configuration_cannot_retire_scopes(tmp_path, github, configuration):
    github.api.side_effect = [{"default_branch": "main"}, {"object": {"sha": SHA}}, configuration,
                              {"object": {"sha": SHA}}, {"default_branch": "main"}, configuration]
    github.pages.side_effect = [[], [analysis(), analysis(id=2, category="/language:ruby", commit_sha="a" * 40)], []]
    result = security.observe_codeql(tmp_path, "fixture/project")
    assert result["state"] == "pending" and result["reason"] == "codeql_scope_coverage_unknown"
    assert result.get("source_bound") is not True


def test_default_setup_language_aliases_require_complete_active_language_coverage(tmp_path, github):
    configuration = setup(languages=["python", "javascript", "typescript", "javascript-typescript"])
    github.api.side_effect = [{"default_branch": "main"}, {"object": {"sha": SHA}}, configuration,
                              {"object": {"sha": SHA}}, {"default_branch": "main"}, configuration]
    github.pages.side_effect = [[], [analysis(), analysis(id=2, category="/language:javascript-typescript", commit_sha="a" * 40)], []]
    result = security.observe_codeql(tmp_path, "fixture/project")
    assert result["state"] == "pending" and result["reason"] == "codeql_analysis_pending"
    assert result["analysis_scope_count"] == 2


@pytest.mark.parametrize("change", ["changed_config", "analysis_predates_config"])
def test_configuration_changes_cannot_reuse_same_source_scan(tmp_path, github, change):
    if change == "changed_config":
        github.api.side_effect = [{"default_branch": "main"}, {"object": {"sha": SHA}}, setup(),
                                  {"object": {"sha": SHA}}, {"default_branch": "main"}, setup(query_suite="extended")]
    else:
        github.pages.side_effect = [[], [analysis(created_at="2026-09-30T12:00:00Z")], []]
    assert security.observe_codeql(tmp_path, "fixture/project")["state"] == "pending"


def test_stale_alert_after_verified_publication_never_becomes_candidate_failure(tmp_path, github, monkeypatch):
    from app.tasks.backup_publish import _codeql_after_publication

    old, head = "a" * 40, "b" * 40
    alerts = [{"number": 12, "tool": {"name": "CodeQL"},
        "most_recent_instance": {"commit_sha": old, "ref": "refs/heads/main"}}]
    github.pages.side_effect = [alerts, [analysis()], alerts]
    record = Mock()
    monkeypatch.setattr(security, "record_codeql_observation", record)
    delivered = {"publication_complete": True, "sha": head, "merge_sha": SHA,
                 "ci": {"state": "success", "sha": SHA, "pr_checks": {"sha": head}}}
    result = _codeql_after_publication(tmp_path, {"project_id": "project"}, ("github.com", None, "fixture/project"), delivered, head)
    assert result["state"] == "failed" and result["source_commit"] == old
    assert result["observed_live_commit"] == SHA and result["alert_source_commits"] == [old]
    assert result["source_bound"] is False and "accepted_source_commit" not in result
    assert record.call_args.args[1]["source_commit"] == old


def test_current_alert_requires_complete_bracket_before_candidate_binding(tmp_path, github):
    alerts = [{"number": 12, "tool": {"name": "CodeQL"},
        "most_recent_instance": {"commit_sha": SHA, "ref": "refs/heads/main"}}]
    github.pages.side_effect = [alerts, [analysis()], alerts]
    result = security.observe_codeql(tmp_path, "fixture/project", expected_sha="a" * 40)
    assert result["state"] == "failed" and result["source_commit"] == SHA
    assert result["observed_live_commit"] == SHA and result["source_bound"] is False
    assert result["coverage_reason"] == "codeql_source_pending"


def test_new_analysis_alerts_cannot_be_hidden_by_earlier_empty_read(tmp_path, github):
    alert = {"number": 22, "tool": {"name": "CodeQL"},
             "most_recent_instance": {"commit_sha": SHA, "ref": "refs/heads/main"}}
    github.pages.side_effect = [[], [analysis()], [alert]]
    result = security.observe_codeql(tmp_path, "fixture/project", expected_sha=SHA)
    assert result["state"] == "failed" and result["alert_ids"] == [22]
    assert result["source_commit"] == SHA and result["source_bound"] is True
    assert github.pages.call_args_list[-1].args[0].startswith("code-scanning/alerts?")
