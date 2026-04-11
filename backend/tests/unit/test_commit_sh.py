"""Tests for shared commit.sh workflow reporting."""

from __future__ import annotations

import os
import shlex
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


def test_commit_sh_capture_workflow_summary_reports_recent_runs(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
if [[ "$1" == "remote" && "$2" == "get-url" && "$3" == "origin" ]]; then
  echo "git@github.com:elias-leslie/a-term.git"
  exit 0
fi
echo "unexpected git invocation: $*" >&2
exit 1
""",
    )
    _write_executable(
        fake_bin / "gh",
        """#!/usr/bin/env bash
if [[ "$1" == "run" && "$2" == "list" ]]; then
  cat <<'JSON'
[{"conclusion":"success","databaseId":24221400922,"displayTitle":"chore(release): bump version to v0.2.1","event":"push","headBranch":"v0.2.1","headSha":"1653d12feeed74101002b3b258f5e8b47476d243","number":2,"status":"completed","url":"https://github.com/elias-leslie/a-term/actions/runs/24221400922","workflowName":"release"},{"conclusion":"","databaseId":24221396362,"displayTitle":"chore(release): bump version to v0.2.1","event":"push","headBranch":"main","headSha":"1653d12feeed74101002b3b258f5e8b47476d243","number":107,"status":"in_progress","url":"https://github.com/elias-leslie/a-term/actions/runs/24221396362","workflowName":"CI"}]
JSON
  exit 0
fi
echo "unexpected gh invocation: $*" >&2
exit 1
""",
    )

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "commit.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["COMMIT_SH_SOURCE_ONLY"] = "1"

    command = f"""
source "{script_path}"
capture_workflow_summary "1653d12feeed74101002b3b258f5e8b47476d243"
printf 'SUMMARY=%s\\n' "$LAST_WORKFLOW_SUMMARY"
printf 'HINT=%s\\n' "$LAST_WORKFLOW_HINT"
printf 'JSON=%s\\n' "$LAST_WORKFLOW_JSON"
"""
    result = subprocess.run(
        ["bash", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert "SUMMARY=release=success@v0.2.1#2 | CI=in_progress@main#107" in result.stdout
    assert "HINT=gh run watch 24221396362 --repo elias-leslie/a-term --exit-status" in result.stdout
    assert '"workflow":"release"' in result.stdout
    assert '"workflow":"CI"' in result.stdout


def test_commit_sh_capture_workflow_summary_marks_fallback_runs_as_recent(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
if [[ "$1" == "remote" && "$2" == "get-url" && "$3" == "origin" ]]; then
  echo "git@github.com:elias-leslie/a-term.git"
  exit 0
fi
echo "unexpected git invocation: $*" >&2
exit 1
""",
    )
    _write_executable(
        fake_bin / "gh",
        """#!/usr/bin/env bash
if [[ "$1" == "run" && "$2" == "list" ]]; then
  cat <<'JSON'
[{"conclusion":"failure","databaseId":24221400920,"displayTitle":"older run","event":"push","headBranch":"main","headSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","number":4,"status":"completed","url":"https://github.com/elias-leslie/a-term/actions/runs/24221400920","workflowName":"CI"}]
JSON
  exit 0
fi
echo "unexpected gh invocation: $*" >&2
exit 1
""",
    )

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "commit.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["COMMIT_SH_SOURCE_ONLY"] = "1"
    env["WORKFLOW_DISCOVERY_ATTEMPTS"] = "1"

    command = f"""
source "{script_path}"
capture_workflow_summary "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
printf 'SUMMARY=%s\\n' "$LAST_WORKFLOW_SUMMARY"
printf 'HINT=%s\\n' "$LAST_WORKFLOW_HINT"
"""
    result = subprocess.run(
        ["bash", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert "SUMMARY=recent: CI=failure@main#4" in result.stdout
    assert "HINT=" in result.stdout


def test_commit_sh_uses_github_identity_for_commits(tmp_path: Path) -> None:
    log_path = tmp_path / "commit-env.log"

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "commit.sh"
    env = os.environ.copy()
    env["COMMIT_SH_SOURCE_ONLY"] = "1"

    command = f"""
gh() {{
  if [[ "$1" == "api" && "$2" == "user" ]]; then
    printf 'Elias Leslie\\t56698332\\telias-leslie\\n'
    return 0
  fi
  echo "unexpected gh invocation: $*" >&2
  return 1
}}
git() {{
  if [[ "$1" == "commit" ]]; then
    printf '%s\\n%s\\n%s\\n%s\\n' "$GIT_AUTHOR_NAME" "$GIT_AUTHOR_EMAIL" "$GIT_COMMITTER_NAME" "$GIT_COMMITTER_EMAIL" > "{log_path}"
    return 0
  fi
  echo "unexpected git invocation: $*" >&2
  return 1
}}
source "{script_path}"
run_git_commit -m "Test commit"
"""
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    logged = log_path.read_text().splitlines()
    assert logged == [
        "Elias Leslie",
        "56698332+elias-leslie@users.noreply.github.com",
        "Elias Leslie",
        "56698332+elias-leslie@users.noreply.github.com",
    ]


def test_commit_sh_respects_pre_staged_subset_and_scopes_dt_changed_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "backend").mkdir()
    (repo / "backend" / "scoped.py").write_text("print('old scoped')\n")
    (repo / "backend" / "other.py").write_text("print('old other')\n")
    _init_git_repo(repo)
    _commit_all(repo, "initial")

    (repo / "backend" / "scoped.py").write_text("print('new scoped')\n")
    (repo / "backend" / "other.py").write_text("print('new other')\n")
    subprocess.run(["git", "add", "backend/scoped.py"], check=True, cwd=repo, capture_output=True, text=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dt_scope_log = tmp_path / "dt-scope.log"
    _write_executable(
        fake_bin / "dt",
        """#!/usr/bin/env bash
printf '%s\n' "${DT_CHANGED_ONLY_SCOPE:-unset}" >> "$DT_SCOPE_LOG"
echo "CHECK_RESULT:OK"
""",
    )

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "commit.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["COMMIT_SH_SOURCE_ONLY"] = "1"
    env["DT_SCOPE_LOG"] = str(dt_scope_log)
    env["GIT_AUTHOR_NAME"] = "Test User"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    command = f"""
source {shlex.quote(str(script_path))}
PUSH=false
run_destructive_path_guard() {{ return 0; }}
cross_layer_check() {{ return 0; }}
generate_ai_message() {{ echo "test: staged subset"; }}
run_git_commit() {{ command git commit --no-verify "$@"; }}
commit_project_repo {shlex.quote(str(repo))}
"""
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    head_files = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    ).stdout.splitlines()
    assert head_files == ["backend/scoped.py"]

    status_lines = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    ).stdout.splitlines()
    assert status_lines == [" M backend/other.py"]
    assert dt_scope_log.read_text().splitlines() == ["staged"]


def test_commit_sh_path_scope_ignores_unrelated_staged_and_hook_staged_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "backend").mkdir()
    (repo / "frontend").mkdir()
    (repo / "backend" / "scoped.py").write_text("print('old scoped')\n")
    (repo / "backend" / "other.py").write_text("print('old other')\n")
    (repo / "frontend" / "hook-only.tsx").write_text("export const HookOnly = 'old';\n")
    _init_git_repo(repo)
    _commit_all(repo, "initial")

    (repo / "backend" / "scoped.py").write_text("print('new scoped')\n")
    (repo / "backend" / "other.py").write_text("print('new other')\n")
    (repo / "frontend" / "hook-only.tsx").write_text("export const HookOnly = 'new';\n")
    subprocess.run(["git", "add", "backend/other.py"], check=True, cwd=repo, capture_output=True, text=True)
    subprocess.run(["git", "reset", "HEAD", "--", "frontend/hook-only.tsx"], check=True, cwd=repo, capture_output=True, text=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dt_scope_log = tmp_path / "dt-scope.log"
    hook_flag = tmp_path / "hook-flag"
    _write_executable(
        fake_bin / "dt",
        """#!/usr/bin/env bash
printf '%s\n' "${DT_CHANGED_ONLY_SCOPE:-unset}" >> "$DT_SCOPE_LOG"
echo "CHECK_RESULT:OK"
""",
    )

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "commit.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["COMMIT_SH_SOURCE_ONLY"] = "1"
    env["DT_SCOPE_LOG"] = str(dt_scope_log)
    env["HOOK_FLAG"] = str(hook_flag)
    env["GIT_AUTHOR_NAME"] = "Test User"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    command = f"""
source {shlex.quote(str(script_path))}
PUSH=false
COMMIT_PATHS=("backend/scoped.py")
run_destructive_path_guard() {{ return 0; }}
cross_layer_check() {{ return 0; }}
generate_ai_message() {{ echo "test: path scope"; }}
run_git_commit() {{
  if [[ ! -f "$HOOK_FLAG" ]]; then
    touch "$HOOK_FLAG"
    command git add backend/other.py frontend/hook-only.tsx
    return 1
  fi
  command git commit --no-verify "$@"
}}
commit_project_repo {shlex.quote(str(repo))}
"""
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    head_files = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    ).stdout.splitlines()
    assert head_files == ["backend/scoped.py"]

    status_lines = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    ).stdout.splitlines()
    assert status_lines == ["M  backend/other.py", " M frontend/hook-only.tsx"]
    assert dt_scope_log.read_text().splitlines() == ["staged"]


def test_commit_sh_preserves_whole_repo_behavior_without_pre_staged_subset(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "backend").mkdir()
    (repo / "backend" / "first.py").write_text("print('old first')\n")
    (repo / "backend" / "second.py").write_text("print('old second')\n")
    _init_git_repo(repo)
    _commit_all(repo, "initial")

    (repo / "backend" / "first.py").write_text("print('new first')\n")
    (repo / "backend" / "second.py").write_text("print('new second')\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dt_scope_log = tmp_path / "dt-scope.log"
    _write_executable(
        fake_bin / "dt",
        """#!/usr/bin/env bash
printf '%s\n' "${DT_CHANGED_ONLY_SCOPE:-unset}" >> "$DT_SCOPE_LOG"
echo "CHECK_RESULT:OK"
""",
    )

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "commit.sh"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["COMMIT_SH_SOURCE_ONLY"] = "1"
    env["DT_SCOPE_LOG"] = str(dt_scope_log)
    env["GIT_AUTHOR_NAME"] = "Test User"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    command = f"""
source {shlex.quote(str(script_path))}
PUSH=false
run_destructive_path_guard() {{ return 0; }}
cross_layer_check() {{ return 0; }}
generate_ai_message() {{ echo "test: whole repo"; }}
run_git_commit() {{ command git commit --no-verify "$@"; }}
commit_project_repo {shlex.quote(str(repo))}
"""
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    head_files = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    ).stdout.splitlines()
    assert head_files == ["backend/first.py", "backend/second.py"]

    status_output = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    ).stdout.strip()
    assert status_output == ""
