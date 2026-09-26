"""Project identity gate behavior for aggregate st check runs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import httpx

from cli.commands import check_dispatch
from cli.commands import check_project_identity as gate


def checkout(tmp_path: Path, *, project_id: str = "aico", lifecycle: str = "active") -> Path:
    root = tmp_path / project_id
    root.mkdir()
    (root / ".git").mkdir()
    (root / "project.identity.json").write_text(json.dumps({
        "project": {"id": project_id, "lifecycle": lifecycle},
    }))
    return root


def test_identity_gate_matches_registry_and_default_listing(tmp_path: Path, monkeypatch, capsys) -> None:
    root = checkout(tmp_path)
    def fetch(path: str):
        if path == "/projects/aico":
            return {"id": "aico", "root_path": str(root), "lifecycle": "active", "category": "dev"}
        return [{"id": "aico"}]
    monkeypatch.setattr(gate, "_fetch", fetch)
    assert gate.run_project_identity_check(root) == 0
    assert "IDENTITY:OK:aico" in capsys.readouterr().out


def test_identity_gate_fails_root_and_visibility_drift_but_lifecycle_is_advisory(tmp_path: Path, monkeypatch, capsys) -> None:
    root = checkout(tmp_path, lifecycle="retired")
    def fetch(path: str):
        if path == "/projects/aico":
            return {"id": "aico", "root_path": str(tmp_path / "old-release"), "lifecycle": "active", "category": "dev"}
        return []
    monkeypatch.setattr(gate, "_fetch", fetch)
    assert gate.run_project_identity_check(root) == 1
    output = capsys.readouterr().out
    assert "registry_root_mismatch" in output
    assert "IDENTITY:ADVISORY:manifest_lifecycle_differs:declared=retired,effective=active" in output
    assert "default_listing_mismatch" in output


def test_identity_gate_manifest_lifecycle_disagreement_does_not_fail(tmp_path: Path, monkeypatch, capsys) -> None:
    root = checkout(tmp_path, lifecycle="retired")
    def fetch(path: str):
        if path == "/projects/aico":
            return {"id": "aico", "root_path": str(root), "lifecycle": "active", "category": "dev"}
        return [{"id": "aico"}]
    monkeypatch.setattr(gate, "_fetch", fetch)
    assert gate.run_project_identity_check(root) == 0
    assert "IDENTITY:ADVISORY:manifest_lifecycle_differs" in capsys.readouterr().out


def test_identity_gate_allows_hidden_testing_fixture_and_no_runtime(tmp_path: Path, monkeypatch) -> None:
    root = checkout(tmp_path, project_id="test1")
    def fetch(path: str):
        if path == "/projects/test1":
            return {"id": "test1", "root_path": str(root), "lifecycle": "active", "category": "testing"}
        return []
    monkeypatch.setattr(gate, "_fetch", fetch)
    assert gate.run_project_identity_check(root) == 0


def test_identity_gate_checks_local_manifest_when_api_offline(tmp_path: Path, monkeypatch, capsys) -> None:
    root = checkout(tmp_path)
    def offline(_path: str):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(gate, "_fetch", offline)
    assert gate.run_project_identity_check(root) == 0
    assert "IDENTITY:UNKNOWN:registry_unavailable" in capsys.readouterr().out
    (root / ".git").rmdir()
    assert gate.run_project_identity_check(root) == 1


def test_identity_gate_rejects_invalid_local_identity_without_api(tmp_path: Path, monkeypatch, capsys) -> None:
    root = checkout(tmp_path)
    (root / "project.identity.json").write_text(json.dumps({"project": {"id": "aico", "lifecycle": "archived"}}))
    fetch = Mock()
    monkeypatch.setattr(gate, "_fetch", fetch)
    assert gate.run_project_identity_check(root) == 1
    assert "invalid_lifecycle" in capsys.readouterr().out
    fetch.assert_not_called()


def test_identity_gate_skips_repos_without_manifest(tmp_path: Path, capsys) -> None:
    assert gate.run_project_identity_check(tmp_path) == 0
    assert "IDENTITY:SKIP:no_manifest" in capsys.readouterr().out


def test_identity_gate_allows_git_worktree_at_another_path(tmp_path: Path, monkeypatch, capsys) -> None:
    root = checkout(tmp_path)
    (root / ".git").rmdir()
    (root / ".git").write_text("gitdir: /example/worktrees/aico")
    def fetch(path: str):
        if path == "/projects/aico":
            return {"id": "aico", "root_path": str(tmp_path / "canonical"), "lifecycle": "active", "category": "dev"}
        return [{"id": "aico"}]
    monkeypatch.setattr(gate, "_fetch", fetch)
    assert gate.run_project_identity_check(root) == 0
    assert "worktree_registry_root_differs" in capsys.readouterr().out


def test_aggregate_check_runs_identity_gate(tmp_path: Path) -> None:
    runtime = Mock(spec=list(check_dispatch.CheckRuntime.__dataclass_fields__))
    runtime.resolve_repo_root.return_value = tmp_path
    runtime.run_architecture_check.return_value = 0
    runtime.run_project_identity_check.return_value = 1
    result = check_dispatch.run_selected([], {}, fix=False, changed_only=True, runtime=runtime)
    assert result == 1
    runtime.run_project_identity_check.assert_called_once_with(tmp_path)
