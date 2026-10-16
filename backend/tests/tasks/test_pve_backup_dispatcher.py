"""The Proxmox backup key's forced command runs fixed verbs only and never ships PVE's private keys."""

from __future__ import annotations

import base64
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.tasks import backup_proxmox as px

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "pve-backup" / "summitflow-pve-backup"
DIRECTORY, FILE = 4, 8


def _load() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("summitflow_pve_backup", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Runs:
    """Records each argv; answers like the PVE tools would."""

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.answers = answers or {}

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert isinstance(argv, list) and not kwargs.get("shell")
        self.calls.append(argv)
        answer = self.answers.get(argv[0], "")
        result = answer(argv) if callable(answer) else answer
        code, stdout = result if isinstance(result, tuple) else (0, result)
        return subprocess.CompletedProcess(argv, code, stdout, "")


@pytest.fixture
def dispatcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load()
    monkeypatch.setattr(module, "SOURCES", tmp_path / "sources.json")
    monkeypatch.setattr(module, "DUMP_DIRECTORY", tmp_path / "dump")
    monkeypatch.delenv("SSH_ORIGINAL_COMMAND", raising=False)
    return module


def _install(module: ModuleType, sources: dict[str, str]) -> dict[str, str]:
    """What install.sh writes: SummitFlow's own manifest of each registered path."""
    entries = {name: px.dispatcher_entry(path) for name, path in sources.items()}
    module.SOURCES.write_text(json.dumps(entries))
    return {name: px.path_digest(path) for name, path in sources.items()}


HOST = "proxmox://proxmox-gem/host/files?path=/vault/identity&path=/etc/pve/qemu-server/120.conf"
CT = "proxmox://proxmox-gem/lxc/140/files?via=pct&path=/srv/data&exclude=*.tmp"
VM = "proxmox://proxmox-gem/qemu/100/files?via=agent&path=/home/u/p&exclude=Cache"


@pytest.mark.parametrize("command", [
    "", "id", "bash -c id", "sh", "guests --type node", "thinpool pve/root", "capture", "capture pve-host-files",
    "pvesh delete /nodes/davion-gem/qemu/100", "vzdump 150 --stdout 1", "capture ../../etc/shadow " + "0" * 64,
    "capture pve-host-files " + "0" * 64 + " extra", "rm -rf /",
])
def test_only_the_fixed_verbs_run(dispatcher, command, capsys):
    runs = Runs()
    _install(dispatcher, {"pve-host-files": HOST})
    assert dispatcher.main(command, run=runs, out=io.BytesIO()) == 2
    assert runs.calls == [] and "summitflow-pve-backup:" in capsys.readouterr().err


def test_forced_command_reads_the_original_ssh_command(dispatcher, monkeypatch):
    runs = Runs()
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "guests")
    assert dispatcher.main(run=runs) == 0
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "thinpool")
    assert dispatcher.main(run=runs) == 0
    assert runs.calls == [["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"],
                          ["lvs", "--noheadings", "-o", "data_percent", "pve/data"]]


def test_capture_needs_the_installed_source_and_its_current_path(dispatcher, capsys):
    digests = _install(dispatcher, {"pve-host-files": HOST})
    runs = Runs()
    # A source registered (or changed) on the workstation after root installed the list is refused.
    assert dispatcher.main(f"capture pve-other {digests['pve-host-files']}", run=runs, out=io.BytesIO()) == 2
    assert "not installed" in capsys.readouterr().err
    changed = px.path_digest(HOST + "&path=/etc/pve/priv")
    assert dispatcher.main(f"capture pve-host-files {changed}", run=runs, out=io.BytesIO()) == 2
    assert "changed on the workstation" in capsys.readouterr().err
    assert runs.calls == []
    assert dispatcher.main(f"capture pve-host-files {digests['pve-host-files']}", run=runs, out=io.BytesIO()) == 0
    assert runs.calls and runs.calls[0][0] == "tar"


@pytest.mark.parametrize("entry", [
    {"kind": "host", "vmid": None, "files": {"via": "host", "paths": ["/a/../etc/pve/priv"], "excludes": []}},
    {"kind": "host", "vmid": None, "files": {"via": "host", "paths": ["etc/shadow"], "excludes": []}},
    {"kind": "host", "vmid": None, "files": {"via": "host", "paths": ["/x;id"], "excludes": []}},
    {"kind": "host", "vmid": None, "files": {"via": "host", "paths": ["/x"], "excludes": ["$(id)"]}},
    {"kind": "host", "vmid": None, "files": {"via": "pct", "paths": ["/x"], "excludes": []}},
    {"kind": "host", "vmid": None, "files": None},
    {"kind": "lxc", "vmid": "140; id", "files": None},
    {"kind": "lxc", "vmid": True, "files": None},
    {"kind": "qemu", "vmid": 100, "files": {"via": "pct", "paths": ["/x"], "excludes": []}},
    {"kind": "config", "vmid": 1, "files": None},
    {"kind": "shell", "vmid": None, "files": None},
])
def test_a_tampered_source_list_is_refused(dispatcher, entry, capsys):
    digest = "a" * 64
    dispatcher.SOURCES.write_text(json.dumps({"s": {**entry, "digest": digest}}))
    runs = Runs()
    assert dispatcher.main(f"capture s {digest}", run=runs, out=io.BytesIO()) == 2
    assert runs.calls == []


def _config_db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE tree (inode INTEGER PRIMARY KEY NOT NULL, parent INTEGER NOT NULL, version INTEGER NOT NULL, "
               "writer INTEGER NOT NULL, mtime INTEGER NOT NULL, type INTEGER NOT NULL, name TEXT NOT NULL, data BLOB)")
    rows = [
        (0, 0, FILE, "__version__", None),
        (1, 0, DIRECTORY, "priv", None),
        (2, 1, FILE, "authkey.key", b"AUTHKEY-SECRET"),
        (3, 1, FILE, "token.cfg", b"TOKEN-SECRET"),
        (4, 1, DIRECTORY, "lock", None),
        (5, 4, FILE, "deep", b"DEEP-SECRET"),
        (6, 0, FILE, "pve-www.key", b"WWW-SECRET"),
        (7, 0, FILE, "pve-root-ca.pem", b"public-ca"),
        (8, 0, DIRECTORY, "nodes", None),
        (9, 8, DIRECTORY, "davion-gem", None),
        (10, 9, FILE, "pve-ssl.key", b"SSL-SECRET"),
        (11, 9, FILE, "pve-ssl.pem", b"public-cert"),
        (12, 9, DIRECTORY, "priv", None),
        (13, 12, FILE, "acme.cfg", b"NODE-PRIV-SECRET"),
        (14, 9, DIRECTORY, "qemu-server", None),
        (15, 14, FILE, "100.conf", b"name: st-browser"),
        (16, 0, FILE, "storage.cfg", b"dir: local"),
        (17, 0, FILE, "pve-root-ca.KEY", b"CASE-SECRET"),
    ]
    db.executemany("INSERT INTO tree VALUES (?, ?, 1, 0, 0, ?, ?, ?)", rows)
    db.commit()
    db.close()


def test_config_dump_leaves_out_priv_and_every_key_file(dispatcher, tmp_path, monkeypatch):
    database = tmp_path / "config.db"
    _config_db(database)
    monkeypatch.setattr(dispatcher, "CONFIG_DATABASE", str(database))
    _install(dispatcher, {"pve-cluster-config": "proxmox://proxmox-gem/config"})
    out = io.BytesIO()
    command = f"capture pve-cluster-config {px.path_digest('proxmox://proxmox-gem/config')}"
    assert dispatcher.main(command, run=Runs(), out=out) == 0
    dump = out.getvalue()
    assert dump.startswith(b"BEGIN TRANSACTION")  # what the stored-stream header check expects
    assert b"SECRET" not in dump and b"'priv'" not in dump and b".key'" not in dump and b".KEY'" not in dump
    restored = sqlite3.connect(":memory:")
    restored.executescript(dump.decode())
    names = {row[0] for row in restored.execute("SELECT name FROM tree")}
    assert names == {"__version__", "pve-root-ca.pem", "nodes", "davion-gem", "pve-ssl.pem", "qemu-server", "100.conf", "storage.cfg"}
    # The source database is opened read-only and left as it was.
    assert sqlite3.connect(database).execute("SELECT count(*) FROM tree").fetchone() == (18,)


LIVE_HOST = ("proxmox://proxmox-gem/host/files?path=/vault/identity&path=/vault/meta/recovery-key.json"
             "&path=/etc/pve/qemu-server/120.conf&path=/var/lib/vz/snippets/neri-120-init.yaml")


@pytest.mark.parametrize("path", [
    "/", "/var", "/var/lib", "/var/lib/pve-cluster", "/var/lib/pve-cluster/config.db", "/etc", "/etc/pve", "/etc/pve/priv",
    "/etc/pve/priv/authkey.key", "/etc/pve/nodes", "/etc/pve/nodes/davion-gem", "/etc/pve/nodes/x/priv",
    "/etc/pve/nodes/x/priv/acme.cfg", "/etc/pve/local/priv", "/etc/pve/local/priv/x", "/etc/pve/pve-www.KEY",
    "/etc/pve/nodes/x/pve-ssl.key", "/root", "/root/.ssh", "/root/.ssh/authorized_keys", "/etc/ssh",
    "/etc/ssh/ssh_host_ed25519_key", "/etc/corosync", "/etc/corosync/authkey",
])
def test_a_host_path_holding_pve_or_root_secrets_is_refused(dispatcher, path, capsys):
    # Written as root would install it from an agent-registered source; the floor holds whatever the workstation parsed.
    files = {"via": "host", "paths": ["/vault/identity", path], "excludes": []}
    dispatcher.SOURCES.write_text(json.dumps({"h": {"digest": "a" * 64, "kind": "host", "vmid": None, "files": files}}))
    runs = Runs()
    assert dispatcher.main(f"capture h {'a' * 64}", run=runs, out=io.BytesIO()) == 2
    error = capsys.readouterr().err
    assert runs.calls == [] and ("holds PVE or root secrets" in error or (path == "/" and "unsafe path" in error))
    assert dispatcher.protected_host_path(path)


def test_a_host_path_is_also_checked_where_it_resolves(dispatcher, monkeypatch):
    real = os.path.realpath
    monkeypatch.setattr(dispatcher.os.path, "realpath",
                        lambda path: "/etc/pve/nodes/davion-gem/priv/lock" if path == "/vault/link" else real(path))
    digests = _install(dispatcher, {"h": "proxmox://proxmox-gem/host/files?path=/vault/link"})
    runs = Runs()
    assert dispatcher.main(f"capture h {digests['h']}", run=runs, out=io.BytesIO()) == 2
    assert runs.calls == []


def test_the_registered_host_files_still_pass_the_floor(dispatcher):
    digests = _install(dispatcher, {"h": LIVE_HOST})
    runs = Runs()
    assert dispatcher.main(f"capture h {digests['h']}", run=runs, out=io.BytesIO()) == 0
    assert runs.calls[0][-4:] == ["vault/identity", "vault/meta/recovery-key.json", "etc/pve/qemu-server/120.conf",
                                  "var/lib/vz/snippets/neri-120-init.yaml"]


@pytest.mark.parametrize("path", [
    "proxmox://proxmox-gem/lxc/150", "proxmox://proxmox-gem/lxc/160", "proxmox://proxmox-gem/qemu/150",
    "proxmox://proxmox-gem/lxc/150/files?via=pct&path=/var/lib/ominull-response-authority",
])
def test_the_ominull_hub_and_append_only_restic_are_never_captured(dispatcher, path, capsys):
    digests = _install(dispatcher, {"g": path})
    runs = Runs()
    assert dispatcher.main(f"capture g {digests['g']}", run=runs, out=io.BytesIO()) == 2
    assert runs.calls == [] and "never captured" in capsys.readouterr().err


def test_sources_shows_the_installed_list(dispatcher):
    out = io.BytesIO()
    assert dispatcher.main("sources", run=Runs(), out=out) == 0 and json.loads(out.getvalue()) == {}
    _install(dispatcher, {"h": HOST})
    out = io.BytesIO()
    assert dispatcher.main("sources", run=Runs(), out=out) == 0 and sorted(json.loads(out.getvalue())) == ["h"]


@pytest.mark.skipif(shutil.which("tar") is None, reason="needs GNU tar")
def test_the_host_floor_excludes_secrets_under_an_allowed_directory(dispatcher, tmp_path):
    root = tmp_path / "root"
    files = ["etc/pve/priv/authkey.key", "etc/pve/nodes/gem/priv/acme.cfg", "etc/pve/pve-www.KEY", "etc/pve/nodes/gem/pve-ssl.key",
             "etc/pve/qemu-server/120.conf", "var/lib/pve-cluster/config.db", "root/.ssh/id", "etc/ssh/ssh_host_ed25519_key",
             "etc/ssh/sshd_config", "vault/identity/a"]
    for name in files:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x")
    (root / "etc/pve/local").symlink_to("nodes/gem")
    command = dispatcher.tar_command({"paths": ["/etc", "/var", "/root", "/vault", "/etc/pve/local/priv/acme.cfg"], "excludes": []}, host=True)
    command[command.index("-C") + 1] = str(root)
    stream = subprocess.run(command, capture_output=True, check=False)
    assert stream.returncode <= 1
    listed = set(subprocess.run(["tar", "-t"], input=stream.stdout, capture_output=True, check=True).stdout.decode().split())
    assert {"etc/pve/qemu-server/120.conf", "etc/ssh/sshd_config", "vault/identity/a", "etc/pve/local"} <= listed
    assert not [name for name in listed if "priv" in name or name.lower().endswith(".key") or "pve-cluster/" in name
                or ".ssh/" in name or "ssh_host" in name]


def test_host_tar_never_carries_pve_private_files_and_accepts_a_changed_file(dispatcher):
    digests = _install(dispatcher, {"h": HOST})
    runs = Runs({"tar": (1, "")})
    assert dispatcher.main(f"capture h {digests['h']}", run=runs, out=io.BytesIO()) == 0
    tar = runs.calls[0]
    floor = tar[tar.index("--ignore-case"):tar.index("--no-ignore-case")]
    assert {"--exclude=etc/pve/priv", "--exclude=etc/pve/*/priv", "--exclude=etc/pve/*.key", "--exclude=var/lib/pve-cluster",
            "--exclude=root/.ssh", "--exclude=etc/ssh/ssh_host_*"} <= set(floor)
    assert tar[tar.index("--") + 1:] == ["vault/identity", "etc/pve/qemu-server/120.conf"]
    assert dispatcher.main(f"capture h {digests['h']}", run=Runs({"tar": (2, "")}), out=io.BytesIO()) == 2


def test_container_files_run_tar_through_pct_without_a_shell(dispatcher):
    digests = _install(dispatcher, {"ct": CT})
    runs = Runs()
    assert dispatcher.main(f"capture ct {digests['ct']}", run=runs, out=io.BytesIO()) == 0
    command = runs.calls[0]
    assert command[:4] == ["pct", "exec", "140", "--"] and command[4] == "tar" and "sh" not in command and "-c" not in command
    assert "--exclude=*.tmp" in command and command[-1] == "srv/data"


def test_whole_guest_streams_in_snapshot_mode_and_trims_week_old_logs(dispatcher):
    path = "proxmox://proxmox-gem/lxc/140"
    digests = _install(dispatcher, {"ct": path})
    logs = dispatcher.DUMP_DIRECTORY
    logs.mkdir()
    old, recent, other = logs / "vzdump-lxc-140-2026_10_01.log", logs / "vzdump-lxc-140-2026_10_14.log", logs / "vzdump-lxc-150-2026_10_01.log"
    for item in (old, recent, other):
        item.write_text("log")
    stamp = time.time() - 8 * 86400
    os.utime(old, (stamp, stamp))
    os.utime(other, (stamp, stamp))
    runs = Runs()
    assert dispatcher.main(f"capture ct {digests['ct']}", run=runs, out=io.BytesIO()) == 0
    assert runs.calls == [["vzdump", "140", "--stdout", "1", "--mode", "snapshot", "--compress", "0", "--quiet", "1"]]
    assert not old.exists() and recent.exists() and other.exists()


def _agent(parts: str, contents: dict[str, bytes]):
    def qm(argv: list[str]) -> str:
        command = argv[-1]
        if command.startswith("ls -1 "):
            return json.dumps({"exitcode": 0, "out-data": parts})
        return json.dumps({"exitcode": 0})

    def pvesh(argv: list[str]) -> str:
        if argv[2] == "/cluster/resources":
            return json.dumps([{"vmid": 100, "type": "qemu", "node": "davion-gem"}])
        name = argv[argv.index("--file") + 1].rsplit("/", 1)[1]
        return json.dumps({"content": base64.b64encode(contents[name]).decode()})

    return {"qm": qm, "pvesh": pvesh}


def test_vm_files_come_back_through_the_guest_agent_and_the_guest_copy_is_always_removed(dispatcher):
    digests = _install(dispatcher, {"vm": VM})
    runs = Runs(_agent("part.00001\npart.00000\n", {"part.00000": b"AB", "part.00001": b"CD"}))
    out = io.BytesIO()
    assert dispatcher.main(f"capture vm {digests['vm']}", run=runs, out=out) == 0
    assert out.getvalue() == b"ABCD"
    build = runs.calls[1]
    assert build[:4] == ["qm", "guest", "exec", "100"] and "--exclude=Cache" in build[-1] and "home/u/p" in build[-1]
    assert runs.calls[-1][-1].startswith("rm -rf /tmp/st-backup-")
    reads = [call for call in runs.calls if call[0] == "pvesh" and "file-read" in call[2]]
    assert [call[2] for call in reads] == ["/nodes/davion-gem/qemu/100/agent/file-read"] * 2


def test_a_guest_cannot_steer_the_host_side_read(dispatcher):
    digests = _install(dispatcher, {"vm": VM})
    runs = Runs(_agent("part.00000\n../../../etc/pve/priv/authkey.key\n", {"part.00000": b"AB"}))
    assert dispatcher.main(f"capture vm {digests['vm']}", run=runs, out=io.BytesIO()) == 2
    assert not any("authkey" in " ".join(call) for call in runs.calls if call[0] == "pvesh")
    assert runs.calls[-1][-1].startswith("rm -rf /tmp/st-backup-")


def test_the_installed_list_is_built_from_summitflow_sources_only_for_the_hosts_own_reads(monkeypatch):
    sources = [
        {"id": "config", "enabled": True, "path": "proxmox://proxmox-gem/config"},
        {"id": "files", "enabled": True, "path": HOST},
        {"id": "ssh-guest", "enabled": True, "path": "proxmox://proxmox-gem/lxc/140/files?via=neri-lab&path=/srv"},
        {"id": "off", "enabled": False, "path": CT},
        {"id": "elsewhere", "enabled": True, "path": "proxmox://other-pve/config"},
        {"id": "local", "enabled": True, "path": "/srv/workspaces/projects/x"},
    ]
    monkeypatch.setattr(px.backup_store, "list_sources", lambda: sources)
    installed = px.dispatcher_sources("proxmox-gem")
    assert sorted(installed) == ["config", "files"]
    assert installed["files"] == {"digest": hashlib.sha256(HOST.encode()).hexdigest(), "kind": "host", "vmid": None,
                                  "files": {"via": "host", "paths": ["/vault/identity", "/etc/pve/qemu-server/120.conf"], "excludes": []}}
