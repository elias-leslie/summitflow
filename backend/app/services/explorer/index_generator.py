"""Index file generator for Explorer service.

Generates a .index.yaml file at project root containing:
- Top-level directories with 1-line descriptions
- File counts per directory
- Key patterns detected (configs, tests, docs, etc.)

Constraint: Output must be <100 lines to stay scannable by AI.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

from ...logging_config import get_logger
from ...storage import explorer as storage
from .base import get_project_root

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def generate_index(project_id: str) -> str:
    """Generate a YAML index string from explorer entries.

    Args:
        project_id: Project to generate index for

    Returns:
        YAML string with folder structure and descriptions
    """
    entries = storage.get_entries(project_id, {"type": "file", "limit": 10000})

    if not entries:
        result: str = yaml.dump({"project": project_id, "folders": {}}, default_flow_style=False)
        return result

    # Group entries by top-level directory
    folders: dict[str, dict[str, Any]] = {}

    for entry in entries:
        path = entry.get("path", "")
        parts = path.split("/")

        folder = "(root)" if len(parts) < 2 else parts[0]

        if folder not in folders:
            folders[folder] = {
                "files": 0,
                "extensions": set(),
                "patterns": set(),
            }

        folders[folder]["files"] += 1

        # Track extensions
        if "." in parts[-1]:
            ext = parts[-1].rsplit(".", 1)[-1]
            folders[folder]["extensions"].add(ext)

        # Detect patterns from path
        path_lower = path.lower()
        if "test" in path_lower or "spec" in path_lower:
            folders[folder]["patterns"].add("tests")
        if "config" in path_lower or parts[-1] in (
            "package.json",
            "pyproject.toml",
            "tsconfig.json",
        ):
            folders[folder]["patterns"].add("config")
        if "readme" in path_lower or path_lower.endswith(".md"):
            folders[folder]["patterns"].add("docs")
        if "api" in path_lower or "endpoint" in path_lower or "route" in path_lower:
            folders[folder]["patterns"].add("api")
        if "component" in path_lower or path_lower.endswith(".tsx"):
            folders[folder]["patterns"].add("components")
        if "model" in path_lower or "schema" in path_lower:
            folders[folder]["patterns"].add("models")
        if "service" in path_lower:
            folders[folder]["patterns"].add("services")
        if "storage" in path_lower or "db" in path_lower or "database" in path_lower:
            folders[folder]["patterns"].add("storage")

    # Generate descriptions
    output_folders: dict[str, str] = {}

    for folder, info in sorted(folders.items()):
        patterns = sorted(info["patterns"])
        exts = sorted(info["extensions"])[:5]  # Limit to 5 most common

        desc_parts = [f"{info['files']} files"]

        if patterns:
            desc_parts.append(", ".join(patterns))

        if exts:
            desc_parts.append(f"({', '.join(exts)})")

        output_folders[folder] = " - ".join(desc_parts)

    # Build final structure
    from datetime import UTC, datetime

    index_data = {
        "project": project_id,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "total_files": len(entries),
        "folders": output_folders,
    }

    yaml_result: str = yaml.dump(index_data, default_flow_style=False, sort_keys=False)
    return yaml_result


def write_index_file(project_id: str) -> str | None:
    """Generate and write .index.yaml to project root.

    Args:
        project_id: Project to generate index for

    Returns:
        Path to written file, or None if failed
    """
    root_path = get_project_root(project_id)
    if not root_path:
        logger.warning(f"No root path found for project {project_id}")
        return None

    index_content = generate_index(project_id)
    index_path = Path(root_path) / ".index.yaml"

    try:
        index_path.write_text(index_content)
        logger.info(f"Wrote index file: {index_path}")
        return str(index_path)
    except OSError as e:
        logger.error(f"Failed to write index file {index_path}: {e}")
        return None
