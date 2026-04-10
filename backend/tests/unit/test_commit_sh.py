"""Tests for shared commit.sh workflow reporting."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


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
    subprocess.run(
        ["bash", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    logged = log_path.read_text().splitlines()
    assert logged == [
        "Elias Leslie",
        "56698332+elias-leslie@users.noreply.github.com",
        "Elias Leslie",
        "56698332+elias-leslie@users.noreply.github.com",
    ]
