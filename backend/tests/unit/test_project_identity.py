"""Unit tests for repo-local project identity manifests."""

from __future__ import annotations

import json
from pathlib import Path


def test_get_project_identity_prefers_explicit_root_path(tmp_path: Path) -> None:
    from app import project_identity

    root_path = tmp_path / "a-term"
    root_path.mkdir()
    manifest_path = root_path / "project.identity.json"
    manifest_path.write_text(
        json.dumps(
            {
                "project": {
                    "id": "a-term",
                    "display_name": "A-Term",
                }
            }
        )
    )
    project_identity._read_manifest.cache_clear()

    identity = project_identity.get_project_identity("a-term", str(root_path))

    assert identity is not None
    assert identity["project"]["display_name"] == "A-Term"


def test_canonicalize_project_name_falls_back_without_manifest() -> None:
    from app.project_identity import canonicalize_project_name

    assert canonicalize_project_name("missing-project", "Fallback Name") == "Fallback Name"


def test_get_project_identity_resolves_legacy_ids_via_workspace_scan(tmp_path: Path, monkeypatch) -> None:
    from app import project_identity

    projects_root = tmp_path / "projects"
    repo_root = projects_root / "a-term"
    repo_root.mkdir(parents=True)
    (repo_root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": "a-term",
                    "repo_name": "a-term",
                    "legacy_ids": ["aterm", "terminal"],
                    "repo_aliases": ["aterm", "terminal"],
                    "display_name": "A-Term",
                }
            }
        )
    )

    monkeypatch.setattr(project_identity, "_PROJECTS_ROOT", projects_root)
    project_identity._read_manifest.cache_clear()
    project_identity._workspace_manifest_paths.cache_clear()

    identity = project_identity.get_project_identity("aterm")

    assert identity is not None
    assert identity["project"]["display_name"] == "A-Term"


def test_get_project_identity_resolves_sibling_checkout_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app import project_identity

    projects_root = tmp_path / "projects"
    summitflow_root = projects_root / "summitflow"
    agent_hub_root = projects_root / "agent-hub"
    summitflow_root.mkdir(parents=True)
    agent_hub_root.mkdir()
    (agent_hub_root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": "agent-hub",
                    "repo_name": "agent-hub",
                    "display_name": "Agent Hub",
                }
            }
        )
    )

    monkeypatch.setattr(project_identity, "get_repo_root", lambda: summitflow_root)
    monkeypatch.setattr(project_identity, "_PROJECTS_ROOT", tmp_path / "unused")
    project_identity._read_manifest.cache_clear()
    project_identity._local_manifest_paths.cache_clear()
    project_identity._workspace_manifest_paths.cache_clear()

    identity = project_identity.get_project_identity("agent-hub")

    assert identity is not None
    assert identity["project"]["display_name"] == "Agent Hub"
    assert project_identity.get_project_identity_root("agent-hub") == str(
        agent_hub_root.resolve()
    )


def test_get_project_aliases_prefers_canonical_id_first(tmp_path: Path, monkeypatch) -> None:
    from app import project_identity

    projects_root = tmp_path / "projects"
    repo_root = projects_root / "a-term"
    repo_root.mkdir(parents=True)
    (repo_root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": "a-term",
                    "repo_name": "a-term",
                    "legacy_ids": ["aterm", "terminal"],
                    "repo_aliases": ["aterm", "terminal-legacy"],
                    "display_name": "A-Term",
                }
            }
        )
    )

    monkeypatch.setattr(project_identity, "_PROJECTS_ROOT", projects_root)
    project_identity._read_manifest.cache_clear()
    project_identity._workspace_manifest_paths.cache_clear()

    aliases = project_identity.get_project_aliases("terminal")

    assert aliases == ("a-term", "aterm", "terminal", "terminal-legacy")
    assert project_identity.get_project_canonical_id("terminal") == "a-term"
    assert project_identity.get_project_identity_root("terminal") == str(repo_root.resolve())


def test_get_project_upload_dir_name_uses_manifest_artifacts(tmp_path: Path, monkeypatch) -> None:
    from app import project_identity

    projects_root = tmp_path / "projects"
    repo_root = projects_root / "a-term"
    repo_root.mkdir(parents=True)
    (repo_root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": "a-term",
                    "repo_name": "a-term",
                    "legacy_ids": ["terminal"],
                },
                "artifacts": {
                    "upload_dir_name": "a-term-uploads",
                },
            }
        )
    )

    monkeypatch.setattr(project_identity, "_PROJECTS_ROOT", projects_root)
    project_identity._read_manifest.cache_clear()
    project_identity._workspace_manifest_paths.cache_clear()

    assert project_identity.get_project_upload_dir_name("terminal") == "a-term-uploads"
