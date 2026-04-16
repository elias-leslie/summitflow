"""Prepare Node-based workspaces for lane-local service runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class NodeWorkspacePreparation:
    """Summary of lane-local workspace preparation work."""

    workspace_root: str
    removed_node_modules_symlinks: list[str]
    materialized_file_dependency_links: list[str]
    needs_install: bool


def _parse_pnpm_workspace_patterns(workspace_root: Path) -> list[str]:
    workspace_file = workspace_root / "pnpm-workspace.yaml"
    if not workspace_file.is_file():
        return []

    patterns: list[str] = []
    in_packages = False
    for raw_line in workspace_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "packages:":
            in_packages = True
            continue
        if not in_packages:
            continue
        if stripped.startswith("- "):
            pattern = stripped[2:].strip().strip("'\"")
            if pattern:
                patterns.append(pattern)
            continue
        if raw_line[:1] not in {" ", "\t"}:
            break
    return patterns


def _find_workspace_root(lane_root: Path, service_dir: Path) -> Path:
    lane_root = lane_root.resolve()
    current = service_dir.resolve()
    while True:
        if (current / "pnpm-workspace.yaml").is_file():
            return current
        if current == lane_root or current.parent == current:
            return service_dir
        current = current.parent


def _iter_workspace_package_dirs(workspace_root: Path) -> list[Path]:
    package_dirs: list[Path] = [workspace_root]
    seen = {workspace_root.resolve()}
    for pattern in _parse_pnpm_workspace_patterns(workspace_root):
        for match in sorted(workspace_root.glob(pattern)):
            if not match.is_dir():
                continue
            resolved = match.resolve()
            if resolved in seen:
                continue
            package_dirs.append(match)
            seen.add(resolved)
    return package_dirs


def _sanitize_node_modules_symlink(package_dir: Path, workspace_root: Path) -> str | None:
    node_modules = package_dir / "node_modules"
    if not node_modules.is_symlink():
        return None

    target = node_modules.resolve(strict=False)
    try:
        target.relative_to(workspace_root.resolve())
        target_is_internal = True
    except ValueError:
        target_is_internal = False

    if target.exists() and target_is_internal:
        return None

    node_modules.unlink()
    return str(node_modules.relative_to(workspace_root))


def _iter_file_dependency_specs(package_dir: Path) -> list[str]:
    package_json = package_dir / "package.json"
    if not package_json.is_file():
        return []
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    specs: list[str] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        deps = payload.get(section)
        if not isinstance(deps, dict):
            continue
        for spec in deps.values():
            if isinstance(spec, str) and spec.startswith("file:"):
                specs.append(spec[5:])
    return specs


def _materialize_file_dependency_links(
    package_dir: Path,
    main_package_dir: Path,
) -> list[str]:
    created: list[str] = []
    for relative in _iter_file_dependency_specs(package_dir):
        raw_lane_target = package_dir / relative
        lane_target = raw_lane_target.resolve(strict=False)
        if raw_lane_target.is_symlink() and not raw_lane_target.exists():
            raw_lane_target.unlink()
        elif raw_lane_target.exists():
            continue

        source = (main_package_dir / relative).resolve(strict=False)
        if not source.exists():
            continue

        lane_target.parent.mkdir(parents=True, exist_ok=True)
        lane_target.symlink_to(source, target_is_directory=source.is_dir())
        created.append(str(lane_target))
    return created


def prepare_node_workspace(lane_root: Path, main_root: Path, cwd: str | None = None) -> NodeWorkspacePreparation:
    """Remove brittle dependency symlinks and restore file: deps for a lane."""
    service_dir = lane_root / cwd if cwd else lane_root
    workspace_root = _find_workspace_root(lane_root, service_dir)
    main_workspace_root = main_root / workspace_root.relative_to(lane_root)

    removed: list[str] = []
    materialized: list[str] = []
    missing_node_modules = False
    for package_dir in _iter_workspace_package_dirs(workspace_root):
        if not (package_dir / "node_modules").exists():
            missing_node_modules = True

        removed_link = _sanitize_node_modules_symlink(package_dir, workspace_root)
        if removed_link:
            removed.append(removed_link)

        main_package_dir = main_workspace_root / package_dir.relative_to(workspace_root)
        materialized.extend(_materialize_file_dependency_links(package_dir, main_package_dir))

    return NodeWorkspacePreparation(
        workspace_root=str(workspace_root),
        removed_node_modules_symlinks=removed,
        materialized_file_dependency_links=materialized,
        needs_install=bool(removed or materialized or missing_node_modules),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a Node workspace for lane-local runs.")
    parser.add_argument("--lane-root", required=True, help="Lane root path")
    parser.add_argument("--main-root", required=True, help="Main checkout root path")
    parser.add_argument("--cwd", default=None, help="Service cwd relative to the lane root")
    args = parser.parse_args()

    result = prepare_node_workspace(
        Path(args.lane_root).resolve(),
        Path(args.main_root).resolve(),
        cwd=args.cwd,
    )
    print(json.dumps(asdict(result)))


if __name__ == "__main__":
    main()
