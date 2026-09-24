"""An owner-only wheel refresh must not run unrelated workspace prepack hooks."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "docker/scripts/pack-workspace-packages.sh"


def test_selected_python_owner_builds_only_its_wheel(tmp_path: Path) -> None:
    owner = tmp_path / "code-intelligence"
    owner.mkdir()
    (owner / "pyproject.toml").write_text('[project]\nname = "code-intelligence"\n')
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands.log"
    for name, body in {
        "st": 'printf "%s\\n" "$TEST_OWNER_ROOT"',
        "uv": 'printf "%s|%s|%s\\n" "$PWD" "$SOURCE_DATE_EPOCH" "$*" >> "$TEST_BUILD_LOG"',
        "pnpm": 'echo "unexpected pnpm invocation" >&2; exit 99',
    }.items():
        executable = commands / name
        executable.write_text("#!/bin/sh\n" + body + "\n")
        executable.chmod(0o755)
    env = {**os.environ, "PATH": f"{commands}:{os.environ['PATH']}", "TEST_OWNER_ROOT": str(owner), "TEST_BUILD_LOG": str(log)}
    result = subprocess.run(["bash", str(SCRIPT), str(tmp_path / "out"), "--python-owner", "code-intelligence"], capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [f"{owner}|1577836800|build --wheel --out-dir {tmp_path / 'out'}"]


def test_unknown_python_owner_is_rejected(tmp_path: Path) -> None:
    result = subprocess.run(["bash", str(SCRIPT), str(tmp_path / "out"), "--python-owner", "unregistered-owner"], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "Unknown Python tool owner" in result.stderr
