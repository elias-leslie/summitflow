"""CLI contracts for Neri prospective cohort and work evidence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import call, patch

from typer.testing import CliRunner

from cli.commands.neri import app

RUN_ID = "11111111-1111-4111-8111-111111111111"
COHORT_ID = "22222222-2222-4222-8222-222222222222"
REQUEST_ID = "33333333-3333-4333-8333-333333333333"

runner = CliRunner()


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_profit_evidence_reads_use_exact_neri_routes() -> None:
    with patch("cli.commands.neri.request") as request:
        cohorts = runner.invoke(app, ["research", "cohorts"])
        cohort = runner.invoke(app, ["research", "cohort", COHORT_ID])
        work = runner.invoke(app, ["research", "work", RUN_ID])
        application = runner.invoke(app, ["research", "application", RUN_ID])
        application_snapshots = runner.invoke(
            app, ["research", "application-snapshots", RUN_ID]
        )

    assert (
        cohorts.exit_code == cohort.exit_code == work.exit_code
        == application.exit_code == application_snapshots.exit_code == 0
    )
    assert request.call_args_list == [
        call("/api/research/evaluation-cohorts"),
        call(f"/api/research/evaluation-cohorts/{COHORT_ID}"),
        call(f"/api/runs/{RUN_ID}/research-work-receipts"),
        call(f"/api/runs/{RUN_ID}/application-evidence-projection"),
        call(f"/api/runs/{RUN_ID}/application-evidence-snapshots"),
    ]


def test_profit_evidence_writes_retain_or_allocate_exact_ids(tmp_path: Path) -> None:
    cohort_payload = {
        "request_key": "cohort-one",
        "title": "Cohort",
        "purpose": "Fixed prospective evaluation",
    }
    closure_payload = {
        "request_key": "closure-one",
        "status": "stopped",
        "case_dispositions": [],
        "reason": "Scope changed.",
    }
    work_payload = {
        "request_key": "work-one",
        "cohort_id": COHORT_ID,
        "work_kind": "reasoning",
    }
    accounting_payload = {
        "request_key": "accounting-one",
        "status": "stopped",
        "case_dispositions": [],
        "reason": "Measurement stopped.",
    }
    cohort_file = write_json(tmp_path / "cohort.json", cohort_payload)
    closure_file = write_json(tmp_path / "closure.json", closure_payload)
    work_file = write_json(tmp_path / "work.json", work_payload)
    accounting_file = write_json(tmp_path / "accounting.json", accounting_payload)
    application_file = write_json(tmp_path / "application.json", {
        "request_key": "application-one",
        "expected_source_digest": "a" * 64,
    })

    with patch("cli.commands.neri.request") as request:
        register = runner.invoke(
            app,
            ["research", "register-cohort", "--file", str(cohort_file), "--id", REQUEST_ID],
        )
        close = runner.invoke(
            app,
            [
                "research", "close-cohort", COHORT_ID,
                "--file", str(closure_file), "--id", REQUEST_ID,
            ],
        )
        record = runner.invoke(
            app,
            [
                "research", "record-work", RUN_ID,
                "--file", str(work_file), "--id", REQUEST_ID,
            ],
        )
        finalize = runner.invoke(
            app,
            [
                "research", "finalize-accounting", COHORT_ID,
                "--file", str(accounting_file), "--id", REQUEST_ID,
            ],
        )
        snapshot_application = runner.invoke(
            app,
            [
                "research", "snapshot-application", RUN_ID,
                "--file", str(application_file), "--id", REQUEST_ID,
            ],
        )

    assert (
        register.exit_code == close.exit_code == finalize.exit_code == record.exit_code
        == snapshot_application.exit_code == 0
    )
    assert request.call_args_list == [
        call(
            "/api/research/evaluation-cohorts",
            {**cohort_payload, "id": REQUEST_ID},
        ),
        call(
            f"/api/research/evaluation-cohorts/{COHORT_ID}/closure",
            {**closure_payload, "id": REQUEST_ID},
        ),
        call(
            f"/api/runs/{RUN_ID}/research-work-receipts",
            {**work_payload, "id": REQUEST_ID},
        ),
        call(
            f"/api/research/evaluation-cohorts/{COHORT_ID}/accounting-closure",
            {**accounting_payload, "id": REQUEST_ID},
        ),
        call(
            f"/api/runs/{RUN_ID}/application-evidence-snapshots",
            {
                "request_key": "application-one",
                "expected_source_digest": "a" * 64,
                "id": REQUEST_ID,
            },
        ),
    ]


def test_profit_evidence_write_rejects_conflicting_file_identity(tmp_path: Path) -> None:
    source = write_json(tmp_path / "cohort.json", {
        "id": COHORT_ID,
        "request_key": "cohort-one",
    })

    with patch("cli.commands.neri.request") as request:
        result = runner.invoke(
            app,
            ["research", "register-cohort", "--file", str(source), "--id", REQUEST_ID],
        )

    assert result.exit_code != 0
    request.assert_not_called()
