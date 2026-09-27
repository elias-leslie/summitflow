"""Fixed privileged installation of the accepted host collector release.

Invoked by st through sudo -n, never by the web API. No sudo policy is installed.
The user collector is retained for a reversible first migration.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import time
import zipfile
from pathlib import Path

UNIT = "summitflow-host-monitor.service"
INSTALL = Path("/usr/local/lib/summitflow-host-monitor")
STATE = Path("/var/lib/summitflow/monitor")
UNIT_PATH = Path("/etc/systemd/system") / UNIT
RECEIPTS = Path("/var/lib/summitflow/monitor-deployments")


def build_helper(source: Path) -> Path:
    """Package only stdlib diagnostics; no backend environment runs as root."""
    target = source / "host-monitor/target/release/monitor-observe.pyz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"#!/usr/bin/python3 -I\n")
    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("__main__.py", "from monitor_observe.privileged_entry import main\nraise SystemExit(main())\n")
        for package in ("monitor_observe", "monitor_extended"):
            archive.writestr(f"{package}/__init__.py", "")
        for name in ("monitor_observe/privileged_entry.py", "monitor_observe/common.py",
                     "monitor_observe/connections.py", "monitor_observe/logs.py",
                     "monitor_extended/disk.py"):
            archive.write(source / "backend" / name, name)
    target.chmod(0o755)
    return target


def _directory(path: Path, mode: int = 0o755) -> None:
    if path.resolve() != path:
        raise RuntimeError(f"refusing symlink directory: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    if path.stat().st_uid != 0:
        raise RuntimeError(f"installation directory is not root owned: {path}")
    path.chmod(mode)


def _write(path: Path, data: bytes, mode: int = 0o644) -> None:
    temporary = path.with_name(path.name + ".next")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(mode)
    os.replace(temporary, path)


def _system(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/usr/bin/systemctl", *args], check=check, text=True, capture_output=True, timeout=45)


def _user(uid: int, gid: int, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    account = pwd.getpwuid(uid)
    env = {"PATH": "/usr/bin:/bin", "HOME": account.pw_dir,
           "XDG_RUNTIME_DIR": f"/run/user/{uid}",
           "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}
    return subprocess.run(["/usr/bin/systemctl", "--user", *args], env=env,
                          user=uid, group=gid, extra_groups=[], check=check,
                          text=True, capture_output=True, timeout=45)


def _backup(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file() or destination.exists():
        raise RuntimeError("invalid monitor database backup paths")
    with (
        sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin,
        sqlite3.connect(destination) as target,
    ):
        origin.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError("monitor backup integrity check failed")


def _receipt(path: Path, record: dict) -> None:
    _write(path, json.dumps(record, sort_keys=True).encode(), 0o600)


def _state_permissions(gid: int) -> None:
    os.chown(STATE, 0, gid)
    STATE.chmod(0o750)
    for name in ("monitor.sqlite3", "monitor.sqlite3-wal", "monitor.sqlite3-shm", "maintenance.lock"):
        path = STATE / name
        if path.exists():
            if path.is_symlink():
                raise RuntimeError("monitor state contains a symlink")
            os.chown(path, 0, gid)
            path.chmod(0o640)


def install(source: Path, uid: int, gid: int, transaction: str) -> None:
    if uid == 0 or pwd.getpwuid(uid).pw_gid != gid:
        raise RuntimeError("collector owner must be a non-root account and its primary group")
    _directory(INSTALL)
    _directory(INSTALL / "releases")
    _directory(RECEIPTS, 0o700)
    receipt = RECEIPTS / f"{transaction}.json"
    if receipt.exists() or any(RECEIPTS.glob("*.pending")):
        raise RuntimeError("monitor deployment already exists or requires recovery")
    release = INSTALL / "releases" / transaction
    release.mkdir(mode=0o755)
    for filename, relative in (
        ("summitflow-host-monitor", "host-monitor/target/release/summitflow-host-monitor"),
        ("monitor-observe.pyz", "host-monitor/target/release/monitor-observe.pyz"),
        ("project.identity.json", "project.identity.json"),
        ("policy.json", "host-monitor/target/release/policy.json"),
    ):
        src = source / relative
        if src.is_symlink() or not src.is_file():
            raise RuntimeError("accepted monitor artifact is absent or a symlink")
        _write(release / filename, src.read_bytes(), 0o755 if filename in {"summitflow-host-monitor", "monitor-observe.pyz"} else 0o644)
    unit = (source / "scripts/systemd" / UNIT).read_text()
    unit = unit.replace("__MONITOR_RELEASE__", str(release)).replace("__MONITOR_OWNER_UID__", str(uid)).replace("__MONITOR_OWNER_GID__", str(gid))
    if "__" in unit:
        raise RuntimeError("unresolved collector service template")
    old_unit = UNIT_PATH.read_text() if UNIT_PATH.exists() else None
    if old_unit is None and STATE.exists():
        raise RuntimeError("unmanaged system monitor state already exists; inspect it before adoption")
    legacy = Path(pwd.getpwuid(uid).pw_dir) / ".local/state/summitflow/monitor"
    record = {"status": "pending", "uid": uid, "gid": gid, "source": str(source),
              "release": str(release), "previous_unit": old_unit,
              "system_enabled": _system("is-enabled", UNIT, check=False).returncode == 0,
              "system_active": _system("is-active", UNIT, check=False).returncode == 0,
              "legacy_enabled": _user(uid, gid, "is-enabled", UNIT, check=False).returncode == 0,
              "legacy_active": _user(uid, gid, "is-active", UNIT, check=False).returncode == 0,
              "legacy": str(legacy), "state_created": not STATE.exists()}
    _receipt(receipt, record)
    marker = RECEIPTS / f"{transaction}.pending"
    marker.touch(mode=0o600)
    try:
        if _user(uid, gid, "cat", UNIT, check=False).returncode == 0:
            _user(uid, gid, "disable", "--now", UNIT)
            if _user(uid, gid, "is-active", UNIT, check=False).returncode == 0:
                raise RuntimeError("legacy collector remains active")
        if old_unit is not None:
            _system("stop", UNIT)
        _directory(STATE, 0o750)
        if (STATE / "migration.interlock").exists() or (legacy / "migration.interlock").exists():
            raise RuntimeError("monitor store migration interlock requires recovery")
        if record["state_created"] and (legacy / "monitor.sqlite3").exists():
            lock = legacy / "maintenance.lock"
            fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _backup(legacy / "monitor.sqlite3", STATE / "monitor.sqlite3")
            finally:
                os.close(fd)
        _state_permissions(gid)
        _write(UNIT_PATH, unit.encode())
        _system("daemon-reload")
        _system("enable", "--now", UNIT)
        if _system("is-active", UNIT, check=False).returncode != 0:
            raise RuntimeError("system collector did not activate")
        record["status"] = "activated"
        _receipt(receipt, record)
    except Exception:
        rollback(transaction)
        raise


def rollback(transaction: str) -> None:
    receipt = RECEIPTS / f"{transaction}.json"
    if not receipt.exists():
        return
    record = json.loads(receipt.read_text())
    if record["status"] == "rolled_back":
        return
    _system("stop", UNIT, check=False)
    if _system("is-active", UNIT, check=False).returncode == 0:
        raise RuntimeError("candidate collector remains active; rollback refused")
    previous = record["previous_unit"]
    if previous is not None:
        _write(UNIT_PATH, previous.encode())
        _system("daemon-reload")
        _system("enable" if record["system_enabled"] else "disable", UNIT)
        if record["system_active"]:
            _system("start", UNIT)
    else:
        _system("disable", UNIT, check=False)
        UNIT_PATH.unlink(missing_ok=True)
        _system("daemon-reload")
        if record["state_created"] and STATE.exists():
            # Preserve candidate samples for recovery; never overwrite old owner history.
            retained = RECEIPTS / f"{transaction}.state"
            shutil.move(str(STATE), retained)
        uid, gid = record["uid"], record["gid"]
        if record["legacy_enabled"]:
            _user(uid, gid, "enable", UNIT)
        if record["legacy_active"]:
            _user(uid, gid, "start", UNIT)
    record["status"] = "rolled_back"
    record["rolled_back_at"] = time.time()
    _receipt(receipt, record)
    (RECEIPTS / f"{transaction}.pending").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "rollback", "finalize"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    parser.add_argument("--transaction", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not args.transaction.isalnum() or len(args.transaction) > 64:
        raise SystemExit("root and a valid deployment transaction are required")
    if args.action == "install":
        install(args.source, args.uid, args.gid, args.transaction)
    elif args.action == "rollback":
        rollback(args.transaction)
    else:
        receipt = RECEIPTS / f"{args.transaction}.json"
        record = json.loads(receipt.read_text())
        if record["status"] != "activated":
            raise SystemExit("collector activation is not pending completion")
        record["status"] = "complete"
        _receipt(receipt, record)
        (RECEIPTS / f"{args.transaction}.pending").unlink(missing_ok=True)
        # These are protected artifact copies, independent of application release GC.
        keep = {Path(record["release"])}
        for line in (record.get("previous_unit") or "").splitlines():
            if line.startswith("ExecStart="):
                keep.add(Path(line.removeprefix("ExecStart=").split()[0]).parent)
        for candidate in (INSTALL / "releases").iterdir():
            if candidate not in keep and not candidate.is_symlink() and candidate.is_dir() and candidate.stat().st_uid == 0:
                shutil.rmtree(candidate)


if __name__ == "__main__":
    main()
