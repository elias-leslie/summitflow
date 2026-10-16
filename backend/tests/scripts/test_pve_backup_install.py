"""install.sh binds a new key to the committed dispatcher only, in one PVE session, and proves the key refuses a shell."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "pve-backup"
SOURCES = {"pve-cluster-config": {"digest": "a" * 64, "kind": "config", "vmid": None, "files": None}}
GOOD = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI" + "G" * 43
ATTACKER = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI" + "A" * 43
LINE_RE = r'restrict,from="[0-9.]+",command="/usr/local/sbin/summitflow-pve-backup" ssh-ed25519 [A-Za-z0-9+/]{68} summitflow-pve-backup'


def _repo(tmp_path: Path) -> Path:
    """A committed copy of scripts/pve-backup: root installs only what git HEAD holds."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "backend").mkdir()
    shutil.copytree(SCRIPTS, repo / "scripts" / "pve-backup")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "fixture"], check=True)
    return repo


def _run(tmp_path: Path, *, shell_refused: bool = True, derived: str = GOOD, args: tuple[str, ...] | None = None,
         installed: dict | None = None, existing_pub: str | None = None, edit=None,
         between=None) -> tuple[subprocess.CompletedProcess[str], list[list[str]], list[str]]:
    """Run install.sh with no terminal. args=None is the owner's flow: a first run prints the approval digest, the second
    passes it with --yes (between(repo, binary) changes things in between)."""
    repo = _repo(tmp_path)
    if edit:
        edit(repo)
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "ssh.jsonl"
    remote = tmp_path / "remote.log"
    _uv(binary, SOURCES)
    # The PVE side runs the real remote script up to the key-line check, so a malformed line is refused there too.
    (binary / "ssh").write_text(
        f"#!{sys.executable}\n"
        "import json, re, sys, base64\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "args = sys.argv[1:]\n"
        "if args[0] == '-G':\n"
        "    print('user root'); print('hostname 192.0.2.39'); print('identityfile /home/x/.ssh/id_ed25519_davion_gem'); sys.exit(0)\n"
        "if 'bash' in args:\n"
        "    script = sys.stdin.read(); line = base64.b64decode(args[-1]).decode()\n"
        f"    open({str(remote)!r}, 'a').write(line + '\\n')\n"
        f"    if not re.fullmatch({LINE_RE!r}, line): sys.exit(1)\n"
        "    print('summitflow-pve-backup installed'); sys.exit(0)\n"
        f"if args[-1] == 'sources': print({json.dumps(json.dumps(installed))!s}) if {installed is not None} else sys.exit(2); sys.exit(0)\n"
        f"sys.exit(0 if args[-1] == 'guests' else {2 if shell_refused else 0})\n"
    )
    # A real key pair is not needed: -y answers what the private key would derive.
    (tmp_path / "derived.pub").write_text(derived + "\n")
    (binary / "ssh-keygen").write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = -y ]; then cat {str(tmp_path / 'derived.pub')!r}; exit 0; fi\n"
        "while [ $# -gt 1 ]; do [ \"$1\" = -f ] && f=$2; shift; done\n"
        f"printf 'private\\n' > \"$f\"; printf '%s summitflow-pve-backup\\n' '{GOOD}' > \"$f.pub\"\n"
    )
    (binary / "python3").symlink_to(sys.executable)
    # The hermetic check sandbox has no coreutils base64; the installer only encodes (-w0).
    (binary / "base64").write_text(f"#!{sys.executable}\nimport base64, sys\nsys.stdout.write(base64.b64encode(sys.stdin.buffer.read()).decode())\n")
    for tool in ("uv", "ssh", "ssh-keygen", "base64"):
        (binary / tool).chmod(0o755)
    keys = tmp_path / "keys"
    keys.mkdir()
    if existing_pub is not None:
        (keys / "pve-backup.ed25519").write_text("private\n")
        (keys / "pve-backup.ed25519.pub").write_text(existing_pub)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}", "SUMMITFLOW_BACKUP_KEY_DIR": str(keys)}

    def install(*argv: str) -> subprocess.CompletedProcess[str]:
        log.unlink(missing_ok=True)
        return subprocess.run(["bash", str(repo / "scripts" / "pve-backup" / "install.sh"), *argv], env=env, capture_output=True,
                              text=True, timeout=60, check=False, stdin=subprocess.DEVNULL)

    if args is None:
        shown = install()
        digest = re.search(r"^Approval digest: ([0-9a-f]{64}) ", shown.stdout, re.MULTILINE)
        assert shown.returncode != 0 and (not digest or f"re-run with --yes {digest[1]}" in shown.stderr)
        if between:
            between(repo, binary)
    result = install("--yes", digest[1]) if args is None and digest else shown if args is None else install(*args)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    lines = remote.read_text().splitlines() if remote.exists() else []
    return result, calls, lines


def _uv(binary: Path, sources: dict) -> None:
    (binary / "uv").write_text(f"#!/bin/sh\nprintf '%s' {json.dumps(json.dumps(sources))!s}\n")
    (binary / "uv").chmod(0o755)


def _sessions(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if "bash" in call]


def test_install_binds_the_new_key_to_the_committed_dispatcher_in_one_session(tmp_path):
    result, calls, _lines = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    sessions = _sessions(calls)
    assert len(sessions) == 1 and sessions[0][:4] == ["proxmox-gem", "bash", "-s", "--"]
    dispatcher, sources, line = (base64.b64decode(item).decode() for item in sessions[0][4:])
    assert dispatcher == (SCRIPTS / "summitflow-pve-backup").read_text(), result.stderr
    assert re.search(r"sha256 [0-9a-f]{64}", result.stdout)
    assert json.loads(sources) == SOURCES
    assert "+ pve-cluster-config" in result.stdout
    key = tmp_path / "keys" / "pve-backup.ed25519"
    assert key.is_file() and not (tmp_path / "keys" / "pve-backup.ed25519.new").exists()
    assert line == f'restrict,from="192.168.86.128",command="/usr/local/sbin/summitflow-pve-backup" {GOOD} summitflow-pve-backup'
    # The proof runs with the new key alone: no ssh config (owner IdentityFile), no agent.
    checks = [call for call in calls if call[-1] in {"guests", "id"}]
    assert [call[-1] for call in checks] == ["guests", "id"]
    for call in checks:
        assert call[:2] == ["-F", "/dev/null"] and call[call.index("-i") + 1] == str(key)
        assert "IdentityAgent=none" in call and call[-2] == "root@192.0.2.39"
    assert "key refuses other commands" in result.stdout


def test_the_key_line_comes_from_the_private_key_not_a_tampered_pub_file(tmp_path):
    # An agent rewrites the .pub file next to an existing key with a second, option-free line.
    result, calls, lines = _run(tmp_path, existing_pub=f"{GOOD} x\n{ATTACKER} summitflow-pve-backup\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert lines == [f'restrict,from="192.168.86.128",command="/usr/local/sbin/summitflow-pve-backup" {GOOD} summitflow-pve-backup']
    assert ATTACKER not in json.dumps(calls)


@pytest.mark.parametrize("derived", [
    f"{GOOD}\n{ATTACKER}",  # two keys
    f'command="/bin/sh" {GOOD}',  # an options prefix
    f"{GOOD[:-1]}",  # not an ed25519 key body
    "ssh-rsa AAAAB3NzaC1yc2E",
    f"{GOOD} comment\n{ATTACKER}",
])
def test_anything_but_one_plain_ed25519_key_installs_nothing(tmp_path, derived):
    result, calls, _lines = _run(tmp_path, derived=derived)
    assert result.returncode != 0 and "exactly one ed25519 key" in result.stderr
    assert _sessions(calls) == []


@pytest.mark.parametrize("installed", [None, SOURCES])
def test_nothing_installs_without_confirmation_even_when_the_list_is_unchanged(tmp_path, installed):
    # The dispatcher may still differ from the installed one, so every install is confirmed.
    result, calls, _lines = _run(tmp_path, args=(), installed=installed, existing_pub=f"{GOOD} x\n")
    assert result.returncode != 0 and re.search(r"re-run with --yes [0-9a-f]{64}$", result.stderr.strip())
    assert "pve-cluster-config" in result.stdout and _sessions(calls) == []


@pytest.mark.parametrize("args", [("--yes",), ("--yes", "0" * 64), ("--yes", "x", "y"), ("--force",)])
def test_yes_needs_the_digest_that_was_shown(tmp_path, args):
    result, calls, _lines = _run(tmp_path, args=args)
    assert result.returncode != 0 and ("usage" in result.stderr or "not the one approved" in result.stderr)
    assert _sessions(calls) == []


def test_a_source_list_changed_after_review_is_refused(tmp_path):
    widened = {**SOURCES, "late": {"digest": "c" * 64, "kind": "lxc", "vmid": 140, "files": None}}
    result, calls, _lines = _run(tmp_path, between=lambda _repo, binary: _uv(binary, widened))
    assert result.returncode != 0 and "not the one approved" in result.stderr and "+ late" in result.stdout
    assert _sessions(calls) == []


def test_a_dispatcher_committed_after_review_is_refused(tmp_path):
    def commit(repo: Path, _binary: Path) -> None:
        path = repo / "scripts" / "pve-backup" / "summitflow-pve-backup"
        path.write_text(path.read_text() + "\n# later\n")
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "commit", "-q", "-am", "later"], check=True)

    result, calls, _lines = _run(tmp_path, between=commit)
    assert result.returncode != 0 and "not the one approved" in result.stderr
    assert _sessions(calls) == []


def test_the_digest_covers_the_dispatcher_and_the_canonical_list(tmp_path):
    result, calls, _lines = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    dispatcher, sources, _line = (base64.b64decode(item) for item in _sessions(calls)[0][4:])
    expected = hashlib.sha256(b"dispatcher " + hashlib.sha256(dispatcher).hexdigest().encode() + b"\n" + sources).hexdigest()
    assert f"Approval digest: {expected} " in result.stdout
    assert sources == (json.dumps(SOURCES, indent=1, sort_keys=True) + "\n").encode()


def test_a_changed_entry_is_marked_against_the_installed_list(tmp_path):
    before = {"pve-cluster-config": {**SOURCES["pve-cluster-config"], "digest": "b" * 64}, "gone": SOURCES["pve-cluster-config"]}
    result, _calls, _lines = _run(tmp_path, args=(), installed=before, existing_pub=f"{GOOD} x\n")
    assert result.returncode != 0
    assert "~ pve-cluster-config" in result.stdout and "- gone" in result.stdout


def test_an_uncommitted_dispatcher_is_never_installed(tmp_path):
    def edit(repo: Path) -> None:
        path = repo / "scripts" / "pve-backup" / "summitflow-pve-backup"
        path.write_text(path.read_text() + "\nimport os; os.execv('/bin/sh', ['sh'])\n")

    result, calls, _lines = _run(tmp_path, edit=edit)
    assert result.returncode != 0 and "uncommitted changes" in result.stderr
    assert _sessions(calls) == []


def test_install_fails_loudly_when_the_key_runs_a_shell(tmp_path):
    result, _calls, _lines = _run(tmp_path, shell_refused=False)
    assert result.returncode != 0 and "ran a shell command" in result.stderr


def test_the_pve_side_refuses_a_malformed_key_line(tmp_path):
    """The remote script checks the decoded line itself before installing anything."""
    script = (SCRIPTS / "install.sh").read_text()
    remote = script.split("<<'REMOTE'\n", 1)[1].split("\nREMOTE\n", 1)[0]
    check = remote.split("tmp=", 1)[0]
    for line, ok in [
        (f'restrict,from="192.168.86.128",command="/usr/local/sbin/summitflow-pve-backup" {GOOD} summitflow-pve-backup', True),
        (f'restrict,from="192.168.86.128",command="/usr/local/sbin/summitflow-pve-backup" {GOOD}\n{ATTACKER} summitflow-pve-backup', False),
        (f"{ATTACKER} summitflow-pve-backup", False),
        (f'from="192.168.86.128",command="/usr/local/sbin/summitflow-pve-backup" {GOOD} summitflow-pve-backup', False),
    ]:
        encoded = base64.b64encode(line.encode()).decode()
        # base64 -d is the only external tool before the check; stand in for it where coreutils is missing.
        decoder = tmp_path / "bin-decode"
        decoder.mkdir(exist_ok=True)
        (decoder / "base64").write_text(f"#!{sys.executable}\nimport base64, sys\nsys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))\n")
        (decoder / "base64").chmod(0o755)
        env = {**os.environ, "PATH": f"{decoder}:{os.environ['PATH']}"}
        result = subprocess.run(["bash", "-c", check, "remote", "x", "y", encoded], env=env, capture_output=True, text=True, check=False)
        assert (result.returncode == 0) is ok, (line, result.stderr)
