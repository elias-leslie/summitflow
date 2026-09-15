"""CLI contracts for Neri-owned local-worker shadow qualification."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import call, patch

import httpx
from typer.testing import CliRunner

from cli.commands import neri
from cli.commands.neri import app

RUN_ID = "11111111-1111-4111-8111-111111111111"
OTHER_RUN_ID = "22222222-2222-4222-8222-222222222222"
ASSIGNMENT_ID = "33333333-3333-4333-8333-333333333333"
REQUEST_ID = "44444444-4444-4444-8444-444444444444"
DECISION_ID = "55555555-5555-4555-8555-555555555555"
EVENT_ID = "66666666-6666-4666-8666-666666666666"

runner = CliRunner()


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_worker_qualification_reads_neri_projection_with_optional_family() -> None:
    with patch("cli.commands.neri.request") as request:
        all_families = runner.invoke(app, ["worker", "qualification"])
        one_family = runner.invoke(
            app,
            ["worker", "qualification", "--task-family", "facts_unknowns"],
        )

    assert all_families.exit_code == 0, all_families.output
    assert one_family.exit_code == 0, one_family.output
    assert request.call_args_list == [
        call("/api/research/local-worker/qualification"),
        call("/api/research/local-worker/qualification?task_family=facts_unknowns"),
    ]


def test_worker_qualify_forwards_exact_file_payload_and_request_identity(tmp_path: Path) -> None:
    payload = {
        "request_id": REQUEST_ID,
        "task_family": "facts_unknowns",
        "state": "held",
        "reason": "Exploratory evidence does not promote this family.",
    }
    source = write_json(tmp_path / "decision.json", payload)

    with patch("cli.commands.neri.request") as request:
        result = runner.invoke(app, ["worker", "qualify", "--file", str(source)])

    assert result.exit_code == 0, result.output
    request.assert_called_once_with(
        "/api/research/local-worker/qualification/decisions",
        payload,
        identity_field="request_id",
    )


def test_worker_shadow_binds_positional_run_and_preserves_reusable_packet(tmp_path: Path) -> None:
    packet = {
        "task_family": "evidence_condensation",
        "qualification_decision_id": DECISION_ID,
        "evidence_event_ids": [EVENT_ID],
        "packet": {
            "objective": "Condense cited facts",
            "evidence": [{"ref": EVENT_ID, "content": "The observed status was 200."}],
            "constraints": ["Retain exact references."],
        },
        "sanitized": True,
        "allow_tools": False,
        "allow_memory": False,
        "allow_fallback": False,
        "allow_target_interaction": False,
        "reasoning_effort": "xhigh",
        "max_output_tokens": 4096,
    }
    source = write_json(tmp_path / "assignment.json", packet)

    with patch("cli.commands.neri.request") as request:
        result = runner.invoke(
            app,
            [
                "worker",
                "shadow",
                RUN_ID,
                "--file",
                str(source),
                "--id",
                REQUEST_ID,
            ],
        )

    assert result.exit_code == 0, result.output
    request.assert_called_once_with(
        "/api/research/local-worker/shadow-assignments",
        {
            **packet,
            "request_id": REQUEST_ID,
            "run_id": RUN_ID,
        },
        identity_field="request_id",
        timeout=neri.LOCAL_WORKER_SHADOW_TIMEOUT_SECONDS,
    )


def test_worker_assignment_reads_use_server_identity_and_meaningful_filters() -> None:
    with patch("cli.commands.neri.request") as request:
        listing = runner.invoke(
            app,
            [
                "worker",
                "assignments",
                "--run-id",
                RUN_ID,
                "--task-family",
                "evidence_condensation",
            ],
        )
        detail = runner.invoke(app, ["worker", "assignment", ASSIGNMENT_ID])

    assert listing.exit_code == 0, listing.output
    assert detail.exit_code == 0, detail.output
    assert request.call_args_list == [
        call(
            "/api/research/local-worker/shadow-assignments"
            f"?run_id={RUN_ID}&task_family=evidence_condensation"
        ),
        call(f"/api/research/local-worker/shadow-assignments/{ASSIGNMENT_ID}"),
    ]


def test_worker_assignment_prints_server_projection_without_rewriting_identity(
    monkeypatch,
) -> None:
    projection = {
        "id": ASSIGNMENT_ID,
        "run_id": RUN_ID,
        "task_family": "facts_unknowns",
        "review": None,
    }
    calls: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.raw_path.decode()))
        return httpx.Response(200, json=projection)

    client = httpx.Client
    monkeypatch.setenv("ST_NERI_API_URL", "https://neri.invalid")
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs),
    )

    result = runner.invoke(app, ["worker", "assignment", ASSIGNMENT_ID])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == projection
    assert calls == [
        (
            "GET",
            f"/api/research/local-worker/shadow-assignments/{ASSIGNMENT_ID}",
        )
    ]


def test_worker_review_binds_run_to_server_issued_assignment(tmp_path: Path) -> None:
    review = {
        "request_id": REQUEST_ID,
        "verdict": "corrected",
        "critical_error": False,
        "reference_error": True,
        "unsupported_claim": False,
        "corrections": ["Retain the exact evidence event ID."],
        "reviewer_actor": "frontier-reviewer",
        "reviewer_model": "astra-xhigh",
        "corrected_output": {"items": []},
    }
    source = write_json(tmp_path / "review.json", review)

    with patch("cli.commands.neri.request") as request:
        result = runner.invoke(
            app,
            ["worker", "review", RUN_ID, ASSIGNMENT_ID, "--file", str(source)],
        )

    assert result.exit_code == 0, result.output
    request.assert_called_once_with(
        f"/api/research/local-worker/shadow-assignments/{ASSIGNMENT_ID}/reviews",
        {**review, "run_id": RUN_ID},
        identity_field="request_id",
    )


def test_worker_writes_reject_bad_json_and_contradictory_runs_before_request(
    tmp_path: Path,
) -> None:
    list_source = write_json(tmp_path / "list.json", [])
    mismatch_source = write_json(
        tmp_path / "mismatch.json",
        {"request_id": REQUEST_ID, "run_id": OTHER_RUN_ID},
    )

    with patch("cli.commands.neri.request") as request:
        bad_object = runner.invoke(
            app,
            ["worker", "qualify", "--file", str(list_source)],
        )
        mismatched_assignment = runner.invoke(
            app,
            ["worker", "shadow", RUN_ID, "--file", str(mismatch_source)],
        )
        mismatched_review = runner.invoke(
            app,
            [
                "worker",
                "review",
                RUN_ID,
                ASSIGNMENT_ID,
                "--file",
                str(mismatch_source),
            ],
        )

    assert bad_object.exit_code == 2
    assert "must be an object" in bad_object.output
    assert mismatched_assignment.exit_code == 2
    assert "must match the positional run ID" in mismatched_assignment.output
    assert mismatched_review.exit_code == 2
    assert "must match the positional run ID" in mismatched_review.output
    request.assert_not_called()
