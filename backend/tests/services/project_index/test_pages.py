"""Live frontend page discovery."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.project_index.pages import discover_pages

_MODULE = "app.services.project_index.pages"


def _page(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "page.tsx").write_text("export default function Page() { return null }", encoding="utf-8")


def _config(root: Path, **overrides: object) -> dict[str, object]:
    return {"root_path": str(root), "base_url": None, "frontend_port": None, "backend_port": None, **overrides}


def test_nextjs_pages_expose_url_and_port(tmp_path: Path) -> None:
    _page(tmp_path / "frontend" / "app" / "settings")

    with patch(f"{_MODULE}.get_project_config", return_value=_config(
        tmp_path, frontend_port=3105, base_url="http://localhost:3105/",
    )), patch(f"{_MODULE}.get_services") as services:
        pages = discover_pages("demo")

    assert pages == [{"path": "/settings", "name": "settings", "url": "http://localhost:3105/settings", "port": 3105}]
    services.assert_not_called()


def test_detected_frontend_port_supplies_url_when_base_url_missing(tmp_path: Path) -> None:
    _page(tmp_path / "frontend" / "src" / "app")

    with (
        patch(f"{_MODULE}.get_project_config", return_value=_config(tmp_path)),
        patch(f"{_MODULE}.get_services", return_value={"frontend_port": 3110}),
    ):
        pages = discover_pages("demo")

    assert pages == [{"path": "/", "name": "home", "url": "http://localhost:3110/", "port": 3110}]


def test_route_groups_and_dynamic_segments(tmp_path: Path) -> None:
    app_dir = tmp_path / "frontend" / "app"
    for subpath in ("(app)", "(app)/docker", "(app)/backups", "(standalone)/notes", "projects/[id]"):
        _page(app_dir / subpath)

    with patch(f"{_MODULE}.get_project_config", return_value=_config(tmp_path, frontend_port=3001)):
        pages = discover_pages("demo")

    assert [(page["path"], page["name"]) for page in pages] == [
        ("/", "home"),
        ("/backups", "backups"),
        ("/docker", "docker"),
        ("/notes", "notes"),
        ("/projects/:id", "projects/:id"),
    ]
    assert all(page["url"] is None and page["port"] == 3001 for page in pages)


def test_spa_index_html_fallback(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    with (
        patch(f"{_MODULE}.get_project_config", return_value=_config(tmp_path, base_url="https://demo.example")),
        patch(f"{_MODULE}.get_services", return_value={}),
    ):
        pages = discover_pages("demo")

    assert pages == [{"path": "/", "name": "home", "url": "https://demo.example/", "port": None}]


def test_no_frontend_or_unknown_project_is_empty(tmp_path: Path) -> None:
    with patch(f"{_MODULE}.get_project_config", return_value=_config(tmp_path)):
        assert discover_pages("demo") == []
    with patch(f"{_MODULE}.get_project_config", return_value=None):
        assert discover_pages("missing") == []
