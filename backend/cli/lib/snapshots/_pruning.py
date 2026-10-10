"""Privileged deletion confined to eligible, managed read-only snapshot leaves."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from ..workspace_paths import get_workspaces_root
from ._models import SnapshotError

# Run an isolated interpreter rather than importing user-writable modules as root.
# Directory descriptors anchor the leaf; its UUID is checked against the open
# subvolume immediately before deletion. No writable-property transition is used.
_DELETE_READONLY = r'''
import os, pathlib, re, subprocess, sys
path, store, uid, device, inode = sys.argv[1:]
uid, device, inode = int(uid), int(device), int(inode)
path, store = pathlib.Path(path), pathlib.Path(store)
assert path.is_absolute() and path.parent == store, "Not a managed leaf"
fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
for part in store.parts[1:]:
    new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    os.close(fd)
    fd = new
assert os.readlink("/proc/self/fd/" + str(fd)) == str(store), "Store changed"
leaf = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
info = os.fstat(leaf)
assert (info.st_uid, info.st_dev, info.st_ino) == (uid, device, inode), "Target identity changed"
assert info.st_ino == 256, "Not a Btrfs subvolume root"
def mount_id(descriptor):
    fields = pathlib.Path("/proc/self/fdinfo/" + str(descriptor)).read_text().splitlines()
    return next(line.split()[1] for line in fields if line.startswith("mnt_id:"))
assert mount_id(fd) == mount_id(leaf), "Target is a filesystem mount"
for line in pathlib.Path("/proc/self/mountinfo").read_text().splitlines():
    mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4])
    assert mount != str(path) and not mount.startswith(str(path) + "/"), "Target contains a mount"
os.fchdir(fd)
def btrfs(*args):
    return subprocess.run(["/usr/bin/btrfs", *args], check=True, capture_output=True,
                          text=True, pass_fds=(leaf,)).stdout.strip()
opened = "/proc/self/fd/" + str(leaf)
assert btrfs("property", "get", opened, "ro") == "ro=true", "Target is writable"
def uuid(target):
    match = re.search(r"^\s*UUID:\s*(\S+)\s*$", btrfs("subvolume", "show", target), re.M)
    assert match and match[1] != "-", "Missing Btrfs subvolume identity"
    return match[1]
identity = uuid(opened)
assert not btrfs("subvolume", "list", "-o", path.name), "Target contains nested subvolumes"
assert uuid(path.name) == identity, "Target subvolume changed"
current = os.stat(path.name, follow_symlinks=False)
assert (current.st_uid, current.st_dev, current.st_ino) == (uid, device, inode), "Target changed before deletion"
btrfs("subvolume", "delete", path.name)
'''


def delete_managed_readonly(path: Path, *, recovery_project: str | None = None) -> None:
    """Delete one eligible leaf; callers retain responsibility for policy/locks."""
    base = get_workspaces_root().absolute() / ".snapshots"
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise SnapshotError(f"Pruning target is outside the managed snapshot store: {path}") from exc
    parts = relative.parts
    def safe(value: str) -> bool:
        return bool(re.fullmatch(r"[a-zA-Z0-9._-]+", value)) and value not in {".", ".."}
    if recovery_project is not None:
        valid = len(parts) == 3 and parts[:2] == ("recoveries", recovery_project)
    else:
        valid = len(parts) == 4 and parts[0] != "recoveries" and parts[1] in {"projects", "worktrees"}
    if not valid or not all(safe(part) for part in parts):
        raise SnapshotError(f"Pruning target is not an exact managed snapshot leaf: {path}")
    _privileged_delete(path)


def delete_readonly_residue(path: Path) -> None:
    """Delete one read-only legacy residue subvolume beneath the managed store.

    Residue roots predate the exact point layout, so only containment is
    checked here; the root helper still refuses writable, nested, mounted,
    swapped or foreign-owned targets.
    """
    base = get_workspaces_root().absolute() / ".snapshots"
    target = path.absolute()
    if target == base or base not in target.parents:
        raise SnapshotError(f"Residue target is outside the managed snapshot store: {path}")
    _privileged_delete(target)


def _privileged_delete(path: Path) -> None:
    # lstat the entire path before deciding that an absent target is already clean.
    for ancestor in reversed((path, *path.parents)):
        if ancestor.is_symlink():
            raise SnapshotError(f"Pruning refuses a symlink component: {ancestor}")
    if not path.exists():
        return
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.getuid():
        raise SnapshotError(f"Pruning target is not owned by the current user: {path}")
    try:
        subprocess.run(
            ["sudo", "-n", "/usr/bin/python3", "-I", "-c", _DELETE_READONLY,
             str(path), str(path.parent), str(os.getuid()), str(info.st_dev), str(info.st_ino)],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise SnapshotError(f"Managed read-only snapshot deletion failed: {path}\n{detail}") from exc
