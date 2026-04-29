"""Small detail-file helpers for token-efficient CLI output."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_RESULT_LINE_RE = re.compile(
    r"(?i)(\b\d+\s+(passed|failed|skipped|deselected|error|errors|warning|warnings)\b|"
    r"\b(all checks passed|no fixes applied)\b)"
)


def current_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return Path.cwd()


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def detail_path(root: Path, name: str) -> Path:
    directory = root / ".dev-tools"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{name}-details.txt"


def display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def summary_hint(output: str, *, limit: int = 180) -> str:
    lines = [line.strip() for line in strip_ansi(output).splitlines() if line.strip()]
    for line in reversed(lines):
        if _RESULT_LINE_RE.search(line) and "RuntimeWarning:" not in line:
            return line[:limit]
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return "-"


def write_details(root: Path, name: str, output: str) -> Path:
    path = detail_path(root, name)
    path.write_text(strip_ansi(output), encoding="utf-8")
    return path


def result_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def emit_result_or_details(
    root: Path,
    name: str,
    label: str,
    result: subprocess.CompletedProcess[str],
    *,
    max_chars: int = 1600,
    max_lines: int = 40,
) -> None:
    output = result_output(result)
    if not output:
        return
    line_count = len(output.splitlines())
    if len(strip_ansi(output)) <= max_chars and line_count <= max_lines:
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        return
    details = write_details(root, name, output)
    status = "OK" if result.returncode == 0 else "FAIL"
    print(
        f"{label}:{status}:{result.returncode}|lines={line_count}|"
        f"details:{display_path(root, details)}|hint:{summary_hint(output)}"
    )
