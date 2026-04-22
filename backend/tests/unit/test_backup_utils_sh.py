"""Regression tests for shell backup helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_upload_with_retry_allows_missing_project_dir_when_share_is_reachable(tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    project_dir = tmp_path / "newproj"
    project_dir.mkdir()
    archive = tmp_path / "newproj-20260422.tar.gz"
    archive.write_text("backup-data")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_root = tmp_path / "remote-share"
    remote_root.mkdir()
    smb_log = tmp_path / "smb.log"

    _write_executable(
        fake_bin / "smbclient",
        f"""#!/usr/bin/env bash
set -euo pipefail
cmd=""
while (($#)); do
  if [[ "$1" == "-c" ]]; then
    shift
    cmd="$1"
    break
  fi
  shift
done
printf '%s\n' "$cmd" >> {str(smb_log)!r}
remote_root={str(remote_root)!r}
case "$cmd" in
  "cd project-backups; ls")
    exit 0
    ;;
  "ls project-backups/newproj")
    # Simulate the first-upload case: share is reachable, but the per-project
    # directory does not exist yet.
    exit 1
    ;;
  "mkdir project-backups/newproj")
    mkdir -p "$remote_root/project-backups/newproj"
    exit 0
    ;;
  "cd project-backups/newproj; put "*" newproj-20260422.tar.gz")
    cp {str(archive)!r} "$remote_root/project-backups/newproj/{archive.name}"
    exit 0
    ;;
  "cd project-backups/newproj; ls {archive.name}")
    if [[ -f "$remote_root/project-backups/newproj/{archive.name}" ]]; then
      printf '%s\n' {archive.name!r}
      exit 0
    fi
    exit 1
    ;;
  *)
    printf 'unexpected smbclient command: %s\n' "$cmd" >&2
    exit 1
    ;;
esac
""",
    )

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "backup-utils.sh"
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["PROJECT_DIR"] = str(project_dir)
    env["SMB_HOST"] = "192.168.8.128"
    env["SMB_SHARE"] = "davion-gem"
    env["SMB_USER"] = "backup-svc"
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-lc",
            (
                f'source "{script_path}"; '
                'mkdir -p "$(dirname "$CREDENTIALS_FILE")"; '
                ': > "$CREDENTIALS_FILE"; '
                f'upload_with_retry "{archive}" "{archive.name}" "newproj"'
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    assert "Upload complete (verified)" in result.stdout
    assert (remote_root / "project-backups" / "newproj" / archive.name).exists()
    assert not (home_dir / ".local" / "share" / "backup-pending" / archive.name).exists()

    log_lines = smb_log.read_text().splitlines()
    assert "cd project-backups; ls" in log_lines
    assert "ls project-backups/newproj" not in log_lines
