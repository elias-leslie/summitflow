"""Tests for ``st jobs`` — URL resolution, exit codes, request shapes, rendering.

Mocked at the :class:`ProjectApiClient` boundary, matching the pattern in
``test_portfolio_command.py``: the suite has no ``respx`` dependency, and what
is worth pinning here is the routing and the envelope, not httpx.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli._client_base import APIError
from cli._jobs_client import JobsConnectError, resolve_jobs_api_url
from cli.main import app

runner = CliRunner()


# --- url resolver ---------------------------------------------------------


def _write_identity(root: Path, *, project_id: str = "jobinator-4000", backend_port: int = 8014) -> None:
    (root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {"id": project_id},
                "runtime": {"backend_port": backend_port},
                "hosts": {"production_api": "jobs-api.example.com"},
            }
        )
    )


def test_resolver_prefers_env_var(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://override.local:9999/")
    resolved = resolve_jobs_api_url(cwd=tmp_path)
    assert resolved.url == "http://override.local:9999"
    assert resolved.source == "env"


def test_resolver_uses_ports_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ST_JOBS_API_URL", raising=False)
    _write_identity(tmp_path)
    (tmp_path / "ports.json").write_text(json.dumps({"backend_port": 8014}))
    resolved = resolve_jobs_api_url(cwd=tmp_path)
    assert resolved.url == "http://localhost:8014"
    assert resolved.source == "ports_json"


def test_resolver_ignores_a_different_projects_checkout(tmp_path: Path, monkeypatch) -> None:
    # Standing in portfolio-ai must not resolve the jobs API to portfolio's
    # port — the walk-up matches on project id, not on "has an identity file".
    monkeypatch.delenv("ST_JOBS_API_URL", raising=False)
    _write_identity(tmp_path, project_id="portfolio-ai", backend_port=8000)
    with patch("cli._project_client._registry_root", return_value=None):
        resolved = resolve_jobs_api_url(cwd=tmp_path)
    assert resolved.source == "default"
    assert resolved.url == "http://localhost:8014"


def test_resolver_remote_uses_production_host_when_no_local_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("ST_JOBS_API_URL", raising=False)
    with patch("cli._project_client._registry_root", return_value=None), patch(
        "cli._project_client._from_remote", return_value="https://jobs-api.example.com"
    ):
        resolved = resolve_jobs_api_url(cwd=tmp_path, remote=True)
    assert resolved.source == "remote"
    assert resolved.url == "https://jobs-api.example.com"


# --- command behaviour ----------------------------------------------------


def _fake_client(
    get_return: Any = None,
    post_return: Any = None,
    *,
    get_exc: Exception | None = None,
    post_exc: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    if get_exc is not None:
        client.get.side_effect = get_exc
    else:
        client.get.return_value = get_return
    if post_exc is not None:
        client.post.side_effect = post_exc
    else:
        client.post.return_value = post_return
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    return client


def _patch_client(client: MagicMock):
    return patch("cli.commands.jobs.JobsClient", return_value=client)


def test_ready_emits_the_leads_envelope(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    leads = [{"id": 9, "title": "Sr. Director, Security", "company": "Zapier", "score": 4.9}]
    fake = _fake_client(get_return={"leads": leads, "unevaluated_new": 3, "min_score": 3.5})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "ready", "--limit", "5"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["data"] == leads
    assert payload["meta"]["unevaluated_new"] == 3
    fake.get.assert_called_once_with("/api/today", params={"limit": 5, "min_score": 3.5})


def test_ready_human_mode_lists_the_leads(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(
        get_return={
            "leads": [{"id": 9, "title": "Sr. Director, Security", "company": "Zapier", "score": 4.9}],
            "unevaluated_new": 0,
        }
    )
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "ready", "--human"])
    assert result.exit_code == 0, result.stdout
    assert "#9" in result.stdout
    assert "Sr. Director, Security — Zapier" in result.stdout
    assert "4.9" in result.stdout


def test_apply_records_the_submission_as_two_calls(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = None
    fake.post.side_effect = [
        {"id": 13, "status": "evaluated"},
        {"application_id": 13, "status": "applied", "applied_on": "2026-09-03"},
    ]
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "apply", "41", "-m", "referred", "--on", "2026-09-03"])
    assert result.exit_code == 0, result.stdout
    opened, moved = fake.post.call_args_list
    assert opened.args[0] == "/api/applications"
    assert opened.kwargs["json_body"] == {"posting_id": 41, "source": "st"}
    assert moved.args[0] == "/api/applications/13/status"
    assert moved.kwargs["json_body"] == {
        "status": "applied",
        "source": "st",
        "note": "referred",
        "applied_on": "2026-09-03",
    }


def test_apply_no_submit_only_opens_the_application(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"id": 13, "status": "evaluated"})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "apply", "41", "--no-submit"])
    assert result.exit_code == 0, result.stdout
    assert fake.post.call_count == 1
    assert json.loads(result.stdout.strip())["meta"]["submitted"] is False


def test_apply_rejects_a_malformed_date(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"id": 13})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "apply", "41", "--on", "yesterday"])
    assert result.exit_code == 3
    assert fake.post.call_count == 0


def test_status_rejects_an_unknown_status(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "status", "9", "ghosted"])
    assert result.exit_code == 3
    assert fake.post.call_count == 0


def test_writes_are_attributed_to_st_not_the_ui(monkeypatch) -> None:
    # The transition timeline is an audit trail. A move made from the CLI that
    # files itself as a UI action makes it a false one.
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"application_id": 9, "status": "interview"})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "status", "9", "interview", "-m", "panel booked"])
    assert result.exit_code == 0, result.stdout
    assert fake.post.call_args.kwargs["json_body"] == {
        "status": "interview",
        "source": "st",
        "note": "panel booked",
    }


def test_tailor_requests_both_documents_by_default(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"application_id": 9, "documents": []})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "tailor", "41"])
    assert result.exit_code == 0, result.stdout
    assert fake.post.call_args.kwargs["json_body"] == {
        "posting_id": 41,
        "kinds": ["resume", "cover_letter"],
        "source": "st",
    }


def test_tailor_rejects_an_unknown_kind(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "tailor", "41", "--kind", "portfolio"])
    assert result.exit_code == 3
    assert fake.post.call_count == 0


def test_a_blocked_fact_check_surfaces_the_invented_claims(monkeypatch) -> None:
    # The whole point of the gate is telling the caller what the model made up.
    # Flattening the detail to a string would leave an agent with nothing to act on.
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    detail = {
        "error": "fact_check_blocked",
        "message": "unsupported metric",
        "invented": ["26 organizations"],
        "forbidden": [],
        "produced": [{"kind": "resume", "html_artifact_id": 1}],
    }
    fake = _fake_client(post_exc=APIError(422, detail))
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "tailor", "41"])
    assert result.exit_code == 1
    payload = json.loads(result.stderr.strip())
    assert payload["error"] == "fact_check_blocked"
    assert payload["invented"] == ["26 organizations"]
    assert payload["produced"][0]["kind"] == "resume"


def test_an_unreachable_backend_exits_two(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(get_exc=JobsConnectError("http://test/api/today", "connection refused"))
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "ready"])
    assert result.exit_code == 2
    payload = json.loads(result.stderr.strip())
    assert payload["error"] == "jobs_api_unreachable"
    assert payload["url"] == "http://test/api/today"


def test_scan_narrows_by_company_and_waits_by_default(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"run_id": 3, "found": 12, "added": 2, "boards": 1, "companies": 1})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "scan", "--company", "Anthropic"])
    assert result.exit_code == 0, result.stdout
    assert fake.post.call_args.args[0] == "/api/sources/scan/sync"
    assert fake.post.call_args.kwargs["params"] == {"company": "Anthropic"}


def test_scan_background_uses_the_accepted_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"status": "started"})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "scan", "--background"])
    assert result.exit_code == 0, result.stdout
    assert fake.post.call_args.args[0] == "/api/sources/scan"


def test_agent_backed_commands_get_the_long_timeout(monkeypatch) -> None:
    # A 30s default would abandon a tailoring run that is still writing to the
    # database, and report a failure for work that succeeded.
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"posting_id": 41, "score": 4.4})
    with patch("cli.commands.jobs.JobsClient", return_value=fake) as constructor:
        result = runner.invoke(app, ["jobs", "evaluate", "41"])
    assert result.exit_code == 0, result.stdout
    assert constructor.call_args.kwargs["timeout"] == 600.0


def test_stats_reports_every_status_not_just_the_happy_path(monkeypatch) -> None:
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client()
    fake.get.side_effect = [
        {"counts": {"applied": 2, "rejected": 5}, "order": ["applied"], "total": 7},
        {"new": 100},
    ]
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "stats", "--human"])
    assert result.exit_code == 0, result.stdout
    assert "rejected" in result.stdout


def test_prep_reads_the_last_brief_without_spending_an_agent_call(monkeypatch):
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(get_return={"briefs": [{"id": 3, "brief_md": "## Zapier"}]})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "prep", "9"])
    assert result.exit_code == 0, result.stdout
    assert fake.post.call_count == 0
    assert json.loads(result.stdout.strip())["meta"]["brief_id"] == 3


def test_prep_with_no_brief_says_so_rather_than_rendering_an_empty_one(monkeypatch):
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(get_return={"briefs": []})
    with _patch_client(fake):
        result = runner.invoke(app, ["jobs", "prep", "9", "--human"])
    assert result.exit_code == 0, result.stdout
    assert "--write" in result.stdout


def test_prep_write_posts_and_takes_the_long_timeout(monkeypatch):
    monkeypatch.setenv("ST_JOBS_API_URL", "http://test")
    fake = _fake_client(post_return={"id": 4, "brief_md": "## Zapier"})
    with patch("cli.commands.jobs.JobsClient", return_value=fake) as constructor:
        result = runner.invoke(app, ["jobs", "prep", "9", "--write"])
    assert result.exit_code == 0, result.stdout
    assert fake.post.call_args.args[0] == "/api/interviews/9"
    assert constructor.call_args.kwargs["timeout"] == 600.0
