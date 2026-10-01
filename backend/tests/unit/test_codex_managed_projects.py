"""Trusted host project selection and independent collector recovery."""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/lib"))
delivery = importlib.import_module("codex_managed_delivery")
capture = importlib.import_module("codex_managed_capture")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    values = {"SUMMITFLOW_CODEX_OUTBOXES_JSON": json.dumps({"agent-hub": str(tmp_path / "ah/outbox.sqlite"), "summitflow": str(tmp_path / "sf/outbox.sqlite")}), "SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES": "268435456", "SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS": "0"}
    monkeypatch.setattr(delivery, "managed_settings", lambda: values)
    monkeypatch.setattr(capture, "codex_binary", lambda: (_ for _ in ()).throw(ValueError("no runtime")))
    return values


def test_project_default_explicit_selection_and_disable_are_independent(settings):
    ah = delivery.configured_outbox()
    sf = delivery.configured_outbox("summitflow")
    assert ah.path != sf.path
    assert ah.metadata("project") == {"project_id": "agent-hub"}
    result = delivery.operator_action("disable", project_id="summitflow")
    assert result["project_id"] == "summitflow"
    assert result["configured_projects"] == ["agent-hub", "summitflow"]
    assert sf.owner()["capture_disabled"] and not ah.owner()["capture_disabled"]
    assert delivery.operator_status()["project_id"] == "agent-hub"
    missing = delivery.operator_status(project_id="unconfigured")
    assert missing["project_id"] == "unconfigured" and not missing["available"] and not missing["actions"]
    with pytest.raises(ValueError):
        delivery.operator_action("disable", project_id="unconfigured")


def test_configuration_rejects_shared_path_and_misbound_database(settings):
    sf = delivery.configured_outbox("summitflow")
    sf.metadata("project", {"project_id": "agent-hub"})
    with pytest.raises(ValueError, match="binding_mismatch"):
        delivery.configured_outbox("summitflow")
    paths = json.loads(settings["SUMMITFLOW_CODEX_OUTBOXES_JSON"])
    paths["summitflow"] = paths["agent-hub"]
    settings["SUMMITFLOW_CODEX_OUTBOXES_JSON"] = json.dumps(paths)
    with pytest.raises(ValueError, match="independent_paths"):
        delivery.configured_paths()


def test_collector_recovers_second_project_after_first_storage_failure(settings, monkeypatch):
    calls = []
    def recover(api_url, *, project_id):
        calls.append((api_url, project_id))
        if project_id == "agent-hub":
            raise OSError("disk unavailable")
        return {"project_id": project_id, "health": "connected", "pending": 0, "capture_gaps": 0}
    monkeypatch.setattr(delivery, "recover_configured_outbox", recover)
    results = delivery.recover_configured_outboxes("http://fixture/api")
    assert [project for _, project in calls] == ["agent-hub", "summitflow"]
    assert results[0]["health"] == "delivery_unavailable" and results[1]["health"] == "connected"


def test_legacy_single_spool_remains_bound_and_cannot_target_another_project(settings, tmp_path):
    settings.pop("SUMMITFLOW_CODEX_OUTBOXES_JSON")
    settings["SUMMITFLOW_CODEX_OUTBOX"] = str(tmp_path / "legacy/outbox.sqlite")
    spool = delivery.configured_outbox()
    spool.metadata("project", {"project_id": "summitflow"})
    assert delivery.operator_status()["configured_projects"] == ["summitflow"]
    assert not delivery.operator_status(project_id="agent-hub")["available"]
    with pytest.raises(ValueError, match="binding_mismatch"):
        delivery.operator_action("disable", project_id="agent-hub")


@pytest.fixture(autouse=True)
def isolated_managed_host_settings(tmp_path, monkeypatch):
    """Host policy must never make unit tests initialize the owner's real spools."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    for key in ("SUMMITFLOW_CODEX_MANAGED_CAPTURE", "SUMMITFLOW_CODEX_OUTBOX", "SUMMITFLOW_CODEX_OUTBOXES_JSON", "SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES", "SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS", "SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION"):
        monkeypatch.delenv(key, raising=False)


def test_trusted_host_policy_file_and_explicit_environment_override(tmp_path, monkeypatch):
    home = Path.home()
    mapping = {"agent-hub": str(tmp_path / "ah/outbox.sqlite"), "summitflow": str(tmp_path / "sf/outbox.sqlite")}
    (home / ".env.local").write_text("SUMMITFLOW_CODEX_MANAGED_CAPTURE=1\nSUMMITFLOW_CODEX_OUTBOXES_JSON='" + json.dumps(mapping) + "'\nSUMMITFLOW_CODEX_OUTBOX_MAX_BYTES=268435456\nSUMMITFLOW_CODEX_RAW_RETENTION_SECONDS=0\n")
    assert capture.capture_enabled()
    assert delivery.configured_outbox("summitflow").max_bytes == 268435456
    monkeypatch.setenv("SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES", "1048576")
    assert delivery.configured_outbox("agent-hub").max_bytes == 1048576
