"""Caller-facing acceptance contracts use explicit materialization and coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_typed_result_returns_compact_validated_reference(tmp_path: Path) -> None:
    from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt

    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "owned.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=tmp_path, check=True)
    result = accept_source(tmp_path, sha="HEAD", materialization="actual", scope=("owned.py",),
                           runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "ok", ""))
    reference = result.reference.to_dict()
    assert reference["state"] == "success" and reference["outcome"] == "pass"
    assert reference["coverage"] == "full"
    assert "checks" not in reference and "plan" not in reference and "inputs" not in reference
    assert result.to_dict()["receipt_reference"] == reference
    assert validate_source_receipt(tmp_path, Path(reference["acceptance_artifact"])).reference == result.reference


def test_task_receipt_runs_scoped_gate_once_without_claiming_full(tmp_path: Path) -> None:
    from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt

    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "owned.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=tmp_path, check=True)
    calls = []

    def run(command, cwd):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")

    first = accept_source(tmp_path, sha="HEAD", materialization="actual", coverage="task",
                          scope=("owned.py",), runner=run)
    second = accept_source(tmp_path, sha="HEAD", materialization="actual", coverage="task",
                           scope=("owned.py",), runner=run)
    assert first.reference.coverage == "task"
    assert first.reference.required_stages[0]["id"] == "scoped-quality"
    assert calls == [["st", "check", "--quick", "--changed-only"]]
    assert second.reused is True
    assert validate_source_receipt(tmp_path, Path(first.reference.acceptance_artifact)).reference.coverage == "task"
    from cli.lib.acceptance import AcceptanceError

    with pytest.raises(AcceptanceError, match="scope contains no source"):
        accept_source(tmp_path, sha="HEAD", materialization="actual", coverage="task", scope=("missing.py",), runner=run)


def test_task_receipt_cannot_omit_required_scoped_evidence(tmp_path: Path) -> None:
    import json

    from cli.lib import acceptance
    from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt

    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "owned.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=tmp_path, check=True)
    result = accept_source(tmp_path, sha="HEAD", materialization="actual", coverage="task", scope=("owned.py",),
                           runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "RUFF:OK:0", ""))
    payload = json.loads(Path(result.reference.acceptance_artifact).read_text())
    payload["checks"][0]["evidence"]["stages"] = []
    payload["acceptance_id"] = acceptance._receipt_digest(payload)
    with pytest.raises(acceptance.AcceptanceError, match="required scoped quality stage"):
        validate_source_receipt(tmp_path, payload)


@pytest.mark.parametrize("forgery", [None, "scope", "coverage", "required_stages", "outside", "missing", "incomplete", "root-symlink", "raw-outside", "external-evidence",
    "source_commit", "source_tree", "input_fingerprint", "acceptance_plan_fingerprint", "scope_digest", "task_id", "kind", "declared_stages"])
def test_compact_reference_reopens_only_matching_immutable_proof(tmp_path: Path, forgery) -> None:
    from cli.lib.acceptance import AcceptanceError
    from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt

    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "owned.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=tmp_path, check=True)
    accepted = accept_source(tmp_path, sha="HEAD", materialization="actual", coverage="task",
                             scope=("owned.py",), task_id="owned-task",
                             runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "RUFF:OK:0", ""))
    reference = accepted.reference.to_dict()
    if forgery in {"scope", "required_stages"}:
        reference[forgery] = ["other.py"] if forgery == "scope" else []
    elif forgery == "declared_stages":
        reference["declared_stages"] = ["other-stage"]
    elif forgery == "coverage":
        reference["coverage"] = "full"
    elif forgery in {"outside", "raw-outside"}:
        outside = tmp_path / "copied-proof.json"
        outside.write_bytes(Path(reference["acceptance_artifact"]).read_bytes())
        if forgery == "raw-outside":
            Path(reference["acceptance_artifact"]).unlink()
            from cli.lib.acceptance import validate_acceptance_receipt

            assert validate_acceptance_receipt(tmp_path, outside)["state"] == "success"
            with pytest.raises(AcceptanceError, match="explicit retention"):
                validate_source_receipt(tmp_path, outside)
            return
        reference["acceptance_artifact"] = str(outside)
    elif forgery == "missing":
        Path(reference["acceptance_artifact"]).unlink()
    elif forgery == "external-evidence":
        from cli.lib.acceptance import validate_acceptance_receipt

        external = tmp_path / "external-evidence"
        external.mkdir()
        for stage in accepted.receipt["checks"][0]["evidence"]["stages"]:
            for evidence in stage["artifacts"]:
                retained = Path(evidence["retained_path"])
                (external / evidence["sha256"]).write_bytes(retained.read_bytes())
                retained.unlink()
        proof = Path(reference["acceptance_artifact"])
        assert validate_acceptance_receipt(tmp_path, proof, evidence_directory=external)["state"] == "success"
        with pytest.raises(AcceptanceError):
            validate_source_receipt(tmp_path, reference, evidence_directory=external)
        with pytest.raises(AcceptanceError):
            validate_source_receipt(tmp_path, proof, evidence_directory=external)
        return
    elif forgery == "incomplete":
        reference.pop("schema_version")
    elif forgery == "root-symlink":
        directory = Path(reference["acceptance_artifact"]).parent
        relocated = tmp_path / "relocated-proof"
        directory.rename(relocated)
        directory.symlink_to(relocated, target_is_directory=True)
    elif forgery:
        reference[forgery] = "forged"
    if forgery:
        with pytest.raises(AcceptanceError):
            validate_source_receipt(tmp_path, reference)
    else:
        reopened = validate_source_receipt(tmp_path, reference)
        assert reopened.reference == accepted.reference
        assert "inputs" not in reopened.reference.to_dict()


@pytest.mark.parametrize("coverage", ["task", "full"])
def test_reuse_keeps_proof_association_separate_from_current_task(tmp_path: Path, coverage) -> None:
    from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt

    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "owned.py").write_text("value = 1\n")
    (tmp_path / "other.py").write_text("value = 2\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=tmp_path, check=True)
    def runner(command, cwd):
        return subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")
    original = accept_source(tmp_path, sha="HEAD", materialization="actual", coverage=coverage,
                             scope=("owned.py",), task_id="original-task", runner=runner)
    selected_scope = ("owned.py",) if coverage == "task" else ("other.py",)
    selected = accept_source(tmp_path, sha="HEAD", materialization="actual", coverage=coverage,
                             scope=selected_scope, task_id="current-task", runner=runner)
    assert selected.reused is True
    assert selected.task_id == "current-task" and selected.scope == selected_scope
    assert selected.reference == original.reference
    assert validate_source_receipt(tmp_path, selected.reference.to_dict()).reference == original.reference
    assert validate_source_receipt(tmp_path, selected.to_dict()).reference == original.reference
