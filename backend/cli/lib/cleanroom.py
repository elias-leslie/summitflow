"""Run commands in an isolated snapshot of the current working tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.utils.env_files import project_env_files, scrub_env_keys_from_files
from app.utils.heavy_work import heavy_work
from app.utils.transient_scratch import (
    SCRATCH_ROOT,
    mounted_scratch_parent,
    validate_temp_parent,
)

from .service_ops import (
    backend_optional_dependencies,
    frontend_install_plan,
    locked_backend_sync_command,
    runtime_source_dirs,
)

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
_SCRATCH_ROOT = SCRATCH_ROOT
# Job directories are ``<project>-cleanroom-<mkdtemp suffix>``; pruning matches only this shape.
CLEANROOM_PREFIX_INFIX = "-cleanroom-"
ARTIFACTS_SUBDIR = Path(".dev-tools") / "cleanroom-artifacts"


class CleanroomUsageError(ValueError):
    """Invalid cleanroom request (reported with exit code 2)."""


@dataclass(frozen=True)
class CleanroomOptions:
    """Optional dependency install and artifact collection for one cleanroom job."""

    deps: bool = False
    extras: tuple[str, ...] = ()
    collect: tuple[str, ...] = ()
    collect_to: Path | None = None
    # Content-addressed host package caches reused by installs only.
    share_caches: bool = True


def _validate_temp_parent(path: Path, *, private: bool = False) -> None:
    """Reject unsafe routing without changing an existing directory's permissions."""
    validate_temp_parent(path, private=private, label="Cleanroom")


def _cleanroom_temp_parent() -> Path | None:
    """Use the caller's namespace, or the host's mounted disposable scratch."""
    if explicit := os.environ.get("TMPDIR"):
        parent = Path(explicit)
        _validate_temp_parent(parent)
        return parent
    return mounted_scratch_parent("st-cleanrooms", root=_SCRATCH_ROOT, required=False, label="Cleanroom")


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


Runner = Callable[..., subprocess.CompletedProcess[object]]


def _snapshot_source_dirs(snapshot_root: Path) -> tuple[Path, Path]:
    """Backend/frontend locations from the snapshot's own project identity."""
    runtime: Mapping[str, object] = {}
    identity_path = snapshot_root / "project.identity.json"
    if identity_path.is_file():
        try:
            identity = json.loads(identity_path.read_text())
        except (OSError, ValueError) as exc:
            raise CleanroomUsageError(f"cannot read project.identity.json: {exc}") from exc
        raw = identity.get("runtime") if isinstance(identity, dict) else None
        runtime = raw if isinstance(raw, dict) else {}
    return runtime_source_dirs(runtime, snapshot_root)


def plan_dependency_installs(snapshot_root: Path, extras: Sequence[str]) -> list[tuple[list[str], Path]]:
    """Locked install commands for the snapshot, backend first, then frontend.

    Requested extras must be declared in the snapshot backend's
    ``[project.optional-dependencies]``; otherwise CleanroomUsageError.
    """
    backend_dir, frontend_dir = _snapshot_source_dirs(snapshot_root)
    steps: list[tuple[list[str], Path]] = []
    declared = backend_optional_dependencies(backend_dir)
    if declared is None:
        if extras:
            raise CleanroomUsageError(
                f"--extra requires pyproject.toml and uv.lock in {backend_dir.relative_to(snapshot_root).as_posix() or '.'}",
            )
    else:
        unknown = [extra for extra in dict.fromkeys(extras) if extra not in declared]
        if unknown:
            known = ", ".join(sorted(declared)) or "none"
            raise CleanroomUsageError(
                f"unknown backend extra(s): {', '.join(unknown)} (declared: {known})",
            )
        steps.append((locked_backend_sync_command(declared, extras), backend_dir))
    frontend = frontend_install_plan(frontend_dir, snapshot_root)
    if frontend is not None:
        steps.append((list(frontend.command), frontend.cwd))
    return steps


def _install_env(env: Mapping[str, str], base_env: Mapping[str, str]) -> dict[str, str]:
    """Isolated env plus the caller's content-addressed download caches.

    Lockfiles pin and hash every package, so sharing uv/npm caches only avoids
    re-downloading; the environment and node_modules stay inside the snapshot.
    """
    install = dict(env)
    install.pop("UV_PROJECT_ENVIRONMENT", None)
    real_home = Path(base_env.get("HOME") or Path.home())
    caches = {
        "UV_CACHE_DIR": Path(base_env.get("UV_CACHE_DIR") or real_home / ".cache" / "uv"),
        "npm_config_cache": Path(base_env.get("npm_config_cache") or real_home / ".npm"),
    }
    for key, path in caches.items():
        if key not in install and path.is_dir():
            install[key] = str(path)
    return install


def install_dependencies(
    snapshot_root: Path,
    extras: Sequence[str],
    *,
    runner: Runner,
    env: Mapping[str, str],
) -> int:
    """Run locked installs in order; stop at the first failure."""
    for command, cwd in plan_dependency_installs(snapshot_root, extras):
        relative = cwd.relative_to(snapshot_root).as_posix() or "."
        print(f"CLEANROOM:deps:{relative}:{' '.join(command)}", file=sys.stderr)
        completed = runner(command, cwd=cwd, env=dict(env))
        if completed.returncode != 0:
            print(f"CLEANROOM:deps-failed:{relative}:exit {completed.returncode}", file=sys.stderr)
            return completed.returncode
    return 0


def default_artifact_dir(project_root: Path, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return project_root / ARTIFACTS_SUBDIR / stamp


def _validate_collect_pattern(pattern: str) -> None:
    if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise CleanroomUsageError(f"--collect must be a glob relative to the snapshot root: {pattern!r}")


def collect_artifacts(snapshot_root: Path, patterns: Sequence[str], destination: Path) -> tuple[int, list[str]]:
    """Copy matches (relative paths preserved) into destination; return (count, empty patterns)."""
    copied = 0
    empty: list[str] = []
    for pattern in patterns:
        matches = sorted(snapshot_root.glob(pattern))
        matches = [m for m in matches if ".git" not in m.relative_to(snapshot_root).parts[:1]]
        if not matches:
            empty.append(pattern)
            continue
        for match in matches:
            target = destination / match.relative_to(snapshot_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if match.is_dir() and not match.is_symlink():
                shutil.copytree(match, target, symlinks=True, dirs_exist_ok=True)
            elif match.is_symlink():
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(os.readlink(match))
            else:
                shutil.copy2(match, target)
            copied += 1
    return copied, empty


def prune_hint(project_root: Path) -> str:
    return f"st cleanup cleanrooms --project {project_root.name} --older-than 24h"


def run_cleanroom(
    project_root: Path,
    command: list[str],
    *,
    env_overrides: Mapping[str, str] | None = None,
    unset_keys: Iterable[str] = (),
    keep_dir: bool = False,
    options: CleanroomOptions | None = None,
) -> int:
    """Run a command in an isolated snapshot of the current working tree."""
    if not command:
        raise ValueError("command is required")
    options = options or CleanroomOptions()
    if options.extras and not options.deps:
        raise CleanroomUsageError("--extra requires --deps")
    for pattern in options.collect:
        _validate_collect_pattern(pattern)
    collect_to = options.collect_to or (default_artifact_dir(project_root) if options.collect else None)

    # This isolated execution route is used for installs, lock resolution and
    # gates. Admit before copying/staging the checkout as well as spawning the
    # command; ordinary ST inspection does not use this route.
    with heavy_work("isolated validation") as work:
        temp_dir = tempfile.mkdtemp(
            prefix=f"{project_root.name}{CLEANROOM_PREFIX_INFIX}", dir=_cleanroom_temp_parent(),
        )
        clean_up = not keep_dir
        snapshot_root = Path(temp_dir) / "repo"
        home_root = Path(temp_dir) / "home"
        temp_root = Path(temp_dir) / "tmp"

        try:
            if collect_to is not None and collect_to.resolve().is_relative_to(Path(temp_dir).resolve()):
                raise CleanroomUsageError("--to must be outside the disposable cleanroom directory")
            snapshot_root.mkdir(parents=True, exist_ok=True)
            temp_root.mkdir(mode=0o700)
            create_snapshot(project_root, snapshot_root)
            initialize_snapshot_git(snapshot_root)
            base_env = os.environ.copy()
            env = build_cleanroom_env(
                project_root,
                snapshot_root,
                home_root,
                base_env=base_env,
                env_overrides=env_overrides,
                unset_keys=unset_keys,
            )
            # The command's temporary files belong to this disposable job too.
            # An explicit --env TMPDIR still selects the caller's desired path.
            if "TMPDIR" not in (env_overrides or {}):
                env["TMPDIR"] = str(temp_root)
            if options.deps:
                install_env = _install_env(env, base_env) if options.share_caches else env
                code = install_dependencies(snapshot_root, options.extras, runner=work.run, env=install_env)
                if code != 0:
                    return code
            completed = work.run(command, cwd=snapshot_root, env=env)
            returncode = completed.returncode
            if collect_to is not None:
                copied, empty = collect_artifacts(snapshot_root, options.collect, collect_to)
                print(f"CLEANROOM:collected:{copied}:{collect_to}", file=sys.stderr)
                for pattern in empty:
                    print(f"CLEANROOM:collect-empty:{pattern}", file=sys.stderr)
                if empty and returncode == 0:
                    returncode = 1
            return returncode
        finally:
            if clean_up:
                shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                print(f"CLEANROOM:kept:{temp_dir}", file=sys.stderr)
                print(f"CLEANROOM:prune:{prune_hint(project_root)}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="st check cleanroom",
        description=__doc__,
        epilog="Kept job dirs (--keep-dir) are pruned with: st cleanup cleanrooms [--older-than 24h] [--project X]",
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--keep-dir", action="store_true")
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--unset", action="append", default=[])
    parser.add_argument(
        "--deps", action="store_true",
        help="Install locked deps in the snapshot first (backend: uv sync --locked + dev; frontend: npm ci / pnpm --frozen-lockfile).",
    )
    parser.add_argument(
        "--extra", action="append", default=[], metavar="NAME",
        help="Additional backend optional-dependency group for --deps (repeatable).",
    )
    parser.add_argument(
        "--collect", action="append", default=[], metavar="GLOB",
        help="Copy matching snapshot paths out before cleanup (repeatable; relative to snapshot root).",
    )
    parser.add_argument(
        "--to", type=Path, default=None, metavar="DIR",
        help=f"Artifact destination (default: <project>/{ARTIFACTS_SUBDIR.as_posix()}/<UTC timestamp>).",
    )
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
    if args.to is not None and not args.collect:
        parser.error("--to requires --collect")

    env_overrides = parse_env_assignments(args.env)
    options = CleanroomOptions(
        deps=args.deps,
        extras=tuple(args.extra),
        collect=tuple(args.collect),
        collect_to=args.to.resolve() if args.to is not None else None,
    )
    try:
        return run_cleanroom(
            args.project_root.resolve(),
            command,
            env_overrides=env_overrides,
            unset_keys=args.unset,
            keep_dir=args.keep_dir,
            options=options,
        )
    except CleanroomUsageError as exc:
        print(f"st check cleanroom: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
