"""Tests for Graphify project graph endpoints."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.storage.connection import get_connection


@pytest.fixture
def graphify_project(db_schema_initialized: None, tmp_path: Path) -> Generator[tuple[str, Path]]:
    project_id = "graphify-api-test"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
                base_url = EXCLUDED.base_url,
                root_path = EXCLUDED.root_path
            """,
            (project_id, "Graphify API Test", "http://localhost:3001", str(tmp_path)),
        )
        conn.commit()

    yield project_id, tmp_path

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def _write_graphify_outputs(root: Path) -> None:
    out = root / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(
        """
        {
          "nodes": [
            {"id": "a", "label": "A", "community": 1},
            {"id": "b", "label": "B", "community": 2}
          ],
          "links": [{"source": "a", "target": "b", "relation": "calls"}]
        }
        """,
        encoding="utf-8",
    )
    (out / "graph.html").write_text("<!doctype html><title>Graph</title>", encoding="utf-8")
    (out / "GRAPH_REPORT.md").write_text("# Report\n", encoding="utf-8")


def test_graphify_status_and_static_outputs(
    client: TestClient,
    graphify_project: tuple[str, Path],
) -> None:
    project_id, root = graphify_project
    _write_graphify_outputs(root)

    status_response = client.get(f"/api/projects/{project_id}/graphify/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["graph_exists"] is True
    assert status["html_available"] is True
    assert status["report_available"] is True
    assert status["node_count"] == 2
    assert status["edge_count"] == 1
    assert status["community_count"] == 2
    assert status["html_url"] == f"/api/projects/{project_id}/graphify/html"

    html_response = client.get(f"/api/projects/{project_id}/graphify/html")
    assert html_response.status_code == 200
    assert "Graph" in html_response.text

    report_response = client.get(f"/api/projects/{project_id}/graphify/report")
    assert report_response.status_code == 200
    assert report_response.text == "# Report\n"


def test_graphify_update_runs_code_only_refresh(
    client: TestClient,
    graphify_project: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, root = graphify_project
    _write_graphify_outputs(root)
    commands: list[tuple[list[str], Path]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        text: bool,
        capture_output: bool,
        timeout: int,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append((command, cwd))
        assert text is True
        assert capture_output is True
        assert timeout == 180
        assert check is False
        return subprocess.CompletedProcess(command, 0, stdout="updated", stderr="")

    monkeypatch.setattr("app.api.graphify._graphify_bin", lambda: "/usr/bin/graphify")
    monkeypatch.setattr("app.api.graphify.subprocess.run", fake_run)

    response = client.post(f"/api/projects/{project_id}/graphify/update")
    assert response.status_code == 200
    assert response.json()["output"] == "updated"
    assert commands == [(["/usr/bin/graphify", "update", str(root)], root)]
