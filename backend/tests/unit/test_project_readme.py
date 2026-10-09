"""Project overview reads stay bounded to the canonical root README."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.projects import readme
from app.services.file_browser import MAX_FILE_SIZE


def test_readme_tracks_checkout_edits_and_preserves_empty_content(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("# Example\n\nA project description.")
    result = readme.read_project_readme("example", str(tmp_path))
    assert result.status == "available"
    assert result.content == target.read_text()
    target.write_text("")
    assert readme.read_project_readme("example", str(tmp_path)).content == ""


def test_missing_readme_differs_from_unavailable_root(tmp_path: Path) -> None:
    assert readme.read_project_readme("example", str(tmp_path)).status == "missing"
    assert readme.read_project_readme("example", None).status == "unavailable"
    assert readme.read_project_readme("example", str(tmp_path / "absent")).status == "unavailable"


@pytest.mark.parametrize("outside", [False, True])
def test_readme_symlinks_cannot_expose_other_files(tmp_path: Path, outside: bool) -> None:
    root = tmp_path / "root"
    root.mkdir()
    other = (tmp_path if outside else root) / "private.txt"
    other.write_text("private data")
    (root / "README.md").symlink_to(other)
    result = readme.read_project_readme("example", str(root))
    assert result.status == "unavailable"
    assert result.content is None


@pytest.mark.parametrize("content", [b"binary\x00content", b"x" * (MAX_FILE_SIZE + 1)], ids=["binary", "oversized"])
def test_unreadable_formats_do_not_show_partial_document(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "README.md").write_bytes(content)
    result = readme.read_project_readme("example", str(tmp_path))
    assert result.status == "unavailable"
    assert result.content is None


def test_read_errors_are_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "README.md").write_text("# Example")
    def denied(*args: object) -> dict:
        raise PermissionError("denied")
    monkeypatch.setattr(readme.file_browser, "read_file", denied)
    assert readme.read_project_readme("example", str(tmp_path)).status == "unavailable"


def test_route_uses_registered_root_and_preserves_unknown_project_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "README.md").write_text("# Registered project")
    def lookup(project_id: str) -> SimpleNamespace:
        if project_id != "registered":
            raise HTTPException(status_code=404, detail="Project not found")
        return SimpleNamespace(id=project_id, root_path=str(tmp_path))
    monkeypatch.setattr(readme, "get_project_from_db", lookup)
    app = FastAPI()
    app.include_router(readme.router, prefix="/api/projects")
    with TestClient(app) as client:
        response = client.get("/api/projects/registered/readme")
        assert response.status_code == 200
        assert response.json()["content"] == "# Registered project"
        assert client.get("/api/projects/unknown/readme").status_code == 404
