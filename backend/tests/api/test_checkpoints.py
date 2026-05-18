"""Tests for the checkpoints API."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.api.checkpoint_helpers import get_project_checkpoints
from app.main import app

client = TestClient(app)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")


def _write_checkpoint(home: Path, project_id: str, task_id: str) -> None:
    checkpoint_dir = home / ".local" / "share" / "st" / "checkpoints" / project_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / f"{task_id}.meta.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "project_id": project_id,
                "base_branch": "main",
                "created_at": "2026-03-24T06:00:00+00:00",
                "claimed_by": "Test",
            }
        ),
        encoding="utf-8",
    )


def test_get_project_checkpoints_reads_canonical_active_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _init_repo(repo)
    _git(repo, "branch", "task-live/main")
    _write_checkpoint(home, "summitflow", "task-live")
    _write_checkpoint(home, "summitflow", "task-stale")
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda project_id: str(repo))
    monkeypatch.setattr("cli.lib.checkpoint_branches._get_repo_cwd", lambda project_id: str(repo))

    checkpoints = get_project_checkpoints("summitflow")

    assert [checkpoint["task_id"] for checkpoint in checkpoints] == ["task-live"]
    assert checkpoints[0]["base_branch"] == "main"


def test_list_checkpoints_endpoint_omits_stale_metadata(mocker: MockerFixture) -> None:
    mocker.patch(
        "app.api.checkpoints.get_project_checkpoints",
        return_value=[
            {
                "task_id": "task-live",
                "project_id": "summitflow",
                "base_branch": "main",
                "created_at": "2026-03-24T06:00:00+00:00",
                "claimed_by": "Test",
                "age": "1h ago",
            }
        ],
    )

    response = client.get("/api/checkpoints", params={"project_id": "summitflow"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["checkpoints"][0]["task_id"] == "task-live"
