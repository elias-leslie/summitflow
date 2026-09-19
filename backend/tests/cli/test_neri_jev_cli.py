"""CLI contract for the Agent Hub backed Neri Jev evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.neri import app

REQUEST_ID = "11111111-1111-4111-8111-111111111111"

runner = CliRunner()


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def jev_request() -> dict[str, object]:
    return {
        "request_id": REQUEST_ID,
        "state": {"finding": "A retained observation."},
        "questions": {
            "supported": {
                "type": "noul",
                "instructions": "Is the finding supported by the retained observation?",
            }
        },
        "sources": [
            {
                "source_id": "event-1",
                "revision": "1",
                "content_sha256": "a" * 64,
            }
        ],
        "rubric": {
            "rubric_id": "support-check",
            "revision": "1",
            "rubric_sha256": "b" * 64,
        },
    }


def test_jev_evaluate_forwards_exact_file_payload_and_server_response(tmp_path: Path) -> None:
    payload = jev_request()
    source = write_json(tmp_path / "request.json", payload)
    response = {
        "request_id": REQUEST_ID,
        "request_sha256": "c" * 64,
        "status": "succeeded",
        "deduplicated": False,
        "model_requested": "jev-1.13.0",
        "model_observed": "jev-1.13.0",
        "pricing_contract": "jev-1.13.0:usd-0.042-per-million-input:2026-09-19",
        "provider_request_id": "provider-request-1",
        "usage": {"input_tokens": 31, "output_tokens": 7},
        "answers": {"supported": {"type": "noul", "noul": 0.91}},
        "budget": {
            "ceiling_usd": "1.00",
            "spent_usd": "0.01",
            "reserved_usd": "0.00",
            "available_usd": "0.99",
            "reservation_usd": "0.01",
        },
        "sources": payload["sources"],
        "rubric": payload["rubric"],
        "observation": None,
        "error_kind": None,
        "error_detail": None,
    }

    with patch("cli.commands.neri.agent_hub_request", return_value=response) as request:
        result = runner.invoke(app, ["jev", "evaluate", "--file", str(source)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == response
    request.assert_called_once_with(
        "POST",
        "/api/neri/jev/evaluate",
        json=payload,
        tool_name="st neri jev evaluate",
    )


def test_jev_evaluate_adds_dry_run_to_payload_without_other_rewriting(tmp_path: Path) -> None:
    payload = {**jev_request(), "dry_run": False}
    source = write_json(tmp_path / "request.json", payload)

    with patch("cli.commands.neri.agent_hub_request", return_value={"status": "dry_run"}) as request:
        result = runner.invoke(
            app,
            ["jev", "evaluate", "--file", str(source), "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    request.assert_called_once_with(
        "POST",
        "/api/neri/jev/evaluate",
        json={**payload, "dry_run": True},
        tool_name="st neri jev evaluate",
    )


def test_jev_evaluate_rejects_non_object_json_before_request(tmp_path: Path) -> None:
    source = write_json(tmp_path / "request.json", ["not", "an", "object"])

    with patch("cli.commands.neri.agent_hub_request") as request:
        result = runner.invoke(app, ["jev", "evaluate", "--file", str(source)])

    assert result.exit_code == 2
    assert "The JSON document must be an object" in result.output
    request.assert_not_called()
