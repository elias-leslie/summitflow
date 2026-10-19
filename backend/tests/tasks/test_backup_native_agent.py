"""Cross-identity backup capture passes recovery data, never owner credentials."""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

from app.tasks import backup_native_agent as agent
from app.tasks import backup_native_archive as archive
from app.tasks import backup_native_recovery as recovery


@pytest.fixture(autouse=True)
def _configured_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent.tether, "_agent_uid", os.getuid)


def _git(project: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, text=True).stdout.strip()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Backup fixture")
    _git(project, "config", "user.email", "backup@example.invalid")
    (project / "source.txt").write_text("committed\n")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "base")
    return project


def test_owner_capture_imports_agent_history_stashes_index_and_safe_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks.backup_native_restore import restore_isolated_archive
    from app.utils import agent_jobs

    project = _project(tmp_path)
    head = _git(project, "rev-parse", "HEAD")
    _git(project, "remote", "add", "origin", "https://example.invalid/project.git")
    _git(project, "update-ref", "refs/remotes/origin/main", head)
    (project / "source.txt").write_text("stashed\n")
    _git(project, "stash", "push", "-m", "recover stash")
    stash = _git(project, "rev-parse", "refs/stash")
    (project / "source.txt").write_text("staged\n")
    _git(project, "add", "source.txt")
    (project / "source.txt").write_text("working\n")
    (project / "source.txt").chmod(0o751)
    (project / "nested").mkdir()
    (project / "nested/source-link").symlink_to("../source.txt")
    (project / "nested-link").symlink_to("nested", target_is_directory=True)
    metadata = project / ".git/st/publication/evidence.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text('{"retained":true}\n')
    requests: list[dict[str, Any]] = []
    events: list[str] = []

    def installed_job(module: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert module == agent.__name__
        assert kwargs["project"] == project
        assert "env" not in kwargs
        assert "owner-secret" not in json.dumps(payload)
        requests.append(payload)
        events.append(payload["operation"])
        # Simulate the installed trusted job already running under agent UID.
        with monkeypatch.context() as local:
            local.setattr(agent, "requires_agent_snapshot", lambda _: False)
            local.setattr(agent.tether, "_agent_uid", os.getuid)
            result = agent.run_job(payload)
            if payload["operation"] == "capture":
                handoff = agent._handoff_directory(project, payload["capture_id"])
                assert handoff.stat().st_mode & 0o777 == 0o750
                assert (handoff / agent.ARCHIVE_NAME).stat().st_mode & 0o777 == 0o640
            return result

    def dump_database(_: str, destination: Path, env: dict[str, str]) -> tuple[int, bool]:
        events.append("database")
        assert env["PGPASSWORD"] == "owner-secret"
        assert destination.parent == staging / "project-snapshot"
        assert not list((project / ".git/st/backup-capture").iterdir())
        return 0, False

    monkeypatch.setenv("PGPASSWORD", "owner-secret")
    monkeypatch.setattr(agent, "requires_agent_snapshot", lambda _: True)
    monkeypatch.setattr(agent_jobs, "run_installed_agent_job", installed_job)
    monkeypatch.setattr(archive, "_dump_database", dump_database)
    staging = tmp_path / "staging"
    staging.mkdir()
    result = archive._create_project_archive(project, "project", staging, {"PGPASSWORD": "owner-secret"})
    restored = tmp_path / "restored"
    restore_isolated_archive(Path(result["archive_path"]), restored)

    assert events == ["capture", "cleanup", "database"]
    assert result["verification"]["verified"] is True
    assert result["recovery"]["git"]["capture_mode"] == "compact"
    assert requests[0]["git_history_mode"] == "compact"
    assert "git_bundle_reuse" not in requests[0]
    assert _git(restored, "rev-parse", "HEAD") == head
    assert _git(restored, "rev-parse", "refs/stash") == stash
    assert _git(restored, "show", ":source.txt") == "staged"
    assert (restored / "source.txt").read_text() == "working\n"
    assert (restored / "source.txt").stat().st_mode & 0o777 == 0o751
    assert (restored / "nested/source-link").readlink() == Path("../source.txt")
    assert (restored / "nested-link/source-link").read_text() == "working\n"
    assert (restored / ".git/st/publication/evidence.json").read_text() == '{"retained":true}\n'


def test_direct_agent_capture_stays_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr(agent, "source_requires_agent", lambda _: True)
    monkeypatch.setattr(agent.tether, "_agent_uid", os.getuid)
    monkeypatch.setattr(agent, "capture_snapshot_as_agent", lambda *_args, **_kwargs: pytest.fail("Unexpected RPC"))
    snapshot, manifest = recovery.build_consistent_snapshot(
        project, tmp_path / "staging", (".git",), archive._should_exclude,
    )
    assert manifest["consistent"] is True
    assert (snapshot / "source.txt").read_text() == "committed\n"


def test_agent_job_preserves_explicit_full_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    head = _git(project, "rev-parse", "HEAD")
    _git(project, "remote", "add", "origin", "https://example.invalid/project.git")
    _git(project, "update-ref", "refs/remotes/origin/main", head)
    monkeypatch.setattr(agent.tether, "_agent_uid", os.getuid)
    request = {
        "operation": "capture", "project": str(project),
        "capture_id": "a594ae0a-7f1c-4257-bcd1-5d742e22b5db", "excludes": [".git"],
        "sensitive_paths": [], "source_roots": {}, "capture_git": True, "git_history_mode": "full",
    }
    try:
        result = agent.run_job(request)
        assert result["ready"] is True
        handoff = agent._handoff_directory(project, request["capture_id"])
        imported = tmp_path / "imported"
        manifest = agent._import_snapshot(handoff / agent.ARCHIVE_NAME, imported)
        assert manifest["git"]["capture_mode"] == "full"
        recovery.restore_git_recovery(imported)
        assert _git(imported, "rev-parse", "HEAD") == head
    finally:
        agent.run_job({**request, "operation": "cleanup"})


def test_failed_agent_job_cannot_become_successful_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.utils import agent_jobs

    project = _project(tmp_path)
    operations: list[str] = []

    def fail_job(_module: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        operations.append(payload["operation"])
        if payload["operation"] == "capture":
            assert kwargs["cancel_check"] is recovery.check_backup_cancelled
            raise RuntimeError("agent capture failed")
        return {"cleaned": True}

    monkeypatch.setattr(agent, "requires_agent_snapshot", lambda _: True)
    monkeypatch.setattr(agent_jobs, "run_installed_agent_job", fail_job)
    monkeypatch.setattr(archive, "_dump_database", lambda *_args: pytest.fail("Unexpected database capture"))
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(RuntimeError, match="agent capture failed"):
        archive._create_project_archive(project, "project", staging, {})
    assert operations == ["capture", "cleanup"]
    assert not list(staging.glob("*.tar.gz"))


@pytest.mark.parametrize("unsafe", ["escape", "symlink", "hardlink", "fifo", "duplicate", "link-parent"])
def test_import_rejects_unsafe_agent_archive(tmp_path: Path, unsafe: str) -> None:
    path = tmp_path / "handoff.tar.gz"
    with tarfile.open(path, "w:gz") as export:
        manifest = json.dumps({"consistent": True}).encode()
        member = tarfile.TarInfo("snapshot/.summitflow-recovery/manifest.json")
        member.size = len(manifest)
        export.addfile(member, io.BytesIO(manifest))
        bad = tarfile.TarInfo("snapshot/bad")
        if unsafe == "escape":
            bad.name = "snapshot/../../outside"
        elif unsafe in {"symlink", "link-parent"}:
            bad.type = tarfile.SYMTYPE
            bad.linkname = "../../outside" if unsafe == "symlink" else ".summitflow-recovery"
        elif unsafe == "hardlink":
            bad.type = tarfile.LNKTYPE
            bad.linkname = "snapshot/.summitflow-recovery/manifest.json"
        elif unsafe == "fifo":
            bad.type = tarfile.FIFOTYPE
        elif unsafe == "duplicate":
            bad.name = member.name
        export.addfile(bad)
        if unsafe == "link-parent":
            export.addfile(tarfile.TarInfo("snapshot/bad/child"))
    with pytest.raises(RuntimeError, match=r"Unsafe|duplicate|symbolic link"):
        agent._import_snapshot(path, tmp_path / "imported")
    assert not (tmp_path / "outside").exists()


def test_import_refuses_symlink_handoff_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "snapshot.tar.gz"
    archive_path.symlink_to(tmp_path / "private")
    with pytest.raises(OSError):
        agent._import_snapshot(archive_path, tmp_path / "imported")


def test_import_refuses_file_owned_by_other_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive_path = tmp_path / "snapshot.tar.gz"
    archive_path.write_text("Private owner data must not be read as agent archive")
    monkeypatch.setattr(agent.tether, "_agent_uid", lambda: os.getuid() + 1)
    with pytest.raises(RuntimeError, match="agent-owned regular archive"):
        agent._import_snapshot(archive_path, tmp_path / "imported")


def _snapshot_export(tmp_path: Path, mutate: Any = None) -> Path:
    project = _project(tmp_path)
    snapshot, _ = recovery.build_consistent_snapshot(project, tmp_path / "stage", (".git",), archive._should_exclude)
    if mutate:
        mutate(snapshot)
    exported = tmp_path / "export.tar.gz"
    with tarfile.open(exported, "w:gz") as output:
        output.add(snapshot, arcname=agent.ARCHIVE_ROOT)
    return exported


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "hook"])
def test_import_refuses_raw_root_git_metadata(tmp_path: Path, kind: str) -> None:
    def inject(snapshot: Path) -> None:
        git = snapshot / ".git"
        if kind == "file":
            git.write_text("gitdir: elsewhere\n")
        elif kind == "symlink":
            git.symlink_to("source.txt")
        else:
            git.mkdir()
            if kind == "hook":
                (git / "config").write_text("[core]\n\thooksPath = hooks\n")
                hook = git / "hooks/reference-transaction"
                hook.parent.mkdir()
                hook.write_text("#!/bin/sh\nexit 0\n")
                hook.chmod(0o755)

    exported = _snapshot_export(tmp_path, inject)
    with pytest.raises(RuntimeError, match="Git metadata"):
        agent._import_snapshot(exported, tmp_path / "imported")


def test_import_requires_current_git_recovery_manifest(tmp_path: Path) -> None:
    def omit_metadata(snapshot: Path) -> None:
        path = snapshot / recovery.RECOVERY_DIR_NAME / recovery.RECOVERY_MANIFEST_NAME
        manifest = json.loads(path.read_text())
        del manifest["st_metadata"]
        path.write_text(json.dumps(manifest))

    exported = _snapshot_export(tmp_path, omit_metadata)
    with pytest.raises(RuntimeError, match="ST recovery metadata"):
        agent._import_snapshot(exported, tmp_path / "imported")


def test_gitfile_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    os.mkfifo(project / ".git")
    context = multiprocessing.get_context("fork")
    outcome = context.Queue()

    def resolve() -> None:
        try:
            agent._handoff_directory(project, "a594ae0a-7f1c-4257-bcd1-5d742e22b5db")
        except RuntimeError:
            outcome.put("rejected")

    worker = context.Process(target=resolve)
    worker.start()
    try:
        worker.join(timeout=1)
        assert not worker.is_alive(), "FIFO Git metadata blocked backup before RPC"
        assert outcome.get(timeout=1) == "rejected"
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join()
        outcome.close()


def test_archive_scan_checks_cancellation_during_decompression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.backup_activity import BackupCancelled

    exported = _snapshot_export(tmp_path)
    monkeypatch.setattr(agent, "check_backup_cancelled", lambda: None)
    monkeypatch.setattr(archive, "check_backup_cancelled", lambda: (_ for _ in ()).throw(BackupCancelled("during read")))
    with pytest.raises(BackupCancelled, match="during read"):
        agent._import_snapshot(exported, tmp_path / "imported")


def test_large_member_copy_checks_cancellation_between_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.backup_activity import BackupCancelled

    exported = _snapshot_export(tmp_path, lambda snapshot: (snapshot / "large.dat").write_bytes(b"x" * (3 * 1024 * 1024)))
    copying = False
    original_write = archive._ScratchWriter.write

    def write_chunk(writer: Any, data: Any) -> int:
        nonlocal copying
        written = original_write(writer, data)
        if writer.destination.name == "large.dat":
            copying = True
        return written

    def cancelled() -> None:
        if copying:
            raise BackupCancelled("during member copy")

    monkeypatch.setattr(archive._ScratchWriter, "write", write_chunk)
    monkeypatch.setattr(archive, "check_backup_cancelled", cancelled)
    with pytest.raises(BackupCancelled, match="during member copy"):
        agent._import_snapshot(exported, tmp_path / "imported")
    assert not (tmp_path / "imported").exists()
