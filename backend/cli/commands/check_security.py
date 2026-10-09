"""Candidate-scoped local security checks with explicit coverage limits."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.utils.heavy_work import heavy_work
from app.utils.transient_scratch import managed_temp_parent

from ..details import display_path, summary_hint
from .check_artifacts import write_check_details

_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "vendor",
}
_LOCK_NAMES = {
    "bun.lock",
    "bun.lockb",
    "Cargo.lock",
    "go.mod",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "requirements.txt",
    "uv.lock",
    "yarn.lock",
}
_MANIFEST_NAMES = {"go.sum", "package.json", "pyproject.toml"}


def _git_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("cannot enumerate candidate source with git")
    return [item.decode(errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def _safe_candidate_paths(root: Path, paths: list[str]) -> list[str]:
    selected: set[str] = set()
    resolved_root = root.resolve()
    for value in paths:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts or _EXCLUDED_PARTS.intersection(relative.parts):
            continue
        candidate = root / relative
        try:
            candidate.parent.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        if candidate.is_file() or candidate.is_symlink():
            selected.add(relative.as_posix())
    return sorted(selected)


def _candidate_paths(root: Path, changed_files: list[str], changed_only: bool) -> list[str]:
    source = changed_files if changed_only else _git_paths(root)
    return _safe_candidate_paths(root, source)


def _materialize(root: Path, paths: list[str], destination: Path) -> None:
    for relative in paths:
        source = root / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.write_text(os.readlink(source), encoding="utf-8")
        else:
            shutil.copyfile(source, target)


def _emit_result(root: Path, name: str, result: subprocess.CompletedProcess[str]) -> int:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    details = write_check_details(root, f"security-{name}", output)
    label = name.upper()
    status = "OK" if result.returncode == 0 else "FAIL"
    print(
        f"{label}:{status}:{result.returncode}|details:{display_path(root, details)}|"
        f"hint:{summary_hint(output)}"
    )
    return result.returncode


def _run(command: list[str], *, root: Path, name: str, environment: dict[str, str] | None = None,
         work_class: str = "heavy") -> int:
    try:
        with heavy_work(f"local scan {name}", work_class=work_class) as work:
            result = work.run(
                command,
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
    except OSError as exc:
        if name != "gitleaks" and isinstance(exc, FileNotFoundError):
            print(f"{name.upper()}:SKIP:{name}:tool_not_installed;coverage_not_claimed")
            return 0
        result = subprocess.CompletedProcess(command, 127, "", f"{type(exc).__name__}: {exc}")
    return _emit_result(root, name, result)


def _semgrep_config(root: Path) -> Path | None:
    configured = os.environ.get("SEMGREP_RULES", "").strip()
    candidates = ([Path(configured).expanduser()] if configured else []) + [
        root / ".semgrep.yml",
        root / ".semgrep.yaml",
        root / ".semgrep",
    ]
    for candidate in candidates:
        if candidate.exists() and not str(candidate).startswith(("http://", "https://")):
            return candidate.resolve()
    return None


def _lockfiles(root: Path, paths: list[str], changed_only: bool) -> list[Path]:
    selected = {root / path for path in paths if Path(path).name in _LOCK_NAMES}
    if changed_only and any(Path(path).name in _MANIFEST_NAMES for path in paths):
        all_paths = _safe_candidate_paths(root, _git_paths(root))
        manifest_dirs = {
            Path(path).parent for path in paths if Path(path).name in _MANIFEST_NAMES
        }
        selected.update(
            root / path
            for path in all_paths
            if Path(path).name in _LOCK_NAMES and Path(path).parent in manifest_dirs
        )
    return sorted(path for path in selected if path.is_file())


def run_local_security_check(
    name: str,
    root: Path,
    changed_files: list[str],
    changed_only: bool,
    explicit_args: list[str],
) -> int:
    """Run a local scanner against current candidate files, never ignored caches."""
    # A changed-file secret scan is sub-second and low-memory; full trees,
    # semgrep and osv keep the heavy lane.
    work_class = "light" if name == "gitleaks" and changed_only else "heavy"
    with heavy_work("local security", work_class=work_class):
        return _run_local_security_check(name, root, changed_files, changed_only, explicit_args, work_class)


def _run_local_security_check(
    name: str,
    root: Path,
    changed_files: list[str],
    changed_only: bool,
    explicit_args: list[str],
    work_class: str,
) -> int:
    if explicit_args:
        print(f"{name.upper()}:FAIL:2|hint:local security adapters do not accept passthrough arguments")
        return 2
    names = ("gitleaks", "semgrep", "osv") if name == "security" else (name,)
    if name == "security":
        print("SECURITY:coverage=local_candidate|codeql_equivalence=not_claimed")
    try:
        paths = _candidate_paths(root, changed_files, changed_only)
    except RuntimeError as exc:
        print(f"SECURITY:FAIL:2|hint:{exc}")
        return 2
    failures: list[int] = []
    for scanner in names:
        if scanner == "osv":
            lockfiles = _lockfiles(root, paths, changed_only)
            if not lockfiles:
                print("OSV:SKIP:osv:no_candidate_lockfiles")
                continue
            command = [
                "osv-scanner",
                "scan",
                "source",
                "--format",
                "json",
                "--verbosity",
                "error",
            ]
            if os.environ.get("ST_OSV_OFFLINE", "").lower() in {"1", "true", "yes", "on"}:
                command.extend(["--offline", "--offline-vulnerabilities"])
            for lockfile in lockfiles:
                command.extend(["--lockfile", str(lockfile)])
            result = _run(command, root=root, name=scanner)
            if result:
                failures.append(result)
            continue
        if not paths:
            print(f"{scanner.upper()}:SKIP:{scanner}:no_candidate_files")
            continue
        required_bytes = sum((root / path).lstat().st_size for path in paths)
        parent = managed_temp_parent("st-security", label="Security scan", required_bytes=required_bytes)
        with tempfile.TemporaryDirectory(prefix="st-security-", dir=parent) as temporary:
            candidate = Path(temporary) / "candidate"
            candidate.mkdir()
            _materialize(root, paths, candidate)
            cache = Path(temporary) / "cache"
            cache.mkdir(mode=0o700)
            environment = {**os.environ, "TMPDIR": temporary, "TMP": temporary, "TEMP": temporary,
                           "XDG_CACHE_HOME": str(cache)}
            if scanner == "gitleaks":
                command = [
                    "gitleaks",
                    "dir",
                    "--no-banner",
                    "--redact",
                    "--report-format",
                    "json",
                    "--report-path",
                    "-",
                    str(candidate),
                ]
            else:
                config = _semgrep_config(root)
                if config is None:
                    print(
                        "SEMGREP:SKIP:semgrep:no_local_rules;"
                        "registry_download_disabled;codeql_equivalence_not_claimed"
                    )
                    continue
                command = [
                    "semgrep",
                    "scan",
                    "--config",
                    str(config),
                    "--metrics",
                    "off",
                    "--disable-version-check",
                    "--error",
                    "--json",
                    str(candidate),
                ]
                environment.update(SEMGREP_SETTINGS_FILE=str(Path(temporary) / "settings.yml"),
                                   SEMGREP_LOG_FILE=str(Path(temporary) / "semgrep.log"))
            result = _run(command, root=root, name=scanner, environment=environment, work_class=work_class)
            if result:
                failures.append(result)
    if not failures:
        return 0
    return 1 if name == "security" else failures[0]
