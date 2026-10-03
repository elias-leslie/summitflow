"""Trusted Neri observer metadata forwards only its read-only runtime location."""
from __future__ import annotations

from cli.extensions import _environment, load_extensions


def test_neri_observer_has_single_native_read_only_registration(monkeypatch):
    catalog = load_extensions(set())
    owners = [record for record in catalog.records
              if record.binding and record.binding.owner == "neri"
              and record.manifest and "observe_deployment" in record.manifest.structured_operations]
    assert len(owners) == 1
    observer = owners[0]
    assert observer.status == "unverified"
    assert observer.binding is not None
    assert observer.binding.executable == "scripts/st-neri-observe"
    assert observer.binding.environment == ["SUMMITFLOW_SERVICE_STATE_ROOT"]
    assert observer.manifest is not None
    assert set(observer.manifest.effects) <= {"network", "read-remote", "read-local", "credentials", "process"}
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", "/tmp/fixture-service-state")
    env = _environment(observer.binding, {"project_id": "neri", "cwd": "/tmp/fixture"})
    assert env["SUMMITFLOW_SERVICE_STATE_ROOT"] == "/tmp/fixture-service-state"
