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
