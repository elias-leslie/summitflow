"""Tests for page scan metadata contracts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.explorer.types.pages import PageScanner


def test_page_scanner_includes_url_and_port_for_nextjs_pages(tmp_path: Path) -> None:
    """Next.js page entries should expose a canonical URL for downstream tools."""
    root = tmp_path / "repo"
    page_dir = root / "frontend" / "app" / "settings"
    page_dir.mkdir(parents=True)
    (page_dir / "page.tsx").write_text("export default function Page() { return null }", encoding="utf-8")

    with patch(
        "app.services.explorer.types.pages.get_project_config",
        return_value={
            "id": "demo",
            "root_path": str(root),
            "frontend_dir": "frontend",
            "frontend_port": 3105,
            "base_url": "http://localhost:3105",
        },
    ):
        result = PageScanner("demo").scan()

    assert len(result) == 1
    assert result[0].path == "/settings"
    assert result[0].metadata["port"] == 3105
    assert result[0].metadata["url"] == "http://localhost:3105/settings"


def test_page_scanner_uses_detected_frontend_port_when_base_url_missing(tmp_path: Path) -> None:
    """Port detection should still produce a usable page URL."""
    root = tmp_path / "repo"
    app_dir = root / "frontend" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "page.tsx").write_text("export default function Page() { return null }", encoding="utf-8")

    with patch(
        "app.services.explorer.types.pages.get_project_config",
        return_value={
            "id": "demo",
            "root_path": str(root),
            "frontend_dir": "frontend",
            "frontend_port": None,
            "base_url": None,
        },
    ), patch(
        "app.services.explorer.types.pages.get_services",
        return_value={"frontend_port": 3110},
    ):
        result = PageScanner("demo").scan()

    assert len(result) == 1
    assert result[0].path == "/"
    assert result[0].metadata["port"] == 3110
    assert result[0].metadata["url"] == "http://localhost:3110/"


def test_page_scanner_strips_route_groups_from_paths(tmp_path: Path) -> None:
    """Next.js route groups like (app) should not appear in page URLs."""
    root = tmp_path / "repo"
    app_dir = root / "frontend" / "app"

    # Create pages inside route groups
    for subpath in ("(app)", "(app)/docker", "(app)/backups", "(standalone)/notes"):
        d = app_dir / subpath
        d.mkdir(parents=True, exist_ok=True)
        (d / "page.tsx").write_text("export default function P() { return null }", encoding="utf-8")

    with patch(
        "app.services.explorer.types.pages.get_project_config",
        return_value={
            "id": "demo",
            "root_path": str(root),
            "frontend_dir": "frontend",
            "frontend_port": 3001,
            "base_url": "http://localhost:3001",
        },
    ):
        result = PageScanner("demo").scan()

    paths = {e.path for e in result}
    names = {e.path: e.name for e in result}

    assert "/" in paths, f"Root page missing, got {paths}"
    assert "/docker" in paths, f"/docker missing, got {paths}"
    assert "/backups" in paths, f"/backups missing, got {paths}"
    assert "/notes" in paths, f"/notes missing, got {paths}"

    # Route group names must not leak into paths
    assert not any("(app)" in p or "(standalone)" in p for p in paths), f"Route group in paths: {paths}"
    assert not any("/app/" in p for p in paths), f"/app/ prefix leaked: {paths}"

    # Root page name should be 'home', not '(app)'
    assert names["/"] == "home"
