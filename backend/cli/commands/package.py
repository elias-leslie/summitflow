"""Run a project's declared packaging command and record its artifact digests.

project.identity.json declares::

    "packaging": {"command": ["npm", "run", "dist"], "artifacts": ["dist/*.AppImage"],
                  "output_dir": "dist", "work_class": "heavy", "timeout_seconds": 3600}

The command runs from the project root under shared admission. Every artifact
glob must match a file written during this run inside output_dir; the receipt
binds their sizes and SHA-256 digests to the source commit.
"""

from __future__ import annotations

import glob
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

import typer

from app.project_identity import get_project_identity, get_project_identity_root
from app.utils.heavy_work import HeavyWorkError, heavy_work

from ..output import output_error

app = typer.Typer(help="Run a project's declared packaging command and record artifact digests.")


class PackagingError(ValueError):
    """The packaging declaration or its result is unusable."""


def _relative(value: Any, field: str) -> str:
    path = PurePosixPath(value) if isinstance(value, str) and value else None
    if path is None or path.is_absolute() or ".." in path.parts:
        raise PackagingError(f"packaging.{field} must be a relative path inside the project")
    return str(path)


def packaging_spec(identity: dict[str, Any] | None) -> dict[str, Any]:
    block = (identity or {}).get("packaging")
    if not isinstance(block, dict):
        raise PackagingError("project.identity.json declares no packaging block")
    command, artifacts = block.get("command"), block.get("artifacts")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise PackagingError("packaging.command must be a non-empty argv list")
    if not isinstance(artifacts, list) or not artifacts:
        raise PackagingError("packaging.artifacts must list at least one glob")
    work_class = block.get("work_class", "heavy")
    if work_class not in {"heavy", "light"}:
        raise PackagingError("packaging.work_class must be heavy or light")
    timeout = block.get("timeout_seconds", 3600)
    if type(timeout) is not int or not 60 <= timeout <= 14400:
        raise PackagingError("packaging.timeout_seconds must be an integer from 60 to 14400")
    output_dir = _relative(block.get("output_dir", "dist"), "output_dir")
    globs = [_relative(pattern, "artifacts[]") for pattern in artifacts]
    if any(not PurePosixPath(pattern).is_relative_to(output_dir) for pattern in globs):
        raise PackagingError("packaging.artifacts must stay inside packaging.output_dir")
    return {"command": command, "artifacts": globs, "output_dir": output_dir,
            "work_class": work_class, "timeout_seconds": timeout}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def collect_artifacts(root: Path, spec: dict[str, Any], started: float) -> list[dict[str, Any]]:
    output = (root / spec["output_dir"]).resolve()
    found: dict[str, Path] = {}
    for pattern in spec["artifacts"]:
        fresh = [Path(match) for match in sorted(glob.glob(str(root / pattern), recursive=True))
                 if Path(match).is_file() and Path(match).resolve().is_relative_to(output)
                 and Path(match).stat().st_mtime >= started]
        if not fresh:
            raise PackagingError(f"no artifact written this run matches {pattern}")
        found.update({str(path.relative_to(root)): path for path in fresh})
    return [{"path": name, "size": path.stat().st_size, "sha256": _digest(path)} for name, path in sorted(found.items())]


def run_package(project: str) -> tuple[int, str]:
    root_path = get_project_identity_root(project)
    if root_path is None:
        raise PackagingError(f"unknown project: {project}")
    root = Path(root_path)
    spec = packaging_spec(get_project_identity(project))
    sha = _git(root, "rev-parse", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=no"))
    details = root / ".dev-tools" / "package-details.txt"
    details.parent.mkdir(exist_ok=True)
    started = time.time()
    with heavy_work(f"package {project}", work_class=spec["work_class"], project=project) as work:
        result = work.run(spec["command"], cwd=root, capture_output=True, text=True,
                          errors="replace", check=False, timeout=spec["timeout_seconds"])
    details.write_text((result.stdout or "") + (result.stderr or ""))
    if result.returncode:
        return result.returncode, f"PACKAGE:{project}|state=failed|returncode={result.returncode}|details:{details}"
    artifacts = collect_artifacts(root, spec, started)
    receipt_dir = root / _git(root, "rev-parse", "--git-dir") / "st" / "package"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = receipt_dir / f"{sha}.json"
    receipt.write_text(json.dumps({
        "kind": "package.v1", "project": project, "source_commit": sha, "tracked_changes": dirty,
        "command": spec["command"], "completed_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((time.time() - started) * 1000, 3), "artifacts": artifacts,
    }, indent=2) + "\n")
    return 0, (f"PACKAGE:{project}|state=ok|source={sha[:12]}|tracked_changes={str(dirty).lower()}"
               f"|artifacts={len(artifacts)}|evidence={receipt}")


@app.command()
def package(project: Annotated[str, typer.Argument(help="Project whose identity declares packaging")]) -> None:
    """Run the project's declared packaging command and record artifact digests."""
    try:
        code, line = run_package(project)
    except (PackagingError, HeavyWorkError, subprocess.SubprocessError, OSError) as exc:
        output_error(f"package {project}: {exc}")
        raise typer.Exit(1) from None
    typer.echo(line)
    raise typer.Exit(code)
