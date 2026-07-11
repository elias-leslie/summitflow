from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "host-guardian.py"
    spec = importlib.util.spec_from_file_location("host_guardian", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_disk_thresholds_distinguish_warning_and_critical() -> None:
    module = _load_module()
    state = module.CheckState()

    module.evaluate_disk(state, {"percent_used": 82.0, "free_gib": 40.0}, label="root")
    assert state.status == "warning"
    assert state.issues[0]["code"] == "root_disk_warning"

    module.evaluate_disk(state, {"percent_used": 91.0, "free_gib": 9.0}, label="backup")
    assert state.status == "critical"
    assert state.issues[-1]["code"] == "backup_disk_critical"


def test_event_fingerprint_ignores_non_health_details() -> None:
    module = _load_module()
    payload = {
        "status": "healthy",
        "issues": [],
        "checked_at": "2026-07-11T12:00:00+00:00",
        "details": {"root_disk": {"free_gib": 100}},
    }
    changed_measurement = json.loads(json.dumps(payload))
    changed_measurement["details"]["root_disk"]["free_gib"] = 99

    assert module.event_fingerprint(payload) == module.event_fingerprint(changed_measurement)


def test_event_fingerprint_changes_when_intervention_changes() -> None:
    module = _load_module()
    healthy = {"status": "healthy", "issues": []}
    critical = {
        "status": "critical",
        "issues": [{"severity": "critical", "code": "postgres_not_ready", "message": "down"}],
    }

    assert module.event_fingerprint(healthy) != module.event_fingerprint(critical)
