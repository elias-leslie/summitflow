"""Run commands in an isolated snapshot of the current working tree."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from app.utils.env_files import project_env_files, scrub_env_keys_from_files

_BASE_UNSET_KEYS = (
    "BASH_ENV",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "PYTHONHOME",
    "PYTHONPATH",
    "SF_COMMAND_GUARD_BIN",
    "SF_COMMAND_GUARD_PREV_BASH_ENV",
    "SF_COMMAND_GUARD_WORDS",
    "VIRTUAL_ENV",
)


def _git_snapshot_paths(project_root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return [
        Path(entry.decode("utf-8"))
        for entry in result.stdout.split(b"\0")
        if entry
    ]


def _copy_snapshot_entry(project_root: Path, snapshot_root: Path, relative_path: Path) -> None:
    source = project_root / relative_path
    if not source.exists() and not source.is_symlink():
        return
    destination = snapshot_root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
        return

    shutil.copy2(source, destination)


def create_snapshot(project_root: Path, snapshot_root: Path) -> None:
    """Copy the current tracked + untracked checkout content into snapshot_root."""
    for relative_path in _git_snapshot_paths(project_root):
        _copy_snapshot_entry(project_root, snapshot_root, relative_path)


def initialize_snapshot_git(snapshot_root: Path) -> None:
    """Create a minimal git repo so repo-root-aware commands still work."""
    subprocess.run(["git", "init", "-q"], cwd=snapshot_root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "st check cleanroom"],
        cwd=snapshot_root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "cleanroom@example.invalid"],
        cwd=snapshot_root,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=snapshot_root, check=True)


def build_cleanroom_env(
    project_root: Path,
    snapshot_root: Path,
    home_root: Path,
    *,
    base_env: Mapping[str, str] | None = None,
    env_overrides: Mapping[str, str] | None = None,
    unset_keys: Iterable[str] = (),
) -> dict[str, str]:
    """Build an isolated environment for a cleanroom command."""
    env = scrub_env_keys_from_files(
        base_env or os.environ,
        project_env_files(project_root),
        extra_keys=(*_BASE_UNSET_KEYS, *unset_keys),
    )

    home_root.mkdir(parents=True, exist_ok=True)
    (home_root / ".cache").mkdir(parents=True, exist_ok=True)
    (home_root / ".config").mkdir(parents=True, exist_ok=True)
    (home_root / ".local" / "share").mkdir(parents=True, exist_ok=True)

    env["HOME"] = str(home_root)
    env["PWD"] = str(snapshot_root)
    env["SF_COMMAND_GUARD_DISABLE"] = "1"
    env["XDG_CACHE_HOME"] = str(home_root / ".cache")
    env["XDG_CONFIG_HOME"] = str(home_root / ".config")
    env["XDG_DATA_HOME"] = str(home_root / ".local" / "share")

    for key, value in (env_overrides or {}).items():
        env[key] = value

    return env


def parse_env_assignments(raw_assignments: Iterable[str]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for assignment in raw_assignments:
        if "=" not in assignment:
            raise ValueError(f"invalid env assignment: {assignment}")
        key, value = assignment.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid env assignment: {assignment}")
        assignments[key] = value
    return assignments


def run_cleanroom(
    project_root: Path,
    command: list[str],
    *,
    env_overrides: Mapping[str, str] | None = None,
    unset_keys: Iterable[str] = (),
    keep_dir: bool = False,
) -> int:
    """Run a command in an isolated snapshot of the current working tree."""
    if not command:
        raise ValueError("command is required")

    temp_dir = tempfile.mkdtemp(prefix=f"{project_root.name}-cleanroom-")
    clean_up = not keep_dir
    snapshot_root = Path(temp_dir) / "repo"
    home_root = Path(temp_dir) / "home"
    snapshot_root.mkdir(parents=True, exist_ok=True)

    try:
        create_snapshot(project_root, snapshot_root)
        initialize_snapshot_git(snapshot_root)
        env = build_cleanroom_env(
            project_root,
            snapshot_root,
            home_root,
            env_overrides=env_overrides,
            unset_keys=unset_keys,
        )
        completed = subprocess.run(command, cwd=snapshot_root, env=env)
        return completed.returncode
    finally:
        if clean_up:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print(f"CLEANROOM:kept:{temp_dir}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--keep-dir", action="store_true")
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--unset", action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("command is required after '--'")

    env_overrides = parse_env_assignments(args.env)
    return run_cleanroom(
        args.project_root.resolve(),
        command,
        env_overrides=env_overrides,
        unset_keys=args.unset,
        keep_dir=args.keep_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
