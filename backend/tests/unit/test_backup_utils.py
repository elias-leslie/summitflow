"""Unit tests for backup task helpers."""

from __future__ import annotations

import json
from pathlib import Path

from app.storage.connection import get_connection


def test_get_source_path_falls_back_to_manifest_upload_dir(tmp_path: Path, monkeypatch) -> None:
    from app import project_identity
    from app.tasks import backup_utils

    home_dir = tmp_path / "home"
    home_dir.mkdir()
    canonical_upload_dir = home_dir / "a-term-uploads"
    canonical_upload_dir.mkdir()

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

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(project_identity, "_PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(backup_utils, "_HOST_HOME_PATH", str(home_dir))
    project_identity._read_manifest.cache_clear()
    project_identity._workspace_manifest_paths.cache_clear()

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM backup_sources WHERE id = 'terminal-uploads'")
        cur.execute(
            """
            INSERT INTO backup_sources (id, name, path, source_type)
            VALUES (%s, %s, %s, 'workspace')
            """,
            ("terminal-uploads", "Terminal Uploads", str(home_dir / "terminal-uploads")),
        )
        conn.commit()

    try:
        assert backup_utils.get_source_path("terminal-uploads") == str(canonical_upload_dir)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = 'terminal-uploads'")
            conn.commit()
        project_identity._read_manifest.cache_clear()
        project_identity._workspace_manifest_paths.cache_clear()
