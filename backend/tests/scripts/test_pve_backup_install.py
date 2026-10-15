"""install.sh binds a new key to the dispatcher only, in one PVE session, and proves the key refuses a shell."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "pve-backup"
SOURCES = {"pve-cluster-config": {"digest": "a" * 64, "kind": "config", "vmid": None, "files": None}}


def _run(tmp_path: Path, *, shell_refused: bool = True) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "ssh.jsonl"
    (binary / "uv").write_text(f"#!/bin/sh\nprintf '%s' {json.dumps(json.dumps(SOURCES))!s}\n")
    (binary / "ssh").write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "args = sys.argv[1:]\n"
        "if args[0] == '-G':\n"
        "    print('user root'); print('hostname 192.0.2.39'); print('identityfile /home/x/.ssh/id_ed25519_davion_gem'); sys.exit(0)\n"
        "if 'bash' in args:\n"
        "    sys.stdin.read(); print('summitflow-pve-backup installed'); sys.exit(0)\n"
        f"sys.exit(0 if args[-1] == 'guests' else {2 if shell_refused else 0})\n"
    )
    # A real key pair is not needed: the test checks where the public half goes.
    (binary / "ssh-keygen").write_text(
        "#!/bin/sh\nwhile [ $# -gt 1 ]; do [ \"$1\" = -f ] && f=$2; shift; done\n"
        "printf 'private\\n' > \"$f\"; printf 'ssh-ed25519 AAAAC3fixture summitflow-pve-backup\\n' > \"$f.pub\"\n"
    )
    (binary / "python3").symlink_to(sys.executable)
    # The hermetic check sandbox has no coreutils base64; the installer only encodes (-w0).
    (binary / "base64").write_text(f"#!{sys.executable}\nimport base64, sys\nsys.stdout.write(base64.b64encode(sys.stdin.buffer.read()).decode())\n")
    for tool in ("uv", "ssh", "ssh-keygen", "base64"):
        (binary / tool).chmod(0o755)
    keys = tmp_path / "keys"
    keys.mkdir()
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}", "SUMMITFLOW_BACKUP_KEY_DIR": str(keys)}
    result = subprocess.run(["bash", str(SCRIPTS / "install.sh")], env=env, capture_output=True, text=True, timeout=60, check=False)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def test_install_binds_the_new_key_to_the_dispatcher_in_one_session(tmp_path):
    result, calls = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    sessions = [call for call in calls if "bash" in call]
    assert len(sessions) == 1 and sessions[0][:4] == ["proxmox-gem", "bash", "-s", "--"]
    dispatcher, sources, line = (base64.b64decode(item).decode() for item in sessions[0][4:])
    assert dispatcher == (SCRIPTS / "summitflow-pve-backup").read_text(), result.stderr
    assert json.loads(sources) == SOURCES
    key = tmp_path / "keys" / "pve-backup.ed25519"
    assert key.is_file() and not (tmp_path / "keys" / "pve-backup.ed25519.new").exists()
    public = " ".join(Path(f"{key}.pub").read_text().split()[:2])
    assert line == f'restrict,from="192.168.86.128",command="/usr/local/sbin/summitflow-pve-backup" {public} summitflow-pve-backup'
    # The proof runs with the new key alone: no ssh config (owner IdentityFile), no agent.
    checks = [call for call in calls if call[-1] in {"guests", "id"}]
    assert [call[-1] for call in checks] == ["guests", "id"]
    for call in checks:
        assert call[:2] == ["-F", "/dev/null"] and call[call.index("-i") + 1] == str(key)
        assert "IdentityAgent=none" in call and call[-2] == "root@192.0.2.39"
    assert "key refuses other commands" in result.stdout


def test_install_fails_loudly_when_the_key_runs_a_shell(tmp_path):
    result, _calls = _run(tmp_path, shell_refused=False)
    assert result.returncode != 0 and "ran a shell command" in result.stderr
