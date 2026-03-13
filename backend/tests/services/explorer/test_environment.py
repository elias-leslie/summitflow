from __future__ import annotations

import json
from pathlib import Path

from app.services.explorer.environment import _read_node_info


def test_read_node_info_prefers_package_manager_field(tmp_path: Path) -> None:
    """Package manager should come from package.json when explicitly pinned."""
    package_json = tmp_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "engines": {"node": "24"},
                "packageManager": "pnpm@10.28.0",
            }
        )
    )

    info = _read_node_info(package_json, tmp_path)

    assert info == {"node_version": "24", "package_manager": "pnpm"}


def test_read_node_info_fallback_to_lockfile_detection(tmp_path: Path) -> None:
    """When packageManager field is missing, fallback to lockfile detection."""
    package_json = tmp_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "engines": {"node": "20"},
            }
        )
    )
    (tmp_path / "pnpm-lock.yaml").touch()

    info = _read_node_info(package_json, tmp_path)

    assert info == {"node_version": "20", "package_manager": "pnpm"}


def test_read_node_info_raw_package_manager_without_version(tmp_path: Path) -> None:
    """When packageManager has no @version suffix, ensure it returns that raw value."""
    package_json = tmp_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "engines": {"node": "18"},
                "packageManager": "yarn",
            }
        )
    )

    info = _read_node_info(package_json, tmp_path)

    assert info == {"node_version": "18", "package_manager": "yarn"}
