#!/usr/bin/python3
"""Keep allocation headroom on this host's two internal Btrfs filesystems.

Only bounded data balances are performed. No files, snapshots, devices, or
redundancy profiles are deleted or changed. Installed during recovery 2026-10-07.
"""

import argparse
import fcntl
import json
import os
import re
import subprocess
from pathlib import Path

GIB = 1024**3
TRIGGER = 8 * GIB
TARGET = 12 * GIB
FILESYSTEMS = (
    ("/", "8b2fb687-0a04-4879-9978-d2bc7ea2f666"),
    ("/srv/workspaces", "d0cb8606-0932-4298-83be-267088035ab0"),
)


def command(args, timeout=60):
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout)


def usage(path):
    result = command(["btrfs", "filesystem", "usage", "-b", path])
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "cannot read filesystem usage")
    values = {}
    for label, name in (
        ("Device size", "size"),
        ("Device unallocated", "unallocated"),
        ("Device missing", "missing"),
        ("Free (statfs, df)", "free"),
    ):
        match = re.search(r"^\s*" + re.escape(label) + r":\s*(\d+)\s*$", result.stdout, re.M)
        if not match:
            raise RuntimeError("unexpected btrfs usage output for " + label)
        values[name] = int(match.group(1))
    metadata = re.findall(r"^Metadata,[^:]+: Size:(\d+), Used:(\d+)", result.stdout, re.M)
    values["metadata_size"] = sum(int(size) for size, _ in metadata)
    values["metadata_used"] = sum(int(used) for _, used in metadata)
    if not metadata:
        raise RuntimeError("missing metadata usage")
    if not 0 < values["metadata_size"] <= values["size"] or values["metadata_used"] > values["metadata_size"] or max(values["free"], values["unallocated"]) > values["size"]:
        raise RuntimeError("invalid filesystem usage measurement")
    return values


def inspect_mount(path, expected_uuid, check_only=False):
    selector = "-T" if check_only else "--mountpoint"
    result = command(["findmnt", "--json", selector, path, "--output", "TARGET,FSTYPE,UUID,OPTIONS"])
    requested = Path(os.path.realpath(path))
    try:
        mounts = json.loads(result.stdout)["filesystems"]
        if not mounts or any(not Path(mount["target"]).is_absolute() or not requested.is_relative_to(Path(mount["target"])) for mount in mounts):
            raise ValueError("invalid mount targets")
        depth = max(len(Path(mount["target"]).parts) for mount in mounts)
        deepest = [mount for mount in mounts if len(Path(mount["target"]).parts) == depth]
        real = [mount for mount in deepest if mount.get("fstype") != "autofs"]
        if len(real) != 1:
            raise ValueError("ambiguous or unmounted filesystem")
        mounted = real[0]
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError("required filesystem is not mounted at " + path) from error
    if result.returncode:
        raise RuntimeError("required filesystem is not mounted at " + path)
    if mounted.get("fstype") != "btrfs" or mounted.get("uuid") != expected_uuid:
        raise RuntimeError("unexpected filesystem at " + path)
    if "rw" not in mounted.get("options", "").split(","):
        raise RuntimeError("filesystem is read-only at " + path)


def maintain(path, expected_uuid, check_only=False):
    inspect_mount(path, expected_uuid, check_only)
    before = usage(path)
    report = {"path": path, "uuid": expected_uuid, "policy": {"trigger_bytes": TRIGGER, "target_bytes": TARGET}, "before": before, "actions": []}
    if before["missing"]:
        raise RuntimeError("a filesystem device is missing at " + path)
    if not check_only and before["unallocated"] < TRIGGER:
        show = command(["btrfs", "filesystem", "show", path])
        if show.returncode or not re.search(r"Total devices\s+1\b", show.stdout):
            raise RuntimeError("automatic reclamation requires a healthy single-device filesystem")
        status = command(["btrfs", "balance", "status", path])
        if "No balance found" not in status.stdout:
            report["deferred"] = "another balance is active or paused"
            report["warning"] = "allocation headroom below 8 GiB; reclamation deferred by another balance"
            report["after"] = before
            return report
        # Never attempt a full balance. Each pass relocates at most 16 chunks.
        for percent in (0, 25, 50, 75, 85):
            current = usage(path)
            if current["unallocated"] >= TARGET:
                break
            if percent and (current["unallocated"] < GIB or current["free"] < 15 * GIB):
                report["warning"] = "insufficient working space; manual space recovery needed"
                break
            args = ["btrfs", "balance", "start", f"-dusage={percent},limit=16", path]
            try:
                result = command(args, timeout=600)
            except subprocess.TimeoutExpired:
                # Cancel only the bounded operation started by this invocation.
                command(["btrfs", "balance", "cancel", path], timeout=120)
                report["warning"] = "bounded balance timed out and was cancelled"
                break
            report["actions"].append({"usage_percent": percent, "returncode": result.returncode})
            if result.returncode:
                report["warning"] = (result.stderr or result.stdout).strip()[-500:]
                break
    report["after"] = before if check_only else usage(path)
    if report["after"]["unallocated"] < TRIGGER:
        report.setdefault("warning", "allocation headroom below 8 GiB; inspect storage growth")
    if report["after"]["free"] < 15 * GIB:
        report.setdefault("warning", "available space below 15 GiB; inspect storage growth")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--path")
    parser.add_argument("--uuid")
    args = parser.parse_args()
    if bool(args.path) != bool(args.uuid) or (args.path and not args.check_only):
        parser.error("--path and --uuid require each other and --check-only")
    if args.path and not Path(args.path).is_absolute():
        parser.error("--path must be absolute")
    if os.geteuid() != 0:
        parser.error("must run as root")
    with open("/run/lock/summitflow-btrfs-space-guard.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"deferred": "another space guard is running"}), flush=True)
            return 0
        failed = False
        for path, expected_uuid in ((args.path, args.uuid),) if args.path else FILESYSTEMS:
            try:
                report = maintain(path, expected_uuid, args.check_only)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                report = {"path": path, "uuid": expected_uuid, "error": str(error)}
            print(json.dumps(report, sort_keys=True), flush=True)
            failed |= "warning" in report or "error" in report or "deferred" in report
        return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
