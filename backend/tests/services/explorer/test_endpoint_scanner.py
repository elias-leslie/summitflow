"""Tests for endpoint scanning edge cases."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.explorer.types.endpoints import EndpointScanner


def test_endpoint_scanner_keeps_project_health_routes(tmp_path: Path) -> None:
    """Project-specific health endpoints should not be filtered out as boilerplate."""
    root = tmp_path / "repo"
    api_dir = root / "backend" / "app" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "quality_gate.py").write_text(
        '''
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/projects/{project_id}/quality/health")
async def get_health_summary(project_id: str) -> dict[str, str]:
    return {"project_id": project_id}
''',
        encoding="utf-8",
    )

    with patch(
        "app.services.explorer.types.endpoints.get_project_config",
        return_value={"id": "demo", "root_path": str(root)},
    ):
        entries = EndpointScanner("demo").scan()

    paths = [entry.path for entry in entries]
    assert "GET /health" not in paths
    assert "GET /projects/{project_id}/quality/health" in paths
