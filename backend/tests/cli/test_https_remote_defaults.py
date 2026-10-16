"""New GitHub remotes default to https (gh credential helper), never SSH."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cli.commands import setup

REPO_ROOT = Path(__file__).resolve().parents[3]
IDENTITY_SH = REPO_ROOT / "scripts" / "lib" / "project-identity.sh"


def _identity_env(tmp_path: Path, repository: dict) -> dict[str, str]:
    manifest = tmp_path / "project.identity.json"
    manifest.write_text(json.dumps({"project": {"id": "demo"}, "repository": repository}))
    out = subprocess.run(
        ["bash", "-c", f'. "{IDENTITY_SH}" && project_identity_load_env_from_manifest "$1"', "_", str(manifest)],
        check=True, capture_output=True, text=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


def test_identity_does_not_synthesize_ssh_url(tmp_path: Path) -> None:
    env = _identity_env(tmp_path, {"owner": "elias-leslie", "name": "demo"})
    assert env["PROJECT_IDENTITY_REPO_HTTPS_URL"] == "https://github.com/elias-leslie/demo"
    assert env["PROJECT_IDENTITY_REPO_SSH_URL"] == "''"


def test_identity_passes_explicit_ssh_url_through(tmp_path: Path) -> None:
    env = _identity_env(tmp_path, {"owner": "o", "name": "n", "ssh_url": "git@github.com:o/n.git"})
    assert env["PROJECT_IDENTITY_REPO_SSH_URL"] == "git@github.com:o/n.git"


def test_agent_tooling_clones_config_repos_over_https(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cloned: list[str] = []

    class Stop(Exception):
        pass

    def fake_ensure(url: str, target: Path, *, update_existing: bool) -> None:
        cloned.append(url)
        if len(cloned) == 2:
            raise Stop

    for var in ("CLAUDE_CONFIG_REPO", "CODEX_CONFIG_REPO"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_HOME_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME_DIR", str(tmp_path / "codex"))
    monkeypatch.setattr(setup, "_preview", lambda *args: None)
    monkeypatch.setattr(setup.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(setup, "_ensure_repo", fake_ensure)
    with pytest.raises(Stop):
        setup.agent_tooling(dry_run=False, confirm=None)
    assert cloned == [
        "https://github.com/elias-leslie/claude-config.git",
        "https://github.com/elias-leslie/codex-config.git",
    ]


def test_manifest_lookup_resolves_legacy_alias(tmp_path: Path) -> None:
    checkout = tmp_path / "renamed-dir"
    checkout.mkdir()
    manifest = checkout / "project.identity.json"
    manifest.write_text(json.dumps({"project": {"id": "demo", "legacy_ids": ["old-demo"]}}))
    out = subprocess.run(
        ["bash", "-c", f'. "{IDENTITY_SH}" && project_identity_manifest_for_project old-demo "$1"', "_", str(tmp_path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert out == str(manifest)
