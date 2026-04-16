"""Shell-level tests for worktree node workspace preparation hooks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _write_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n  - frontend\n",
        encoding="utf-8",
    )


def _write_package_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": path.parent.name}), encoding="utf-8")


def _copy_script_harness(tmp_path: Path, source_name: str, *, strip_main: bool = False, truncate_before: str | None = None) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    source = repo_root / "scripts" / source_name
    script_root = tmp_path / "scripts"
    lib_root = script_root / "lib"
    shutil.copytree(repo_root / "scripts" / "lib", lib_root, dirs_exist_ok=True)

    content = source.read_text(encoding="utf-8")
    if truncate_before is not None:
        content = content.split(truncate_before, 1)[0]
    if strip_main:
        content = content.rsplit('\nmain "$@"\n', 1)[0] + "\n"

    target = script_root / source_name
    target.write_text(content, encoding="utf-8")
    return target


def test_worktree_services_prepare_node_workspace_removes_external_symlinks(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    main_root = tmp_path / "projects" / "summitflow"
    lane_root = tmp_path / "lanes" / "summitflow" / "task-1"
    _write_workspace(main_root)
    _write_workspace(lane_root)
    _write_package_json(main_root / "frontend" / "package.json")
    _write_package_json(lane_root / "frontend" / "package.json")

    (lane_root / "node_modules").symlink_to(main_root / "node_modules")
    (lane_root / "frontend" / "node_modules").symlink_to(main_root / "frontend" / "node_modules")

    harness = _copy_script_harness(tmp_path / "worktree-services", "worktree-services.sh", strip_main=True)

    result = subprocess.run(
        [
            "bash",
            "-lc",
            f"""
set -euo pipefail
source {str(harness)!r}
SUMMITFLOW_ROOT_OVERRIDE={str(repo_root)!r}
PROJECT_ID=summitflow
resolve_project_root() {{ printf '%s\\n' {str(main_root)!r}; }}
find_venv_python() {{ printf '%s\\n' {sys.executable!r}; }}
result=$(prepare_node_workspace {str(lane_root)!r} frontend)
printf 'RESULT:%s\\n' "$result"
test ! -e {str(lane_root / 'node_modules')!r}
test ! -e {str(lane_root / 'frontend' / 'node_modules')!r}
""",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().endswith("true")


def test_rebuild_prepare_node_workspace_for_rebuild_removes_external_symlinks(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    main_root = tmp_path / "projects" / "summitflow"
    lane_root = tmp_path / "lanes" / "summitflow" / "task-2"
    _write_workspace(main_root)
    _write_workspace(lane_root)
    _write_package_json(main_root / "frontend" / "package.json")
    _write_package_json(lane_root / "frontend" / "package.json")

    (lane_root / "node_modules").symlink_to(main_root / "node_modules")
    (lane_root / "frontend" / "node_modules").symlink_to(main_root / "frontend" / "node_modules")

    harness = _copy_script_harness(
        tmp_path / "rebuild",
        "rebuild.sh",
        truncate_before='\nPROJECT="${POSITIONAL[0]:-}"\n',
    )

    result = subprocess.run(
        [
            "bash",
            "-lc",
            f"""
set -euo pipefail
source {str(harness)!r}
SUMMITFLOW_ROOT={str(repo_root)!r}
SUMMITFLOW_ROOT_OVERRIDE={str(repo_root)!r}
PROJECT=summitflow
ROOT_DIR={str(lane_root)!r}
FRONTEND_SUBDIR=frontend
resolve_project_root() {{ printf '%s\\n' {str(main_root)!r}; }}
find_venv_python() {{ printf '%s\\n' {sys.executable!r}; }}
result=$(prepare_node_workspace_for_rebuild)
printf 'RESULT:%s\\n' "$result"
test ! -e {str(lane_root / 'node_modules')!r}
test ! -e {str(lane_root / 'frontend' / 'node_modules')!r}
""",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().endswith("true")
