"""Tests for the bounded Neri local-worker ST surface."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.neri import app

runner = CliRunner()


def test_worker_status_uses_dedicated_agent_hub_route() -> None:
    with patch(
        "cli.commands.neri.agent_hub_request",
        return_value={"model_id": "local/neri", "lifecycle": "experimental"},
    ) as request:
        result = runner.invoke(app, ["worker", "status"])

    assert result.exit_code == 0
    assert json.loads(result.output)["lifecycle"] == "experimental"
    request.assert_called_once_with(
        "GET",
        "/api/neri/local-worker/status",
        tool_name="st neri worker status",
    )


def test_worker_evaluate_exposes_no_model_tool_or_fallback_override(tmp_path: Path) -> None:
    packet = tmp_path / "packet.json"
    packet.write_text(
        json.dumps(
            {
                "objective": "Separate facts from unknowns",
                "evidence": [{"ref": "E1", "content": "Observed status 200"}],
                "constraints": [],
            }
        )
    )
    with patch(
        "cli.commands.neri.agent_hub_request",
        return_value={"effective_model": "qwen3.8-27b-neri-iq3_s"},
    ) as request:
        result = runner.invoke(
            app,
            [
                "worker",
                "evaluate",
                "--task-family",
                "facts_unknowns",
                "--file",
                str(packet),
                "--arm",
                "role_checklist",
            ],
        )

    assert result.exit_code == 0
    payload = request.call_args.kwargs["json"]
    assert payload == {
        "task_family": "facts_unknowns",
        "harness_arm": "role_checklist",
        "packet": json.loads(packet.read_text()),
        "reasoning_effort": "xhigh",
        "max_output_tokens": 4096,
    }
    assert not ({"model", "tools", "fallback_models", "working_dir"} & payload.keys())


def test_worker_benchmark_defaults_to_all_harness_arms() -> None:
    with patch(
        "cli.commands.neri.agent_hub_request",
        return_value={"benchmark_id": "bench-1", "attempts": 4},
    ) as request:
        result = runner.invoke(app, ["worker", "benchmark", "--split", "development"])

    assert result.exit_code == 0
    payload = request.call_args.kwargs["json"]
    assert payload["harness_arms"] == [
        "bare_schema",
        "role_checklist",
        "grounded_decomposition",
        "critique_repair",
    ]
    assert payload["persist"] is True
    assert payload["max_output_tokens"] == 4096


def test_worker_benchmark_preserves_exact_case_order() -> None:
    with patch(
        "cli.commands.neri.agent_hub_request",
        return_value={"benchmark_id": "bench-exact", "attempts": 2},
    ) as request:
        result = runner.invoke(
            app,
            [
                "worker",
                "benchmark",
                "--case-id",
                "locked_case_17",
                "--case-id",
                "development_case_02",
            ],
        )

    assert result.exit_code == 0
    payload = request.call_args.kwargs["json"]
    assert payload["case_ids"] == ["locked_case_17", "development_case_02"]
    assert payload["study_id"] is None
    assert payload["study_block"] is None
    assert payload["study_case_position"] is None
    assert payload["study_replacement"] == 0


def test_worker_benchmark_sends_complete_study_binding() -> None:
    with patch(
        "cli.commands.neri.agent_hub_request",
        return_value={"benchmark_id": "bench-study", "attempts": 1},
    ) as request:
        result = runner.invoke(
            app,
            [
                "worker",
                "benchmark",
                "--study-id",
                "frozen-study-v1",
                "--study-block",
                "3",
                "--study-case-position",
                "11",
                "--study-replacement",
                "2",
            ],
        )

    assert result.exit_code == 0
    payload = request.call_args.kwargs["json"]
    assert payload["harness_arms"] == ["role_checklist"]
    assert payload["study_id"] == "frozen-study-v1"
    assert payload["study_block"] == 3
    assert payload["study_case_position"] == 11
    assert payload["study_replacement"] == 2


def test_worker_benchmark_rejects_incomplete_study_binding_before_request() -> None:
    with patch("cli.commands.neri.agent_hub_request") as request:
        result = runner.invoke(
            app,
            [
                "worker",
                "benchmark",
                "--study-id",
                "frozen-study-v1",
                "--study-block",
                "3",
            ],
        )

    assert result.exit_code == 2
    # Rich may wrap the validation text inside its terminal-width error box.
    assert "must be supplied together" in " ".join(result.output.replace("│", " ").split())
    request.assert_not_called()


def test_worker_benchmark_rejects_non_frozen_study_options_before_request() -> None:
    binding = [
        "--study-id",
        "frozen-study-v1",
        "--study-block",
        "3",
        "--study-case-position",
        "11",
    ]
    incompatible_options = [
        ["--case-id", "development_case_02"],
        ["--task-family", "facts_unknowns"],
        ["--runs", "2"],
        ["--arm", "bare_schema"],
        ["--arm", "role_checklist", "--arm", "role_checklist"],
        ["--no-persist"],
    ]

    with patch("cli.commands.neri.agent_hub_request") as request:
        for incompatible in incompatible_options:
            result = runner.invoke(app, ["worker", "benchmark", *binding, *incompatible])

            assert result.exit_code == 2

    request.assert_not_called()


def test_worker_benchmark_rejects_replacement_outside_study_before_request() -> None:
    with patch("cli.commands.neri.agent_hub_request") as request:
        result = runner.invoke(
            app,
            ["worker", "benchmark", "--study-replacement", "1"],
        )

    assert result.exit_code == 2
    assert "requires a complete study binding" in result.output
    request.assert_not_called()
