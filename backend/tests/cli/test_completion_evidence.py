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


def test_acceptance_artifact_is_resolved_and_validated_at_its_exact_source(tmp_path, monkeypatch):
    from unittest.mock import Mock

    validated = {"state": "success", "source_commit": "a" * 40}
    validator = Mock(return_value=validated)
    monkeypatch.setattr("cli.lib.acceptance.validate_acceptance_receipt", validator)
    (tmp_path / "accepted.json").write_text(json.dumps({"source": {"commit": validated["source_commit"]}}))
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"acceptance_receipt": "accepted.json"}))
    assert load_completion_evidence(evidence, project_root=tmp_path) == {"acceptance": validated}
    validator.assert_called_once_with(tmp_path, tmp_path / "accepted.json", sha=validated["source_commit"])


def test_native_reference_uses_the_task_project_instead_of_ambient_context(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, Mock

    client = MagicMock(project_id="owner-project")
    client.__enter__.return_value = client
    url = "https://summitflow.example.invalid/api/projects/owner-project/deployment-observations/" + "a" * 32
    client._url.return_value = url
    client.get.return_value = {"deployment": {"receipt_id": "a" * 32}}
    factory = Mock(return_value=client)
    monkeypatch.setattr("cli.client.STClient", factory)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"native_deployment_receipt": "a" * 32}))
    assert load_completion_evidence(evidence, project_root=tmp_path, project_id="owner-project") == client.get.return_value
    factory.assert_called_once_with(project_id="owner-project")
    client._url.assert_called_once_with("/deployment-observations/" + "a" * 32)
    client.get.assert_called_once_with(url)


@pytest.mark.parametrize("payload", [
    {"native_deployment_receipt": "../forged"},
    {"native_deployment_receipt": "a" * 32, "deployment_receipt": "forged.json"},
    {"native_deployment_receipt": "a" * 32, "live_validation": {"source_commit": "b" * 40}},
])
def test_native_import_rejects_mixed_or_arbitrary_evidence(tmp_path, payload):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_completion_evidence(evidence, project_root=tmp_path, project_id="owner-project")


def test_native_api_rejection_is_a_clean_import_error(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, Mock

    from cli.client import APIError

    client = MagicMock(project_id="owner-project")
    client.__enter__.return_value = client
    client.get.side_effect = APIError(422, "Unknown receipt")
    monkeypatch.setattr("cli.client.STClient", Mock(return_value=client))
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"native_deployment_receipt": "a" * 32}))
    with pytest.raises(ValueError, match="Server rejected"):
        load_completion_evidence(evidence, project_root=tmp_path, project_id="owner-project")
