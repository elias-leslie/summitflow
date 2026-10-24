"""Monthly real restore of the btrbk host points on the T7; sets ``restore_verified``.

The latest ``workspaces`` and ``home`` points are received with ``btrfs send |
btrfs receive`` into a private directory on the T7 itself (the scratch disk
cannot hold a full copy of either). Each received tree must have the same file,
link and directory counts as the source's retained local snapshot of that point,
and a random sample must hash the same; sampled files unchanged since the point
must also match the live tree. The boot path must be complete: kernel, initrd
and grub.cfg of the running kernel in the capture's ``/boot`` copy, and fstab,
systemd and the running kernel's modules in the ``root`` point. The received
copies are deleted before the write window closes; only a pass sets the time
``restore_verified`` counts from.
"""

from __future__ import annotations

import fcntl
import json
import platform
import secrets
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..utils.host_retention_policy import HostRetentionPolicy
from . import backup_btrbk as host
from .backup_activity import BackupCancelled, run_bulk_process
from .backup_btrbk import NATIVE_TARGET
from .backup_offsite_restore_test import MONTHLY_CADENCE_DAYS, RESTORE_VERIFIED_DAYS
from .backup_write_window import path_window

logger = get_logger(__name__)

SUBVOLUMES = ("workspaces", "home")
RESTORE_ROOT = NATIVE_TARGET.parent / "restore-test"
SAMPLE_FILES = 48
SAMPLE_MAX_FILE_BYTES = 64 * 1024**2
METHOD = "monthly-host-restore"
# Root-side walk and hash of a received or snapshot tree. Runs as root through
# sudo because both trees hold root-only files; it reads, never writes.
_PROBE = r"""
import hashlib, json, os, random, stat, sys
mode, root = sys.argv[1], sys.argv[2]
def digest(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return [info.st_size, int(info.st_mtime), h.hexdigest()]
if mode == "count":
    sample, limit, rng = [], int(sys.argv[3]), random.Random(sys.argv[4])
    counts, seen, device = {"files": 0, "links": 0, "dirs": 0}, 0, os.lstat(root).st_dev
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    counts["dirs"] += 1
                    if info.st_dev == device:
                        stack.append(entry.path)
                elif stat.S_ISLNK(info.st_mode):
                    counts["links"] += 1
                elif stat.S_ISREG(info.st_mode):
                    counts["files"] += 1
                    if limit and info.st_size <= int(sys.argv[5]):
                        seen += 1
                        rel = os.path.relpath(entry.path, root)
                        if len(sample) < limit:
                            sample.append(rel)
                        elif (slot := rng.randrange(seen)) < limit:
                            sample[slot] = rel
    print(json.dumps({**counts, "sample": sample}))
else:
    out = {}
    for rel in sys.argv[3:]:
        try:
            out[rel] = digest(os.path.join(root, rel))
        except OSError:
            out[rel] = None
    print(json.dumps(out))
"""


def _receipt_path() -> Path:
    return host._state_root() / "restore-test.json"


def restore_receipt() -> dict[str, Any]:
    try:
        data = json.loads(_receipt_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def host_restore_status(*, now: datetime | None = None) -> dict[str, Any]:
    """``restore_verified`` is a passing real restore within one monthly cadence plus slack."""
    receipt = restore_receipt()
    tested = receipt.get("completed_at")
    passed = receipt.get("status") == "verified" and tested
    verified = bool(passed) and (now or datetime.now(UTC)) - datetime.fromisoformat(str(tested)) <= timedelta(days=RESTORE_VERIFIED_DAYS)
    return {"restore_verified": verified, "restore_tested_at": tested, "restore_test_result": receipt.get("status"),
            "restore_test_error": receipt.get("error")}


def _probe(*args: str, bulk: bool = False) -> dict[str, Any]:
    command = ["sudo", "-n", "/usr/bin/python3", "-I", "-c", _PROBE, *args]
    output = host._checked(command, bulk=bulk)
    return json.loads(output)


def _latest_point(name: str) -> Path:
    points = sorted(Path(path) for path in host._native_listing(NATIVE_TARGET, "target") if Path(path).name.startswith(f"{name}."))
    if not points:
        raise RuntimeError(f"No {name} point on the T7")
    return points[-1]


def _compare(name: str, row: dict[str, str], run: Path, seed: str) -> dict[str, Any]:
    point = _latest_point(name)
    local = Path(row["snapshot_path"]) / point.name
    live = Path(row["source_url"])
    used = shutil.disk_usage(live).used
    reserve = int(HostRetentionPolicy.from_env().pressure_min_free_gb * 1024**3)
    if shutil.disk_usage(NATIVE_TARGET).free - used < reserve:
        raise RuntimeError(f"T7 lacks room to receive {name} ({used} bytes) above the {reserve}-byte reserve")
    started = time.monotonic()
    # pipefail: a failed send must not pass as an empty but successful receive.
    run_bulk_process(["sudo", "-n", "/bin/bash", "-c", 'set -o pipefail; btrfs send -q "$1" | btrfs receive "$2"',
                      "restore", str(point), str(run)], phase="host_restore_test", object_name=name)
    received = run / point.name
    if host._run(["sudo", "-n", "test", "-d", str(received)]).returncode:
        raise RuntimeError(f"btrfs receive produced no {name} tree")
    receive_seconds = round(time.monotonic() - started)
    restored = _probe("count", str(received), str(SAMPLE_FILES), seed, str(SAMPLE_MAX_FILE_BYTES), bulk=True)
    source = _probe("count", str(local), "0", seed, "0", bulk=True)
    current = _probe("count", str(live), "0", seed, "0", bulk=True)
    sample = restored.pop("sample")
    source.pop("sample")
    current.pop("sample")
    hashes = {label: _probe("hash", str(root), *sample) for label, root in (("restored", received), ("source", local), ("live", live))}
    matched = [rel for rel in sample if hashes["restored"][rel] and hashes["restored"][rel] == hashes["source"][rel]]
    # A live file with the point's size and mtime must still hold the point's bytes.
    unchanged = [rel for rel in sample if hashes["live"][rel] and hashes["source"][rel]
                 and hashes["live"][rel][:2] == hashes["source"][rel][:2]]
    live_matched = [rel for rel in unchanged if hashes["live"][rel] == hashes["restored"][rel]]
    result = {"point": str(point), "local_snapshot": str(local), "receive_seconds": receive_seconds,
              "restored": restored, "source": source, "live": current, "sample": len(sample),
              "sample_matched": len(matched), "live_compared": len(unchanged), "live_matched": len(live_matched)}
    problems = []
    if restored != source:
        problems.append(f"counts differ from the source snapshot ({restored} vs {source})")
    if not sample or len(matched) != len(sample):
        problems.append(f"{len(sample) - len(matched)} of {len(sample)} sampled files differ from the source snapshot")
    if len(live_matched) != len(unchanged):
        problems.append(f"{len(unchanged) - len(live_matched)} unchanged live files differ from the restore")
    result["ok"] = not problems
    if problems:
        result["error"] = "; ".join(problems)
    return result


def _boot_path() -> dict[str, Any]:
    kernel = platform.release()
    root_point = _latest_point("root")
    last_good = json.loads((host._state_root() / "last-good.json").read_text())
    boot = Path(last_good["boot_path"])
    point_files = ["etc/fstab", "usr/lib/systemd/systemd", f"usr/lib/modules/{kernel}/modules.dep"]
    boot_files = [f"vmlinuz-{kernel}", f"initrd.img-{kernel}", "grub/grub.cfg"]
    in_point = _probe("hash", str(root_point), *point_files)
    in_boot = _probe("hash", str(boot), *boot_files)
    live_boot = _probe("hash", "/boot", *boot_files)
    missing = [f"root:{rel}" for rel, value in in_point.items() if not value] + [f"boot:{rel}" for rel, value in in_boot.items() if not value]
    # The kernel image never changes in place; a differing copy is a bad copy.
    kernel_ok = bool(in_boot[f"vmlinuz-{kernel}"]) and in_boot[f"vmlinuz-{kernel}"] == live_boot[f"vmlinuz-{kernel}"]
    return {"kernel": kernel, "root_point": str(root_point), "boot_copy": str(boot), "missing": missing,
            "kernel_matches_live": kernel_ok, "ok": not missing and kernel_ok}


def _delete_received(run: Path, *, remove_run: bool = False) -> list[str]:
    """Delete received trees (one at a time stays on the T7), then the run directory when asked."""
    errors = []
    listing = host._run(["sudo", "-n", "find", str(run), "-mindepth", "1", "-maxdepth", "1", "-type", "d"])
    for child in listing.stdout.split():
        result = host._run(["sudo", "-n", "btrfs", "subvolume", "delete", "--commit-after", child])
        if result.returncode:
            errors.append(f"{child}: {result.stderr.strip()[:200]}")
    if remove_run and not errors and host._run(["sudo", "-n", "rmdir", str(run)]).returncode:
        errors.append(f"{run}: not empty after delete")
    return errors


def run_host_restore_test(*, force: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """Run the monthly host restore unless a pass is inside the cadence; failures retry next week."""
    now = now or datetime.now(UTC)
    previous = restore_receipt()
    last = previous.get("completed_at")
    if not force and previous.get("status") == "verified" and last and datetime.fromisoformat(last) > now - timedelta(days=MONTHLY_CADENCE_DAYS):
        return {"status": "skipped", "reason": "monthly-cadence", "last_completed_at": last}
    root = host._state_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "host-backup-active"}
        stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
        run = RESTORE_ROOT / stamp
        receipt: dict[str, Any] = {"method": METHOD, "run_id": stamp, "started_at": now.isoformat(), "subvolumes": {}}
        with path_window(NATIVE_TARGET):
            try:
                rows = {row["snapshot_name"]: row for row in host._configuration()}
                host._checked(["sudo", "-n", "mkdir", "-p", "-m", "700", str(run)])
                for name in SUBVOLUMES:
                    result = receipt["subvolumes"][name] = _compare(name, rows[name], run, stamp)
                    if cleanup := _delete_received(run):
                        result.update(ok=False, error=f"cleanup failed: {cleanup}")
                receipt["boot"] = _boot_path()
                checks = {**receipt["subvolumes"], "boot": receipt["boot"]}
                errors = [f"{name}: {item.get('error') or 'boot path incomplete'}" for name, item in checks.items() if not item["ok"]]
                receipt["status"] = "failed" if errors else "verified"
                if errors:
                    receipt["error"] = "; ".join(errors)
            except BackupCancelled:
                receipt.update(status="cancelled")
                raise
            except Exception as exc:
                logger.exception("host_restore_test_failed")
                receipt.update(status="failed", error=str(exc)[:500])
            finally:
                leftover = _delete_received(run, remove_run=True) if host._run(["sudo", "-n", "test", "-e", str(run)]).returncode == 0 else []
                if leftover:
                    receipt.update(status="failed", cleanup_errors=leftover)
                receipt["completed_at"] = datetime.now(UTC).isoformat()
                host._write_json(_receipt_path(), receipt)
        logger.info("host_restore_test_completed", status=receipt["status"], error=receipt.get("error"))
        return receipt

