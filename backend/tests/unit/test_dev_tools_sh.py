"""Tests for shared dev-tools.sh changed-only scope handling."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _write_project_identity(path: Path, project_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": {"id": project_id, "repo_name": project_id, "display_name": project_id},
                "runtime": {"backend_dir": "backend", "frontend_dir": "frontend"},
            }
        )
    )


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


def test_dev_tools_lane_checkout_uses_canonical_repo_venv(tmp_path: Path) -> None:
    canonical_repo = tmp_path / "canonical"
    lane_repo = tmp_path / "lane"
    canonical_app = canonical_repo / "backend" / "app"
    lane_app = lane_repo / "backend" / "app"
    canonical_venv_bin = canonical_repo / "backend" / ".venv" / "bin"

    canonical_app.mkdir(parents=True)
    lane_app.mkdir(parents=True)
    canonical_venv_bin.mkdir(parents=True)

    for repo, app_dir in ((canonical_repo, canonical_app), (lane_repo, lane_app)):
        _write_project_identity(repo / "project.identity.json", "summitflow")
        (repo / "backend" / "pyproject.toml").write_text("[project]\nname = 'tmp'\nversion = '0.0.0'\n")
        (app_dir / "only.py").write_text("def run() -> None:\n    return None\n")
        _init_git_repo(repo)
        _commit_all(repo, "initial")

    _write_executable(
        canonical_venv_bin / "python",
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
    _write_executable(
        fake_bin / "st",
        f"""#!/usr/bin/env bash
if [[ "$1" == "projects" && "$2" == "root" && "$3" == "summitflow" ]]; then
  printf '%s\\n' {str(canonical_repo)!r}
  exit 0
fi
exit 1
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
        cwd=lane_repo,
        env=env,
        check=True,
    )

    assert "TYPES:OK:0" in result.stdout
    assert "skipped_no_python" not in result.stdout


def test_dev_tools_changed_only_includes_modified_python_scripts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    app_dir = repo / "backend" / "app"
    scripts_dir = repo / "scripts"
    venv_bin = repo / "backend" / ".venv" / "bin"
    app_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)
    venv_bin.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (repo / "backend" / "pyproject.toml").write_text("[project]\nname = 'tmp'\nversion = '0.0.0'\n")
    (app_dir / "staged.py").write_text("print('old staged')\n")
    (scripts_dir / "codex-session-sync.py").write_text("print('old sync')\n")

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    (app_dir / "staged.py").write_text("print('new staged')\n")
    (scripts_dir / "codex-session-sync.py").write_text("print('new sync')\n")
    subprocess.run(["git", "add", "backend/app/staged.py", "scripts/codex-session-sync.py"], check=True, cwd=repo, capture_output=True, text=True)

    ruff_log = tmp_path / "ruff-scripts.log"
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
    ty_log = tmp_path / "ty-scripts.log"
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

    assert "SCOPE:2 files:" in result.stdout
    assert "staged.py" in result.stdout
    assert "codex-session-sync.py" in result.stdout
    ruff_logged = ruff_log.read_text()
    assert "backend/app/staged.py" in ruff_logged
    assert "scripts/codex-session-sync.py" in ruff_logged
    ty_logged = ty_log.read_text()
    assert f"cwd={repo / 'backend'}" in ty_logged
    assert "app/staged.py" in ty_logged
    assert "../scripts/codex-session-sync.py" in ty_logged


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


def test_dev_tools_pytest_rejects_trailing_global_check_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "pytest", "--check"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert "ERROR:global_flag_after_subcommand:--check" in result.stderr
    assert "Use 'dt --check' for wrapper mode" in result.stderr
    assert "Only '--changed-only' is accepted after a tool subcommand." in result.stderr


def test_dev_tools_tsc_rejects_trailing_frontend_only_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    frontend_dir = repo / "frontend"
    frontend_dir.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (frontend_dir / "package.json").write_text('{"name":"tmp"}\n')

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "tsc", "--frontend-only"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert "ERROR:global_flag_after_subcommand:--frontend-only" in result.stderr
    assert "Use 'dt --frontend-only' for wrapper mode" in result.stderr
    assert "Only '--changed-only' is accepted after a tool subcommand." in result.stderr


def test_dev_tools_tsc_help_shows_wrapper_guidance(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    frontend_dir = repo / "frontend"
    frontend_dir.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (frontend_dir / "package.json").write_text('{"name":"tmp"}\n')

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "tsc", "--help"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=True,
    )

    assert "Usage:" in result.stdout
    assert "dt --frontend-only" in result.stdout
    assert "dt tsc -- --pretty false" in result.stdout


def test_dev_tools_vitest_help_mentions_repo_root_path_normalization(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    frontend_dir = repo / "frontend"
    frontend_dir.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (frontend_dir / "package.json").write_text('{"name":"tmp","devDependencies":{"vitest":"^4.1.1"}}\n')

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "vitest", "--help"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=True,
    )

    assert "frontend-relative paths are canonical" in result.stdout
    assert "frontend/src/__tests__/compactness.test.ts" in result.stdout
    assert "Repo-root paths under frontend/ are accepted and normalized for you." in result.stdout


def test_dev_tools_quick_changed_only_without_checks_reports_skips_not_usage(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
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

    assert "QUICK_CHECK:" in result.stdout
    assert "skipped_no_python" in result.stdout
    assert "skipped_no_frontend" in result.stdout
    assert "CHECK_RESULT:OK" in result.stdout
    assert "Usage:" not in result.stdout


def test_dev_tools_biome_fails_on_formatter_only_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    frontend_dir = repo / "frontend"
    frontend_dir.mkdir(parents=True)

    (repo / ".index.yaml").write_text("project: summitflow\n")
    (frontend_dir / "package.json").write_text('{"name":"tmp"}\n')

    _init_git_repo(repo)
    _commit_all(repo, "initial")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "npx",
        """#!/usr/bin/env bash
printf 'Checked 1 file in 3ms. No fixes applied.\\n'
printf 'Formatter would have printed the following content:\\n'
exit 1
""",
    )

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tools.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(script_path), "biome"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "BIOME:FAIL:1" in result.stdout
