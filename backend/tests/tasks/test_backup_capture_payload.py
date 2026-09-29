"""Staged capture contracts shared by encrypted archives and repository adapters."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

from app.tasks import backup_native_archive as archive
from app.tasks import backup_native_recovery as recovery
from tests.tasks.test_backup_native_recovery import _git


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "base.txt").write_text("base\n")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "base")
    (project / "base.txt").write_text("staged\n")
    _git(project, "add", ".")
    (project / "base.txt").write_text("working\n")
    return project


def test_project_payload_is_plain_materialized_tree_and_legacy_packs_gzip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "note.txt").write_text("recoverable\n")
    sql = b"-- PostgreSQL database dump\nSELECT 1;\n"

    def dump(_name, path, _env):
        assert path.name == "database.sql"
        path.write_bytes(sql)
        return len(sql), True

    monkeypatch.setattr(archive, "_dump_database", dump)
    payload = archive.prepare_project_payload(project, "fixture", tmp_path / "stage", {})
    snapshot = payload["snapshot_dir"]
    assert (snapshot / "database.sql").read_bytes() == sql
    assert not (snapshot / "database.sql.gz").exists()
    assert payload["db_bytes"] == len(sql)
    assert payload["total_bytes"] == sum(path.stat().st_size for path in snapshot.rglob("*") if path.is_file())
    assert payload["logical_bytes"] == payload["total_bytes"]
    assert payload["verification"]["verified"] is True
    assert payload["verification"]["has_db"] is True
    assert "checksum" not in payload["verification"]

    legacy = archive._create_project_archive(project, "fixture", tmp_path / "legacy-stage", {})
    with tarfile.open(legacy["archive_path"], "r:gz") as packed:
        database = packed.extractfile("fixture/database.sql.gz")
        assert database is not None
        assert gzip.decompress(database.read()) == sql
        assert "fixture/database.sql" not in packed.getnames()
    assert legacy["verification"]["verified"] is True


def test_explicit_file_source_never_walks_parent_or_dumps_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / ".claude.json"
    source.write_text('{"fixture": true}\n')
    (tmp_path / "unrelated.txt").write_text("must not capture")
    monkeypatch.setattr(archive, "_dump_database", lambda *_args: pytest.fail("file source dumped a database"))
    payload = archive.prepare_project_payload(source, "claude-root-config", tmp_path / "stage", {})
    assert (payload["snapshot_dir"] / ".claude.json").read_bytes() == source.read_bytes()
    assert not (payload["snapshot_dir"] / "unrelated.txt").exists()
    assert payload["recovery"]["source_kind"] == "file"
    assert payload["recovery"]["file_name"] == ".claude.json"
    assert payload["db_bytes"] == 0


def test_original_root_sql_asset_is_preserved_alongside_generated_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    original = b"-- original project asset\n"
    database = b"-- generated PostgreSQL dump\n"
    (project / "database.sql").write_bytes(original)

    def dump(_name, path, _env):
        path.write_bytes(database)
        return len(database), True

    monkeypatch.setattr(archive, "_dump_database", dump)
    payload = archive.prepare_project_payload(project, "fixture", tmp_path / "stage", {})
    assert (payload["snapshot_dir"] / "database.sql").read_bytes() == original
    assert (payload["snapshot_dir"] / payload["db_dump_name"]).read_bytes() == database
    assert payload["db_dump_name"] == ".summitflow-recovery/database.sql"
    packed = archive._create_project_archive(project, "fixture", tmp_path / "legacy", {})
    with tarfile.open(packed["archive_path"], "r:gz") as output:
        asset = output.extractfile("fixture/database.sql")
        assert asset is not None
        assert asset.read() == original
        dumped = output.extractfile("fixture/database.sql.gz")
        assert dumped is not None
        assert gzip.decompress(dumped.read()) == database


@pytest.mark.parametrize("target_kind", ["directory", "file"])
def test_root_symlinks_are_rejected_before_reading_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_kind: str,
) -> None:
    target = tmp_path / "target"
    target.mkdir() if target_kind == "directory" else target.write_text("content")
    source = tmp_path / "link"
    source.symlink_to(target)
    monkeypatch.setattr(archive, "_load_excludes", lambda *_args: pytest.fail("read through root symlink"))
    with pytest.raises(RuntimeError, match="explicit regular file"):
        archive.prepare_project_payload(source, "fixture", tmp_path / "stage", {})


def test_explicit_file_rejects_same_metadata_content_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / ".claude.json"
    source.write_bytes(b"original")
    initial = source.stat()
    original_copy = recovery.copy_inventory_snapshot

    def copy_then_rewrite(*args):
        original_copy(*args)
        source.write_bytes(b"modified")
        os.utime(source, ns=(initial.st_atime_ns, initial.st_mtime_ns))

    monkeypatch.setattr(recovery, "copy_inventory_snapshot", copy_then_rewrite)
    with pytest.raises(RuntimeError, match="changed during capture"):
        archive.prepare_project_payload(source, "fixture", tmp_path / "stage", {})


def test_registered_external_links_are_manifest_only_and_restore_inside_isolation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("capture")
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "SKILL.md").write_text("skill")
    (source / "skills").symlink_to(canonical)
    (source / "unregistered").symlink_to(tmp_path / "unregistered-target")
    snapshot, manifest = recovery.build_consistent_snapshot(
        source, tmp_path / "stage", (), lambda *_args: False,
        source_roots={"agent-skills": canonical},
    )
    assert manifest["mapped_links"] == [{"path": "skills", "target_source": "agent-skills", "target_relative_path": "."}]
    assert not (snapshot / "skills").is_symlink()
    assert not (snapshot / "unregistered").is_symlink()
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    restored = isolated / "config"
    shutil.copytree(snapshot, restored)
    destination = isolated / "agent-skills"
    shutil.copytree(canonical, destination)
    result = recovery.restore_mapped_links(restored, destination_roots={"agent-skills": destination}, isolated_root=isolated)
    assert result == {"mapped_links_restored": 1, "mapped_links_pending": []}
    assert (restored / "skills").is_symlink()
    assert (restored / "skills").resolve() == destination
    assert not Path(os.readlink(restored / "skills")).is_absolute()


def test_existing_stale_canonical_link_is_pending_without_losing_valid_links(tmp_path: Path) -> None:
    from app.tasks import backup_executor as executor

    isolated = tmp_path / "isolated"
    project = isolated / "claude-config"
    target = isolated / "agent-skills"
    (project / recovery.RECOVERY_DIR_NAME).mkdir(parents=True)
    (target / recovery.RECOVERY_DIR_NAME).mkdir(parents=True)
    (target / "SKILL.md").write_text("recovered")
    (target / recovery.RECOVERY_DIR_NAME / recovery.RECOVERY_MANIFEST_NAME).write_text("{}")
    mappings = [
        {"path": "skills", "target_source": "agent-skills", "target_relative_path": "."},
        {"path": "commands/stale.md", "target_source": "agent-skills", "target_relative_path": "commands/stale.md"},
    ]
    (project / recovery.RECOVERY_DIR_NAME / recovery.RECOVERY_MANIFEST_NAME).write_text(
        json.dumps({"mapped_links_version": 1, "mapped_links": mappings})
    )

    result = executor._complete_mapped_recovery(project, {"agent-skills": target})

    assert result == {"mapped_links_restored": 1, "mapped_links_pending": [mappings[1]], "recovery_complete": False}
    assert (project / "skills").is_symlink()
    assert (project / "skills" / "SKILL.md").read_text() == "recovered"
    assert not (project / "commands" / "stale.md").exists()


def test_mapped_link_restore_rejects_symlink_target_outside_isolation(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    project = isolated / "claude-config"
    target = isolated / "agent-skills"
    (project / recovery.RECOVERY_DIR_NAME).mkdir(parents=True)
    target.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (target / "outside.txt").symlink_to(outside)
    (project / recovery.RECOVERY_DIR_NAME / recovery.RECOVERY_MANIFEST_NAME).write_text(
        json.dumps({"mapped_links_version": 1, "mapped_links": [
            {"path": "linked", "target_source": "agent-skills", "target_relative_path": "outside.txt"},
        ]})
    )

    with pytest.raises(RuntimeError, match="escape"):
        recovery.restore_mapped_links(project, destination_roots={"agent-skills": target}, isolated_root=isolated)
    assert not (project / "linked").is_symlink()


def test_sensitive_targets_are_not_registered_as_links(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("capture")
    canonical = tmp_path / "canonical"
    private = canonical / "private"
    private.mkdir(parents=True)
    (source / "private").symlink_to(private)
    _, manifest = recovery.build_consistent_snapshot(
        source, tmp_path / "stage", (), lambda *_args: False, (private,),
        source_roots={"canonical": canonical},
    )
    assert manifest["mapped_links"] == []


@pytest.mark.parametrize("invalid", ["traversal", "outside", "missing", "version"])
def test_mapped_link_restore_rejects_invalid_mapping_before_creating_link(tmp_path: Path, invalid: str) -> None:
    isolated = tmp_path / "isolated"
    project = isolated / "config"
    recovery_dir = project / recovery.RECOVERY_DIR_NAME
    recovery_dir.mkdir(parents=True)
    target = isolated / "skills"
    target.mkdir()
    mapping = {"path": "skills", "target_source": "skills", "target_relative_path": "."}
    manifest = {"mapped_links_version": 1, "mapped_links": [mapping]}
    if invalid == "traversal":
        mapping["path"] = "../escape"
    elif invalid == "outside":
        target = tmp_path / "outside"
        target.mkdir()
    elif invalid == "missing":
        target = isolated / "missing"
    else:
        manifest["mapped_links_version"] = 2
    (recovery_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises((RuntimeError, FileNotFoundError)):
        recovery.restore_mapped_links(project, destination_roots={"skills": target}, isolated_root=isolated)
    assert not (project / "skills").is_symlink()


def test_git_bundle_and_manifest_are_deterministic_and_verified_bundle_can_be_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    first, first_manifest = recovery.build_consistent_snapshot(project, tmp_path / "first", (".git",), archive._should_exclude)
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-09-29T20:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-09-29T20:00:00+00:00")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Environment must not change recovery identity")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "different@example.invalid")
    second, second_manifest = recovery.build_consistent_snapshot(project, tmp_path / "second", (".git",), archive._should_exclude)
    assert first_manifest == second_manifest
    assert (first / recovery.RECOVERY_DIR_NAME / "git.bundle").read_bytes() == (second / recovery.RECOVERY_DIR_NAME / "git.bundle").read_bytes()
    monkeypatch.setattr(recovery, "_create_git_bundle", lambda *_args: pytest.fail("fresh bundle created despite valid reuse"))
    reused, _ = recovery.build_consistent_snapshot(
        project, tmp_path / "reused", (".git",), archive._should_exclude,
        git_bundle_reuse={"bundle_path": first / recovery.RECOVERY_DIR_NAME / "git.bundle", "git": first_manifest["git"]},
    )
    assert (reused / recovery.RECOVERY_DIR_NAME / "git.bundle").read_bytes() == (first / recovery.RECOVERY_DIR_NAME / "git.bundle").read_bytes()
    assert (reused / recovery.RECOVERY_DIR_NAME / "git-index").read_bytes() == (project / ".git/index").read_bytes()


@pytest.mark.parametrize("invalid", ["checksum", "refs", "object_format", "recovery_format", "git_version", "missing"])
def test_invalid_git_bundle_reuse_falls_back_to_fresh_full_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    project = _project(tmp_path)
    first, manifest = recovery.build_consistent_snapshot(project, tmp_path / "first", (".git",), archive._should_exclude)
    previous = dict(manifest["git"])
    path = first / recovery.RECOVERY_DIR_NAME / "git.bundle"
    if invalid == "checksum":
        previous["bundle_checksum"] = "sha256:invalid"
    elif invalid == "missing":
        path = tmp_path / "missing.bundle"
    else:
        previous[invalid] = [] if invalid == "refs" else "incompatible"
    original = recovery._create_git_bundle
    created = []

    def record(*args):
        created.append(True)
        original(*args)

    monkeypatch.setattr(recovery, "_create_git_bundle", record)
    recovery.build_consistent_snapshot(
        project, tmp_path / "second", (".git",), archive._should_exclude,
        git_bundle_reuse={"bundle_path": path, "git": previous},
    )
    assert created == [True]


def test_plain_database_stream_keeps_uncompressed_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import subprocess

    def run(_command, **kwargs):
        kwargs["stdout_sink"](io.BytesIO(b"-- plain SQL\n"))
        return subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(archive, "run_bulk_process", run)
    destination = tmp_path / "database.sql"
    assert archive._run_plain_stream(["fixture"], destination, env={}, timeout=1) == (0, b"")
    assert destination.read_bytes() == b"-- plain SQL\n"


def test_incremental_git_bundle_reuse_is_rejected_even_with_matching_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    parent = _git(project, "rev-parse", "HEAD")
    _git(project, "commit", "-m", "second")
    incremental = tmp_path / "incremental.bundle"
    _git(project, "bundle", "create", str(incremental), "HEAD", f"^{parent}")
    state = recovery.git_state(project)
    assert state is not None
    prior = {**state, "bundle_checksum": recovery._sha256(incremental)}
    original = recovery._create_git_bundle
    calls = []

    def record(*args):
        calls.append(True)
        original(*args)

    monkeypatch.setattr(recovery, "_create_git_bundle", record)
    snapshot, manifest = recovery.build_consistent_snapshot(
        project, tmp_path / "stage", (".git",), archive._should_exclude,
        git_bundle_reuse={"bundle_path": incremental, "git": prior},
    )
    assert calls == [True]
    assert manifest["git"]["bundle_checksum"] != prior["bundle_checksum"]
    restored = tmp_path / "restored"
    shutil.copytree(snapshot, restored)
    recovery.restore_git_recovery(restored)
    assert _git(restored, "rev-list", "--count", "HEAD") == "2"


def test_verified_bundle_reuse_still_fails_closed_on_source_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    first, manifest = recovery.build_consistent_snapshot(project, tmp_path / "first", (".git",), archive._should_exclude)
    original = recovery._reuse_git_bundle

    def reuse_then_mutate(*args):
        result = original(*args)
        assert result is True
        _git(project, "update-ref", "refs/heads/concurrent", "HEAD")
        return result

    monkeypatch.setattr(recovery, "_reuse_git_bundle", reuse_then_mutate)
    with pytest.raises(RuntimeError, match="source changed during capture"):
        recovery.build_consistent_snapshot(
            project, tmp_path / "second", (".git",), archive._should_exclude,
            git_bundle_reuse={"bundle_path": first / recovery.RECOVERY_DIR_NAME / "git.bundle", "git": manifest["git"]},
        )


def test_git_recovery_preserves_sha256_object_format(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "--object-format=sha256", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "note.txt").write_text("base")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "base")
    (project / "note.txt").write_text("staged")
    _git(project, "add", ".")
    snapshot, manifest = recovery.build_consistent_snapshot(project, tmp_path / "stage", (".git",), archive._should_exclude)
    assert manifest["git"]["object_format"] == "sha256"
    restored = tmp_path / "restored"
    shutil.copytree(snapshot, restored)
    recovery.restore_git_recovery(restored)
    assert _git(restored, "rev-parse", "--show-object-format") == "sha256"
    assert _git(restored, "rev-parse", "HEAD") == _git(project, "rev-parse", "HEAD")
    assert (restored / ".git/index").read_bytes() == (project / ".git/index").read_bytes()
