"""CLI contracts for Neri owned-lab catalog campaigns."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import call, patch

from typer.testing import CliRunner

from cli.commands.neri import app

CAMPAIGN_ID = "11111111-1111-4111-8111-111111111111"
REQUEST_ID = "22222222-2222-4222-8222-222222222222"
INVESTIGATION_ID = "33333333-3333-4333-8333-333333333333"

runner = CliRunner()


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_catalog_campaign_reads_use_exact_neri_routes() -> None:
    with patch("cli.commands.neri.request") as request:
        campaigns = runner.invoke(app, ["research", "catalog-campaigns"])
        campaign = runner.invoke(
            app, ["research", "catalog-campaign", CAMPAIGN_ID]
        )

    assert campaigns.exit_code == campaign.exit_code == 0
    assert request.call_args_list == [
        call("/api/research/catalog-campaigns"),
        call(f"/api/research/catalog-campaigns/{CAMPAIGN_ID}"),
    ]


def test_catalog_campaign_writes_retain_exact_ids_and_escape_item_key(
    tmp_path: Path,
) -> None:
    registration_payload = {
        "request_key": "juice-shop-20-2-0",
        "title": "Juice Shop 20.2.0 complete catalog",
    }
    completion_payload = {
        "status": "verified_complete",
        "run_id": INVESTIGATION_ID,
    }
    plan_payload = {
        "run_id": INVESTIGATION_ID,
        "item_keys": ["catalog-item"],
    }
    replay_payload = {
        "run_id": "44444444-4444-4444-8444-444444444444",
        "item_keys": ["catalog-item"],
    }
    registration_file = write_json(
        tmp_path / "campaign.json", registration_payload
    )
    completion_file = write_json(tmp_path / "completion.json", completion_payload)
    plan_file = write_json(tmp_path / "plan.json", plan_payload)
    replay_file = write_json(tmp_path / "replay.json", replay_payload)

    with patch("cli.commands.neri.request") as request:
        register = runner.invoke(
            app,
            [
                "research",
                "register-catalog-campaign",
                "--file",
                str(registration_file),
                "--id",
                REQUEST_ID,
            ],
        )
        complete = runner.invoke(
            app,
            [
                "research",
                "verify-catalog-item",
                CAMPAIGN_ID,
                "item/with space",
                "--file",
                str(completion_file),
                "--id",
                REQUEST_ID,
            ],
        )
        plan = runner.invoke(
            app,
            [
                "research",
                "record-catalog-plan",
                CAMPAIGN_ID,
                "--file",
                str(plan_file),
                "--id",
                REQUEST_ID,
            ],
        )
        replay = runner.invoke(
            app,
            [
                "research",
                "record-catalog-replay",
                CAMPAIGN_ID,
                "--file",
                str(replay_file),
                "--id",
                REQUEST_ID,
            ],
        )

    assert register.exit_code == complete.exit_code == plan.exit_code == replay.exit_code == 0
    assert request.call_args_list == [
        call(
            "/api/research/catalog-campaigns",
            {**registration_payload, "id": REQUEST_ID},
        ),
        call(
            f"/api/research/catalog-campaigns/{CAMPAIGN_ID}/items/item%2Fwith%20space/verify",
            {**completion_payload, "id": REQUEST_ID},
        ),
        call(
            f"/api/research/catalog-campaigns/{CAMPAIGN_ID}/plans",
            {**plan_payload, "id": REQUEST_ID},
        ),
        call(
            f"/api/research/catalog-campaigns/{CAMPAIGN_ID}/replays",
            {**replay_payload, "id": REQUEST_ID},
        ),
    ]


def test_catalog_campaign_write_rejects_conflicting_file_identity(
    tmp_path: Path,
) -> None:
    source = write_json(
        tmp_path / "campaign.json",
        {"id": CAMPAIGN_ID, "request_key": "juice-shop-20-2-0"},
    )

    with patch("cli.commands.neri.request") as request:
        result = runner.invoke(
            app,
            [
                "research",
                "register-catalog-campaign",
                "--file",
                str(source),
                "--id",
                REQUEST_ID,
            ],
        )

    assert result.exit_code != 0
    request.assert_not_called()


def test_runtime_snapshot_retains_exact_request_identity(tmp_path: Path) -> None:
    payload = {
        "controller_id": "external-tui",
        "controller_revision": 7,
        "client": "Codex",
        "model": "gpt-daybreak-blue-latest",
    }
    source = write_json(tmp_path / "runtime-snapshot.json", payload)

    with patch("cli.commands.neri.request") as request:
        result = runner.invoke(
            app,
            [
                "execute",
                "runtime-snapshot",
                INVESTIGATION_ID,
                "--file",
                str(source),
                "--id",
                REQUEST_ID,
            ],
        )

    assert result.exit_code == 0
    request.assert_called_once_with(
        f"/api/workbench/{INVESTIGATION_ID}/runtime-snapshots",
        {**payload, "id": REQUEST_ID},
    )
