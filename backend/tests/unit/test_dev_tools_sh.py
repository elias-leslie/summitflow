"""Tests for shared dev-tools.sh changed-only scope handling."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], check=True, cwd=path, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], check=True, cwd=path, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        check=True,
        cwd=path,
        capture_output=True,
        text=True,
    )


def _commit_all(path: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], check=True, cwd=path, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", message], check=True, cwd=path, capture_output=True, text=True)


def test_dev_tools_changed_only_scope_staged_ignores_unstaged_and_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    app_dir = repo / "backend" / "app"
    venv_bin = repo / "backend" / ".venv" / "bin"
    app_dir.mkdir(parents=True)
    venv_bin.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (repo / "backend" / "pyproject.toml").write_text("[project]\nname = 'tmp'\nversion = '0.0.0'\n")
    (app_dir / "staged.py").write_text("print('old staged')\n")
    (app_dir / "unstaged.py").write_text("print('old unstaged')\n")

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    (app_dir / "staged.py").write_text("print('new staged')\n")
    (app_dir / "unstaged.py").write_text("print('new unstaged')\n")
    (app_dir / "untracked.py").write_text("print('new untracked')\n")
    subprocess.run(["git", "add", "backend/app/staged.py"], check=True, cwd=repo, capture_output=True, text=True)

    ruff_log = tmp_path / "ruff.log"
    _write_executable(
        venv_bin / "ruff",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {str(ruff_log)!r}
exit 0
""",
    )
    _write_executable(
        venv_bin / "python",
        """#!/usr/bin/env bash
exit 0
""",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ty",
        """#!/usr/bin/env bash
exit 0
""",
    )

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["DT_CHANGED_ONLY_SCOPE"] = "staged"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "--quick", "--changed-only"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=True,
    )

    assert "CHECK_RESULT:OK" in result.stdout
    assert "SCOPE:1 files:staged.py" in result.stdout
    logged = ruff_log.read_text()
    assert "staged.py" in logged
    assert "unstaged.py" not in logged
    assert "untracked.py" not in logged
