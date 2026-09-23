import hashlib
import json

import pytest

from cli.lib.completion_evidence import load_completion_evidence


def test_live_artifact_is_hashed_and_bound_to_source(tmp_path):
    artifact = tmp_path / "live.txt"
    artifact.write_text("observed login isolation")
    source = "a" * 40
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"live_validation": {"source_commit": source, "checks": [
        {"id": "login-isolation", "state": "success", "artifact": "live.txt"},
    ]}}))
    receipt = load_completion_evidence(evidence, project_root=tmp_path)
    check = receipt["live_validation"]["checks"][0]
    assert check["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert check["artifact"] == str(artifact)
    assert receipt["live_validation"]["source_commit"] == source


def test_invalid_or_missing_live_evidence_is_rejected(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"live_validation": {"source_commit": "HEAD", "checks": []}}))
    with pytest.raises(ValueError):
        load_completion_evidence(evidence, project_root=tmp_path)


def test_recorded_artifact_digest_cannot_change(tmp_path):
    artifact = tmp_path / "live.txt"
    artifact.write_text("modified")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"live_validation": {"source_commit": "a" * 40, "checks": [
        {"id": "check", "state": "success", "artifact": "live.txt", "sha256": "0" * 64},
    ]}}))
    with pytest.raises(ValueError, match="digest"):
        load_completion_evidence(evidence, project_root=tmp_path)


def test_acceptance_artifact_is_resolved_and_validated_at_exact_head(tmp_path, monkeypatch):
    from unittest.mock import Mock

    validated = {"state": "success", "source_commit": "a" * 40}
    validator = Mock(return_value=validated)
    monkeypatch.setattr("cli.lib.acceptance.validate_acceptance_receipt", validator)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"acceptance_receipt": "accepted.json"}))
    assert load_completion_evidence(evidence, project_root=tmp_path) == {"acceptance": validated}
    validator.assert_called_once_with(tmp_path, tmp_path / "accepted.json", sha="HEAD")
