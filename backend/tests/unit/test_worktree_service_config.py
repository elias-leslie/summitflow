"""Unit tests for manifest-derived worktree service config."""

from __future__ import annotations

import json
from pathlib import Path


def _write_manifest(root: Path, payload: dict[str, object]) -> None:
    (root / "project.identity.json").write_text(json.dumps(payload), encoding="utf-8")


def _set_projects_root(monkeypatch, projects_root: Path) -> None:
    from app import project_identity

    monkeypatch.setattr(project_identity, "_PROJECTS_ROOT", projects_root)
    project_identity._read_manifest.cache_clear()
    project_identity._workspace_manifest_paths.cache_clear()


def test_load_project_worktree_services_rewrites_ports_and_api_urls(tmp_path: Path, monkeypatch) -> None:
    from app.worktree_service_config import load_project_worktree_services_dict

    projects_root = tmp_path / "projects"
    repo_root = projects_root / "agent-hub"
    (repo_root / "backend").mkdir(parents=True)
    (repo_root / "frontend" / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "systemd").mkdir(parents=True)
    (repo_root / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "next build", "start": "next start"}}),
        encoding="utf-8",
    )
    (repo_root / "frontend" / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    _write_manifest(
        repo_root,
        {
            "project": {"id": "agent-hub", "repo_name": "agent-hub"},
            "runtime": {
                "backend_port": 8003,
                "frontend_port": 3003,
                "backend_dir": "backend",
                "frontend_dir": "frontend",
            },
            "services": {
                "backend": "agent-hub-backend.service",
                "frontend": "agent-hub-frontend.service",
            },
        },
    )
    (repo_root / "scripts" / "systemd" / "agent-hub-backend.service").write_text(
        "\n".join(
            [
                "[Service]",
                "WorkingDirectory=__PROJECT_ROOT__/backend",
                'Environment="PYTHONUNBUFFERED=1"',
                'ExecStart=/bin/bash -lc \'__PROJECT_ROOT__/backend/.venv/bin/uvicorn app.main:app --host "${AGENT_HUB_BIND_HOST:-0.0.0.0}" --port "${AGENT_HUB_PORT:-8003}"\'',
            ]
        ),
        encoding="utf-8",
    )
    (repo_root / "scripts" / "systemd" / "agent-hub-frontend.service").write_text(
        "\n".join(
            [
                "[Service]",
                "WorkingDirectory=__PROJECT_ROOT__/frontend",
                "EnvironmentFile=-%h/.env.local",
                'Environment="NODE_ENV=production"',
                'Environment="PORT=3003"',
                'Environment="AGENT_HUB_API_URL=http://localhost:8003"',
                'ExecStart=/bin/bash -lc "pnpm start --hostname 0.0.0.0 --port 3003"',
            ]
        ),
        encoding="utf-8",
    )
    _set_projects_root(monkeypatch, projects_root)

    config = load_project_worktree_services_dict("agent-hub")

    backend = config["services"]["backend"]
    frontend = config["services"]["frontend"]
    assert config["config_source"] == "project_identity"
    assert backend["cwd"] == "backend"
    assert backend["environment"]["AGENT_HUB_PORT"] == "${SF_WORKTREE_BACKEND_PORT}"
    assert frontend["cwd"] == "frontend"
    assert frontend["env_files"] == []
    assert frontend["environment"]["PORT"] == "${PORT}"
    assert frontend["environment"]["AGENT_HUB_API_URL"] == "http://localhost:${SF_WORKTREE_BACKEND_PORT}"
    assert frontend["command"] == "pnpm start --hostname 0.0.0.0 --port ${PORT}"
    assert frontend["install_command"] == "pnpm install"
    assert frontend["build_command"] == "pnpm build"


def test_load_project_worktree_services_preserves_dynamic_frontend_command(tmp_path: Path, monkeypatch) -> None:
    from app.worktree_service_config import load_project_worktree_services_dict

    projects_root = tmp_path / "projects"
    repo_root = projects_root / "a-term"
    (repo_root / "frontend").mkdir(parents=True)
    (repo_root / "scripts" / "systemd").mkdir(parents=True)
    (repo_root / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "next build", "start": "next start"}}),
        encoding="utf-8",
    )
    _write_manifest(
        repo_root,
        {
            "project": {"id": "a-term", "repo_name": "a-term"},
            "runtime": {
                "backend_port": 8002,
                "frontend_port": 3002,
                "backend_dir": ".",
                "frontend_dir": "frontend",
            },
            "services": {
                "backend": "a-term-backend.service",
                "frontend": "a-term-frontend.service",
            },
        },
    )
    (repo_root / "scripts" / "systemd" / "a-term-backend.service").write_text(
        "\n".join(
            [
                "[Service]",
                "WorkingDirectory=__PROJECT_ROOT__",
                'ExecStart=/bin/bash -lc \'export A_TERM_PORT="${A_TERM_PORT:-8002}"; exec __PROJECT_ROOT__/.venv/bin/uvicorn a_term.main:app --port "$A_TERM_PORT"\'',
            ]
        ),
        encoding="utf-8",
    )
    (repo_root / "scripts" / "systemd" / "a-term-frontend.service").write_text(
        "\n".join(
            [
                "[Service]",
                "WorkingDirectory=__PROJECT_ROOT__/frontend",
                "EnvironmentFile=-__PROJECT_ROOT__/.env.local",
                'ExecStart=/bin/bash -lc \'export API_URL="${API_URL:-http://127.0.0.1:${A_TERM_PORT:-8002}}"; export HOSTNAME="${A_TERM_FRONTEND_HOST:-127.0.0.1}"; export PORT="${A_TERM_FRONTEND_PORT:-3002}"; exec corepack pnpm start --hostname "$HOSTNAME" --port "$PORT"\'',
            ]
        ),
        encoding="utf-8",
    )
    _set_projects_root(monkeypatch, projects_root)

    config = load_project_worktree_services_dict("a-term")
    frontend = config["services"]["frontend"]

    assert frontend["env_files"] == [".env.local"]
    assert frontend["environment"]["A_TERM_PORT"] == "${SF_WORKTREE_BACKEND_PORT}"
    assert frontend["environment"]["A_TERM_FRONTEND_PORT"] == "${SF_WORKTREE_FRONTEND_PORT}"
    assert 'corepack pnpm start --hostname "$HOSTNAME" --port "$PORT"' in frontend["command"]
    assert frontend["install_command"] == "corepack pnpm install"
    assert frontend["build_command"] == "corepack pnpm build"
