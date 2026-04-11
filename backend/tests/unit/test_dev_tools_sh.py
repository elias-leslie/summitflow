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
    ty_log = tmp_path / "ty.log"
    _write_executable(
        fake_bin / "ty",
        f"""#!/usr/bin/env bash
printf 'cwd=%s args=%s\\n' "$PWD" "$*" >> {str(ty_log)!r}
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
    ty_logged = ty_log.read_text()
    assert "staged.py" in ty_logged
    assert "unstaged.py" not in ty_logged
    assert "untracked.py" not in ty_logged
    assert "/backend/app" not in ty_logged


def test_dev_tools_types_explicit_path_stays_scoped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    app_dir = repo / "backend" / "app"
    venv_bin = repo / "backend" / ".venv" / "bin"
    app_dir.mkdir(parents=True)
    venv_bin.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (repo / "backend" / "pyproject.toml").write_text("[project]\nname = 'tmp'\nversion = '0.0.0'\n")
    (app_dir / "only.py").write_text("def run() -> None:\n    return None\n")

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    _write_executable(
        venv_bin / "python",
        """#!/usr/bin/env bash
exit 0
""",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ty_log = tmp_path / "ty-explicit.log"
    _write_executable(
        fake_bin / "ty",
        f"""#!/usr/bin/env bash
printf 'cwd=%s args=%s\\n' "$PWD" "$*" >> {str(ty_log)!r}
exit 0
""",
    )

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "types", "backend/app/only.py"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=True,
    )

    assert "TYPES:OK:0" in result.stdout
    logged = ty_log.read_text()
    assert f"cwd={repo / 'backend'}" in logged
    assert "app/only.py" in logged
    assert "backend/app/only.py" not in logged
    assert "/backend/app" not in logged


def test_dev_tools_vitest_normalizes_repo_root_frontend_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    frontend_dir = repo / "frontend"
    tests_dir = frontend_dir / "src" / "__tests__"
    tests_dir.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (frontend_dir / "package.json").write_text('{"name":"tmp","devDependencies":{"vitest":"^4.1.1"}}\n')
    (tests_dir / "compactness.test.ts").write_text("export {};\n")

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    vitest_log = tmp_path / "vitest.log"
    _write_executable(
        fake_bin / "vitest",
        f"""#!/usr/bin/env bash
printf 'cwd=%s args=%s\\n' "$PWD" "$*" >> {str(vitest_log)!r}
printf 'Tests 1 passed\\n'
exit 0
""",
    )

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "vitest", "--", "frontend/src/__tests__/compactness.test.ts"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=True,
    )

    assert "VITEST:OK:0" in result.stdout
    logged = vitest_log.read_text()
    assert f"cwd={frontend_dir}" in logged
    assert "src/__tests__/compactness.test.ts" in logged
    assert "frontend/src/__tests__/compactness.test.ts" not in logged
