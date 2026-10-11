"""The live PreToolUse hook denies a small irreversible command set.

Regression: the destructive guard in command_guard had no live caller, so the
shared hook let ``git reset --hard``/``git clean -fd``/``rm -rf <project>``
through in checkouts shared by many agents.
"""

from __future__ import annotations

import io
import json

import pytest

from app.services import _publication_guard, publication_hook
from app.services._publication_guard import (
    evaluate_irreversible_command,
    evaluate_publication_command,
)
from app.services.command_guard import evaluate_shell_command

SHARED = "/srv/workspaces/projects/summitflow"

DENIED = [
    "git reset --hard", "git reset --hard HEAD~1", "cd backend && git reset --hard origin/main",
    "git -C /srv/workspaces/projects/summitflow reset --hard", "bash -lc 'git reset --hard'",
    "sudo git reset --hard", "git clean -fd", "git clean -f", "git clean -xdf", "git clean --force -d",
    "git checkout .", "git checkout -- .", "git checkout HEAD -- .", "git restore .",
    "git restore --worktree --source HEAD .", "git restore -- :/",
    "git stash", "git stash -u", "git stash push -m wip", "git stash save wip", "git stash drop", "git stash clear",
    "rm -rf /", "rm -rf ~", "rm -rf ~/", "rm -fr $HOME", "rm -rf /srv", "rm -rf /srv/workspaces",
    "rm -rf /srv/workspaces/projects/summitflow", "rm -r /srv/workspaces/projects/summitflow/",
    "rm -rf /srv/workspaces/projects/*", "cd /srv/workspaces/projects && rm -rf summitflow", "rm -rf .",
    "rm -rf /media/kasadis/Backups/davion-gem", "rm -rf /mnt/summitflow-native", "rm -Rf /etc",
    "/bin/rm -rf -- /home/kasadis", "echo $(git reset --hard)", "bash <<'EOF'\ngit reset --hard\nEOF",
    "cat <<'EOF' | sh\ngit clean -fd\nEOF", "ls && git stash && git pull",
]
ALLOWED = [
    "git status", "git diff", "git fetch", "git stash list", "git stash show -p", "git stash pop",
    "git restore --staged .", "git restore -- backend/app/x.py", "git checkout -- backend/app/x.py",
    "git checkout main", "git reset --soft HEAD~1", "git reset HEAD backend/x.py", "git clean -n -d",
    "git clean -nfd", "rm -rf build/", "rm -rf node_modules", "rm -f /srv/workspaces", "rm -rf $BUILD_DIR",
    "rm -rf /srv/workspaces/projects/summitflow/frontend/.next", "rm -rf /tmp/claude-1000/foo",
    "rm -rf /srv/workspaces/st-local-acceptance.hf9oW2",
    "git -C /tmp/scratch-repo reset --hard", "cd /tmp/x && git clean -fdx && git stash",
    # Soft redirects are advice elsewhere, never hook denies.
    "pytest backend/tests", "st check --quick --changed-only",
    # Quoted and heredoc data is not a command.
    "st commit -m 'never run git reset --hard or rm -rf /'",
    "git commit -m \"$(cat <<'EOF'\nStop git reset --hard and git clean -fd; rm -rf /srv\nEOF\n)\"",
    "cat > /tmp/notes.md <<'EOF'\ngit reset --hard\nrm -rf /\nEOF",
    "python3 - <<'EOF'\nprint('git stash drop')\nEOF", "echo 'git checkout .'", "rg 'git reset --hard' docs",
]


@pytest.fixture(autouse=True)
def _home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/kasadis")


@pytest.mark.parametrize("command", DENIED)
def test_irreversible_denied_in_shared_checkout(command: str) -> None:
    assert evaluate_irreversible_command(command, SHARED).blocked


@pytest.mark.parametrize("command", ALLOWED)
def test_ordinary_and_quoted_commands_allowed(command: str) -> None:
    assert not evaluate_irreversible_command(command, SHARED).blocked


@pytest.mark.parametrize("command", ["git reset --hard", "git checkout .", "git stash", "git clean -fdx"])
def test_disposable_checkout_is_exempt(command: str) -> None:
    assert not evaluate_irreversible_command(command, "/tmp/scratch-clone").blocked


def test_force_push_main_denied_everywhere() -> None:
    assert evaluate_irreversible_command("git push --force origin main", "/tmp/scratch-clone").blocked


def _run_hook(payload: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> dict:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert publication_hook.publication_hook_main() == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("payload", [
    {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}, "cwd": SHARED},
    {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "git clean -fd"]}, "cwd": SHARED},
    {"tool_name": "exec_command", "tool_input": {"cmd": "rm -rf /srv/workspaces"}, "cwd": "/tmp"},
])
def test_hook_emits_harness_deny(payload: dict, monkeypatch, capsys) -> None:
    output = _run_hook(payload, monkeypatch, capsys)["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["hookEventName"] == "PreToolUse"
    assert "\n" not in output["permissionDecisionReason"]


def test_hook_fails_open_on_irreversible_policy_error(monkeypatch, capsys) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("policy defect")

    monkeypatch.setattr(publication_hook, "evaluate_irreversible_command", boom)
    payload = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}, "cwd": SHARED}
    assert _run_hook(payload, monkeypatch, capsys) == {}
    assert _publication_guard.evaluate_irreversible_command is not boom


def test_commit_message_heredoc_mentioning_no_verify_allowed() -> None:
    command = "st commit -m \"$(cat <<'EOF'\nfix: document --no-verify misuse\nEOF\n)\""
    assert not evaluate_publication_command(command).blocked
    # A heredoc that a shell executes still counts.
    assert evaluate_publication_command("bash -c \"$(cat <<'EOF'\ngit commit --no-verify\nEOF\n)\"").blocked


def test_legacy_shell_guard_shares_protected_root_policy(tmp_path) -> None:
    decision = evaluate_shell_command("rm -rf /srv/workspaces/projects/summitflow", tmp_path)
    assert decision.blocked
    assert decision.code == "rm_protected_root"


# Host-level accidents: disks, snapshots, backups, Proxmox (also through sudo/env/bash -c/ssh).
SYSTEM_DENIED = {
    "irreversible_mkfs_ext4": ["mkfs.ext4 /dev/sda1", "mkfs.ext4 $DEV"],
    "irreversible_mkfs": ["sudo mkfs -t ext4 /dev/nvme0n1p3"],
    "irreversible_wipefs": ["wipefs -a /dev/sdb", "bash -c 'wipefs --all /dev/sda'"],
    "irreversible_blkdiscard": ["sudo blkdiscard /dev/nvme1n1"],
    "irreversible_dd_of_dev": [
        "dd if=/dev/zero of=/dev/sda bs=1M", "sudo dd if=img.iso of=/dev/disk/by-id/usb-X status=progress",
    ],
    "irreversible_parted": ["parted -s /dev/sda mklabel gpt"],
    "irreversible_sgdisk": ["sgdisk --zap-all /dev/sdb", "sgdisk -n 1:0:0 /dev/sdb"],
    "irreversible_fdisk": ["fdisk /dev/sda"],
    "irreversible_sfdisk": ["sfdisk /dev/sda < layout"],
    "irreversible_cryptsetup": ["cryptsetup luksFormat /dev/sdc", "sudo cryptsetup erase /dev/nvme0n1p2"],
    "irreversible_btrfs_subvolume_delete": [
        "btrfs subvolume delete /mnt/summitflow-native/home.20261001",
        "sudo btrfs sub del /.snapshots/12/snapshot",
        "btrfs subvolume delete /srv/.btrbk/srv.20261010",
        "cd /srv/.btrbk && btrfs subvolume delete srv.2026",
    ],
    "irreversible_restic_forget": [
        "restic -r /mnt/x forget --keep-last 1 --prune",
        "sudo env RESTIC_PASSWORD_FILE=x restic -r rclone:summitflow-drive:r forget --keep-daily 1",
    ],
    "irreversible_restic_prune": ["restic prune"],
    "irreversible_restic_key": ["restic key remove abc"],
    "irreversible_rclone_delete": ["rclone delete summitflow-drive:backups"],
    "irreversible_rclone_purge": ["rclone purge summitflow-drive:"],
    "irreversible_rclone_deletefile": ["rclone --config /x/rclone.conf deletefile gdrive:a/b"],
    "irreversible_rclone_cleanup": ["rclone cleanup summitflow-drive:"],
    "irreversible_rclone_rmdirs": ["rclone rmdirs summitflow-drive:x"],
    "irreversible_find_home_kasadis_delete": ["find ~ -delete"],
    "irreversible_find_srv_workspaces_delete": ["find /srv/workspaces -type f -delete"],
    "irreversible_find_mnt_summitflow_native_delete": ["find /mnt/summitflow-native -mtime +30 -delete"],
    "irreversible_find_srv_workspaces_projects_summitflow_delete": [
        "find /srv/workspaces/projects/summitflow -exec rm -rf {} +", "find . -type f -delete",
    ],
    "irreversible_qm_destroy": [
        "ssh proxmox-gem qm destroy 101", "ssh proxmox-gem \"bash -c 'qm destroy 9'\"",
        "ssh proxmox-gem <<'EOF'\nqm destroy 101\nEOF",
    ],
    "irreversible_pct_destroy": ["ssh root@192.168.86.39 'pct destroy 200 --purge'"],
    "irreversible_lvremove": ["ssh -p 22 -i key davion-gem lvremove -y pve/vm-101-disk-0"],
    "irreversible_vgremove": ["ssh proxmox-gem vgremove pve"],
    "irreversible_zfs_destroy": ["ssh proxmox-gem 'zfs destroy -r rpool/data'"],
    "irreversible_pvesm_free": ["ssh proxmox-gem pvesm free local-lvm:vm-101-disk-0"],
    "rm_protected_root": ["ssh proxmox-gem rm -rf /var/lib/vz", "ssh proxmox-gem 'sudo rm -rf /etc/pve/qemu-server'"],
}
SYSTEM_ALLOWED = [
    "restic snapshots", "restic -r /mnt/x check", "restic forget --dry-run --keep-last 3",
    "rclone ls summitflow-drive:", "rclone lsd summitflow-drive:", "rclone delete summitflow-drive:x --dry-run",
    "rclone delete /tmp/local", "dd if=/dev/zero of=./file bs=1M count=10",
    "dd if=/dev/sda of=/srv/scratch/disk.img", "dd if=x of=/dev/null", "find . -name x",
    "find . -name '*.pyc' -delete", "find /tmp/foo -delete", "btrfs subvolume list /",
    "btrfs subvolume delete /srv/scratch/testvol", "btrfs subvolume snapshot / /x", "qm list", "pct list",
    "ssh proxmox-gem qm list", "ssh proxmox-gem 'qm config 101'", "ssh proxmox-gem zfs list", "lvs",
    "parted -l", "parted /dev/sda print", "sgdisk -p /dev/sda", "fdisk -l", "fdisk -l /dev/sda",
    "wipefs /dev/sda", "mkfs.ext4 /srv/scratch/disk.img", "mkfs.ext4 /dev/loop5",
    "cryptsetup luksDump /dev/sda2", "cryptsetup luksFormat /srv/scratch/test.img",
    "lvremove --test pve/x", "zfs destroy -n rpool/x", "ssh host uptime", "ssh -t host",
    "st commit -m 'never run qm destroy or mkfs /dev/sda'", "echo 'restic forget'",
]


@pytest.mark.parametrize(
    ("code", "command"), [(code, command) for code, commands in SYSTEM_DENIED.items() for command in commands],
)
def test_host_level_irreversible_denied(code: str, command: str) -> None:
    decision = evaluate_irreversible_command(command, SHARED)
    assert decision.blocked
    assert decision.code == code
    assert decision.message and decision.message.startswith("BLOCKED:")


@pytest.mark.parametrize("command", SYSTEM_ALLOWED)
def test_host_level_inspection_allowed(command: str) -> None:
    assert not evaluate_irreversible_command(command, SHARED).blocked


def test_hook_denies_proxmox_destroy_over_ssh(monkeypatch, capsys) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": "ssh proxmox-gem qm destroy 101"}, "cwd": SHARED}
    output = _run_hook(payload, monkeypatch, capsys)["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "qm list" in output["permissionDecisionReason"]


def test_legacy_shell_guard_shares_host_level_policy(tmp_path) -> None:
    assert evaluate_shell_command("sudo mkfs.ext4 /dev/sdb1", tmp_path).blocked
    assert not evaluate_shell_command("dd if=/dev/zero of=./file bs=1M count=1", tmp_path).blocked
