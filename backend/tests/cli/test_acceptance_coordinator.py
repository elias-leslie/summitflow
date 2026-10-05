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
