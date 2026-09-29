"""Standalone recovery arguments and read-only inventory, using local fixtures."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RECOVER = ROOT / "scripts" / "backup-repository-recover.sh"
INVENTORY = ROOT / "scripts" / "backup-cleanup-inventory.py"


@pytest.fixture
def tools(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path]:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "calls.jsonl"
    for executable in ("restic", "rclone"):
        binary = binaries / executable
        binary.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, shutil, sys\n"
            "name = pathlib.Path(sys.argv[0]).name\n"
            "if sys.argv[1:] == ['version']:\n"
            "    print(os.environ.get('FAKE_'+name.upper()+'_VERSION', 'restic 0.19.1 compiled with go' if name == 'restic' else 'rclone v1.75.1'))\n"
            "    raise SystemExit(0)\n"
            "with open(os.environ['FAKE_CALL_LOG'], 'a') as output:\n"
            "    output.write(json.dumps({'args':sys.argv[1:], 'config':os.environ.get('RCLONE_CONFIG'), 'inline_password_present':'RESTIC_PASSWORD' in os.environ, 'inline_token_present':'RCLONE_CONFIG_DRIVE_TOKEN' in os.environ, 'backend_override_present':'RCLONE_DRIVE_ROOT_FOLDER_ID' in os.environ, 'cache_override_present':'RESTIC_CACHE_DIR' in os.environ})+'\\n')\n"
            "if os.environ.get('FAKE_FAILURE'):\n"
            "    raise SystemExit(17)\n"
            "if 'restore' in sys.argv:\n"
            "    target = pathlib.Path(sys.argv[sys.argv.index('--target')+1])\n"
            "    if os.environ.get('FAKE_SOURCE'):\n"
            "        shutil.copytree(os.environ['FAKE_SOURCE'], target/'project')\n"
            "if 'snapshots' in sys.argv:\n"
            "    print('[]')\n"
        )
        binary.chmod(0o700)
    password = tmp_path / "password.ref"
    password.write_text("fixture-do-not-print\n")
    password.chmod(0o600)
    config = tmp_path / "rclone.ref"
    config.write_text("fixture-do-not-print\n")
    config.chmod(0o600)
    repository = tmp_path / "repository"
    repository.mkdir()
    env = {
        **os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "FAKE_CALL_LOG": str(log),
        "RESTIC_PASSWORD": "fixture-inline-secret", "RCLONE_CONFIG_DRIVE_TOKEN": "fixture-inline-secret",
        "RCLONE_DRIVE_ROOT_FOLDER_ID": "fixture-unapproved-root", "RESTIC_CACHE_DIR": "fixture-unapproved-cache",
    }
    return env, password, config, repository


def run_recovery(tools, mode: str, *extra: str, remote: bool = False):
    env, password, config, repository = tools
    arguments = ["bash", str(RECOVER), mode, "--repository", "rclone:drive:bounded/repository" if remote else str(repository), "--password-file", str(password)]
    if remote:
        arguments += ["--rclone-config", str(config)]
    return subprocess.run([*arguments, *extra], env=env, capture_output=True, text=True, check=False)


def calls(tools) -> list[dict]:
    path = Path(tools[0]["FAKE_CALL_LOG"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_snapshots_uses_private_file_refs_source_filter_and_clears_inline_secrets(tools) -> None:
    result = run_recovery(tools, "snapshots", "--source", "codex-config", remote=True)
    assert result.returncode == 0, result.stderr
    call = calls(tools)[0]
    assert call["args"][-4:] == ["snapshots", "--json", "--tag", "source:codex-config"]
    assert call["config"] == str(tools[2])
    assert call["inline_password_present"] is False
    assert call["inline_token_present"] is False
    assert call["backend_override_present"] is False
    assert call["cache_override_present"] is False
    assert "fixture-do-not-print" not in result.stdout + result.stderr


@pytest.mark.parametrize("source_id", [".codex", ".claude"])
def test_snapshots_accepts_actual_dot_prefixed_source_ids(tools, source_id: str) -> None:
    result = run_recovery(tools, "snapshots", "--source", source_id, remote=True)
    assert result.returncode == 0, result.stderr
    assert calls(tools)[0]["args"][-2:] == ["--tag", f"source:{source_id}"]


def test_deterministic_check_subset_and_restore_verify_args(tools, tmp_path: Path) -> None:
    check = run_recovery(tools, "check", "--read-data-subset", "3/30")
    assert check.returncode == 0, check.stderr
    assert calls(tools)[0]["args"][-2:] == ["check", "--read-data-subset=3/30"]
    destination = tmp_path / "restore"
    restore = run_recovery(tools, "restore", "--snapshot", "a" * 64, "--into", str(destination), "--verify")
    assert restore.returncode == 0, restore.stderr
    assert calls(tools)[1]["args"][-5:] == ["restore", "a" * 64, "--target", str(destination), "--verify"]
    assert destination.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("invalid", ["no-verify", "latest", "nonempty", "symlink", "public", "version"])
def test_restore_refuses_unsafe_inputs_before_repository_operation(tools, tmp_path: Path, invalid: str) -> None:
    destination = tmp_path / "restore"
    snapshot = "a" * 64
    options = ["--verify"]
    if invalid == "no-verify":
        options = []
    elif invalid == "latest":
        snapshot = "latest"
    elif invalid == "nonempty":
        destination.mkdir(mode=0o700)
        (destination / "sentinel").write_text("preserve")
    elif invalid == "symlink":
        actual = tmp_path / "actual"
        actual.mkdir(mode=0o700)
        destination.symlink_to(actual)
    elif invalid == "public":
        destination.mkdir(mode=0o755)
    else:
        tools[0]["FAKE_RESTIC_VERSION"] = "restic 0.18.0 compiled with go"
    result = run_recovery(tools, "restore", "--snapshot", snapshot, "--into", str(destination), *options)
    assert result.returncode != 0
    assert calls(tools) == []
    if invalid == "nonempty":
        assert (destination / "sentinel").read_text() == "preserve"


@pytest.mark.parametrize("repository", ["rclone:drive:", "rclone:drive:../outside", "rclone:drive:folder/../outside", "rclone:drive:/"])
def test_remote_root_and_traversal_are_refused(tools, repository: str) -> None:
    env, password, config, _ = tools
    result = subprocess.run(["bash", str(RECOVER), "snapshots", "--repository", repository, "--password-file", str(password), "--rclone-config", str(config)], env=env, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert calls(tools) == []


def test_repository_failure_is_propagated(tools) -> None:
    tools[0]["FAKE_FAILURE"] = "1"
    assert run_recovery(tools, "check").returncode == 17


@pytest.mark.parametrize("invalid", ["public-password", "linked-config", "rclone-version"])
def test_private_credential_references_and_rclone_pin_are_required(tools, tmp_path: Path, invalid: str) -> None:
    if invalid == "public-password":
        tools[1].chmod(0o644)
    elif invalid == "linked-config":
        original = tmp_path / "original-config"
        tools[2].rename(original)
        tools[2].symlink_to(original)
    else:
        tools[0]["FAKE_RCLONE_VERSION"] = "rclone v1.74.0"
    result = run_recovery(tools, "snapshots", remote=True)
    assert result.returncode != 0
    assert calls(tools) == []


def test_standard_git_recovery_restores_exact_index_and_wip_without_backend_import(tools, tmp_path: Path) -> None:
    from app.tasks import backup_native_archive, backup_native_recovery
    from tests.tasks.test_backup_native_recovery import _git

    project = tmp_path / "source"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "file.txt").write_text("base")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "base")
    (project / "file.txt").write_text("staged")
    _git(project, "add", ".")
    (project / "file.txt").write_text("working")
    snapshot, _ = backup_native_recovery.build_consistent_snapshot(project, tmp_path / "stage", (".git",), backup_native_archive._should_exclude)
    tools[0]["FAKE_SOURCE"] = str(snapshot)
    tools[0]["GIT_DIR"] = str(project / ".git")
    destination = tmp_path / "restored"
    result = run_recovery(tools, "restore", "--snapshot", "a" * 64, "--into", str(destination), "--verify", "--git-root", "project")
    assert result.returncode == 0, result.stderr
    restored = destination / "project"
    assert (restored / "file.txt").read_text() == "working"
    assert (restored / ".git/index").read_bytes() == (project / ".git/index").read_bytes()
    assert _git(restored, "rev-parse", "HEAD") == _git(project, "rev-parse", "HEAD")
    assert "GIT_READY" in result.stdout


def test_inventory_opens_no_file_contents_skips_links_and_protects_recovery_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runpy.run_path(str(INVENTORY))
    root = tmp_path / ".codex"
    root.mkdir()
    fixtures = ["plugins/cache/download.bin", "plugins/cache/LICENSE.txt", "logs/conversation.jsonl", "sessions/transcript.txt", "releases/old/package.bin", "art/original.png", "state/session.db", "auth.json"]
    for fixture in fixtures:
        path = root / fixture
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"must never read contents")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "not-in-scope").write_text("must not inventory")
    (root / "linked").symlink_to(outside)
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("opened file contents"))
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: pytest.fail("read file contents"))
    original_open = os.open

    def directories_only(path, flags, **kwargs):
        assert flags & os.O_DIRECTORY and flags & os.O_NOFOLLOW
        return original_open(path, flags, **kwargs)

    monkeypatch.setattr(os, "open", directories_only)
    report = module["inventory"]([root], protected_paths=[], older_than_days=30, max_entries=1000)
    indexed = {entry["path"]: entry for entry in report["entries"]}
    assert report["read_only"] is True
    assert report["complete"] is True
    assert indexed["plugins/cache/download.bin"]["category"] == "review-generated"
    assert indexed["plugins/cache/LICENSE.txt"]["category"] == "protected-recovery"
    assert indexed["logs/conversation.jsonl"]["category"] == "protected-recovery"
    assert indexed["art/original.png"]["category"] == "protected-recovery"
    assert indexed["state/session.db"]["category"] == "protected-recovery"
    assert indexed["linked"]["category"] == "link-skipped"
    assert indexed["auth.json"]["category"] == "sensitive-skipped"
    assert "linked/not-in-scope" not in indexed


def test_inventory_counts_hardlinks_once_and_marks_bounded_traversal_incomplete(tmp_path: Path) -> None:
    module = runpy.run_path(str(INVENTORY))
    root = tmp_path / ".claude"
    root.mkdir()
    file = root / "first.bin"
    file.write_bytes(b"content" * 1024)
    os.link(file, root / "second.bin")
    full = module["inventory"]([root], protected_paths=[], older_than_days=0, max_entries=100)
    files = [entry for entry in full["entries"] if entry.get("kind") == "file"]
    assert sum(entry["allocated_bytes"] for entry in files) == file.stat().st_blocks * 512
    assert files[1]["hardlink_already_counted"] is True
    partial = module["inventory"]([root], protected_paths=[], older_than_days=0, max_entries=1)
    assert partial["complete"] is False
    assert partial["truncated"] is True


def test_inventory_cli_rejects_broad_and_symlink_roots(tmp_path: Path) -> None:
    for path in (tmp_path, tmp_path / ".codex"):
        if path.name == ".codex":
            path.symlink_to(tmp_path)
        result = subprocess.run(["python3", str(INVENTORY), "--root", str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 2


def test_inventory_cli_truncated_report_exits_nonzero_without_modifying_files(tmp_path: Path) -> None:
    root = tmp_path / ".claude"
    root.mkdir()
    (root / "retained.txt").write_text("unchanged")
    result = subprocess.run(["python3", str(INVENTORY), "--root", str(root), "--max-entries", "1"], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert json.loads(result.stdout)["complete"] is False
    assert (root / "retained.txt").read_text() == "unchanged"


def test_inventory_cli_accepts_actual_aftertimes_project_name(tmp_path: Path) -> None:
    root = tmp_path / "the-aftertimes"
    root.mkdir()
    (root / "LICENSE.txt").write_text("retained")
    result = subprocess.run(["python3", str(INVENTORY), "--root", str(root)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["complete"] is True
    assert next(entry for entry in report["entries"] if entry["path"] == "LICENSE.txt")["category"] == "protected-recovery"


def test_inventory_protects_explicit_active_release(tmp_path: Path) -> None:
    module = runpy.run_path(str(INVENTORY))
    root = tmp_path / "AfterTimes"
    active = root / "releases" / "active"
    active.mkdir(parents=True)
    (active / "package.bin").write_bytes(b"retained")
    report = module["inventory"]([root], protected_paths=[active], older_than_days=30, max_entries=100)
    entry = next(entry for entry in report["entries"] if entry["path"] == "releases/active/package.bin")
    assert entry["category"] == "protected-recovery"
