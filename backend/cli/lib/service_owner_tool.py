"""Prepare an accepted, relocatable ST tool; installation remains owner work.

Like Nightshift's deploy-gate refresh_tool, this materializes accepted Git source
and runs uv sync --frozen. Only the agent builds; the resulting tar needs neither
uv nor the build machine's Python/dependency caches at runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from app.services.tether import _agent_uid
from app.utils.heavy_work import HeavyWork, heavy_work

from . import acceptance, service_ops
from . import service_release as releases

PYTHON_RELPATH = "python/bin/python3.13"
LAUNCHER_RELPATH = "launch.py"
LAUNCHER = '''"""Installed capsule adapter: preserve the caller's HOME and identity."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:] = [str(root / path) for path in (
    "source/backend", "source/packages/st-sdk", "site-packages",
    "python/lib/python3.13", "python/lib/python3.13/lib-dynload",
)]

if __name__ == "__main__":
    from cli.main import app
    app()
'''


def tool_argv(root: Path) -> list[str]:
    """The same argv is used by agent preparation and owner activation."""
    return [str(root / PYTHON_RELPATH), "-I", "-S", str(root / LAUNCHER_RELPATH)]


def _python_prefix() -> Path:
    if sys.version_info[:2] != (3, 13):
        raise ValueError("Owner tool preparation requires Python 3.13")
    prefix = Path(sys.base_prefix).resolve(strict=True)
    executable = prefix / "bin/python3.13"
    if not stat.S_ISREG(executable.lstat().st_mode):
        raise ValueError("Capsule Python must be a regular ELF executable")
    with executable.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ValueError("Capsule Python must be a regular ELF executable")
    if not (prefix / "lib/python3.13/encodings/__init__.py").is_file():
        raise ValueError("Complete Python 3.13 prefix is unavailable")
    return prefix


def _check_links(root: Path) -> None:
    """Only relative links resolving inside the copied payload can relocate."""
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            if Path(os.readlink(path)).is_absolute() or not path.resolve(strict=True).is_relative_to(root):
                raise ValueError(f"Capsule has an external symlink: {path.relative_to(root)}")
        elif not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"Capsule has an unsupported file: {path.relative_to(root)}")


def _copy_payload(source: Path, prefix: Path, destination: Path) -> None:
    site = source / "backend/.venv/lib/python3.13/site-packages"
    if not site.is_dir():
        raise ValueError("Frozen dependency environment is unavailable")
    for direct_url in site.glob("*.dist-info/direct_url.json"):
        if json.loads(direct_url.read_text()).get("dir_info", {}).get("editable"):
            raise ValueError("Frozen dependency environment contains an editable install")
    if any("editable" in path.name.lower() for path in site.glob("*.pth")):
        raise ValueError("Frozen dependency environment contains an editable install")
    # Copy all files: no hardlinks to uv's shared package cache or build venv.
    shutil.copytree(prefix, destination / "python", symlinks=True)
    shutil.copytree(site, destination / "site-packages", symlinks=True)
    shutil.copytree(source, destination / "source", symlinks=True,
                    ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__"))
    (destination / LAUNCHER_RELPATH).write_text(LAUNCHER)
    _check_links(destination)


def _smoke(root: Path, home: Path, work: HeavyWork) -> None:
    # Settings requires a URL even for help. This deliberately unusable local
    # test address permits import without reading the agent's real credentials.
    env = {"HOME": str(home), "PATH": os.defpath, "LANG": "C.UTF-8", "NO_COLOR": "1",
           "DATABASE_URL": "postgresql://127.0.0.1:1/summitflow_test"}
    home.mkdir()
    commands = [[*tool_argv(root)[:3], "-V"], [*tool_argv(root), "--help"],
                [*tool_argv(root), "service", "--help"]]
    for command in commands:
        result = work.run(command, cwd=home, env=env, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode:
            raise ValueError(f"Relocated owner tool smoke failed: {result.stderr[-2000:]}")


def prepare(*, sha: str, destination: Path, receipt: Path) -> dict[str, Any]:
    """Write capsule.tar and manifest.json from one canonical FULL accepted SHA.

    destination must not exist. Source, environment and unarchived copies are
    disposable; no service pointers, owner storage or installed tools change.
    """
    if os.getuid() == 0 or os.getuid() != _agent_uid() or os.geteuid() != os.getuid():
        raise ValueError("Owner tool preparation requires the configured agent account")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Owner tool source must be a full lowercase commit SHA")
    prefix = _python_prefix()
    destination = destination.absolute()
    if destination.exists():
        raise ValueError("Owner tool output already exists")
    project = service_ops.load_project("summitflow")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (heavy_work("accepted owner tool capsule", project="summitflow") as work,
          tempfile.TemporaryDirectory(prefix=".owner-tool-", dir=destination.parent) as directory):
        temporary = Path(directory)
        # Validate the requested exact SHA before materialization; prepare_release
        # revalidates the canonical descriptor under its existing repository lock.
        descriptor = acceptance.validate_acceptance_receipt(project.git_root, receipt, sha=sha)
        accepted = releases.AcceptedSource.from_descriptor(descriptor, require_full=True)
        if not re.fullmatch(r"[0-9a-f]{64}", accepted.acceptance_id):
            raise ValueError("Owner tool acceptance identity is invalid")
        release = releases.prepare_release("summitflow", project.git_root, descriptor,
                                           state_root=temporary / "state")
        backend = release.source_root / "backend"
        env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(backend / ".venv"),
                   UV_PYTHON_DOWNLOADS="never", UV_LINK_MODE="copy")
        result = work.run(["uv", "sync", "--frozen", "--no-editable", "--link-mode", "copy",
                           "--python", str(prefix / "bin/python3.13")], cwd=backend, env=env,
                          capture_output=True, text=True, timeout=1800, check=False)
        if result.returncode:
            raise ValueError(f"Frozen owner tool dependency preparation failed: {result.stderr[-2000:]}")
        capsule = temporary / "capsule"
        capsule.mkdir()
        _copy_payload(release.source_root, prefix, capsule)
        # Move before execution so absolute build paths cannot supply imports.
        relocated = temporary / "relocated"
        capsule.rename(relocated)
        _smoke(relocated, temporary / "home", work)
        output = temporary / "output"
        output.mkdir()
        archive_path = output / "capsule.tar"
        with tarfile.open(archive_path, "w") as archive:
            for path in sorted(relocated.iterdir()):
                archive.add(path, arcname=path.name)
        with archive_path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = {"schema": 1, "source_sha": accepted.source_commit,
                    "source_tree": accepted.source_tree, "acceptance_id": accepted.acceptance_id,
                    "archive_sha256": digest, "archive_size": archive_path.stat().st_size,
                    "python_relpath": PYTHON_RELPATH, "launcher_relpath": LAUNCHER_RELPATH}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        output.rename(destination)
        return manifest
