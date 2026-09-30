"""Compact recovery keeps original unpublished Git objects without old history."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.tasks import backup_native_archive as archive
from app.tasks import backup_native_recovery as recovery
from tests.tasks.test_backup_native_recovery import _git


def _commit(project: Path, name: str, value: str) -> str:
    (project / name).write_text(value)
    _git(project, "add", name)
    _git(project, "commit", "-m", value)
    return _git(project, "rev-parse", "HEAD")


def _project(tmp_path: Path, *, object_format: str = "sha1") -> tuple[Path, str, str]:
    project = tmp_path / "source"
    project.mkdir()
    _git(project, "init", "-b", "main", f"--object-format={object_format}")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    old = _commit(project, "old", "obsolete published asset")
    _git(project, "rm", "old")
    _git(project, "commit", "-m", "published baseline")
    baseline = _commit(project, "note", "published current tree")
    _git(project, "remote", "add", "origin", "https://example.invalid/repository.git")
    _git(project, "update-ref", "refs/remotes/origin/main", baseline)
    return project, old, baseline


def _metadata(project: Path) -> dict[str, str]:
    return {path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in (project / ".git").rglob("*") if path.is_file()}


def _metadata_times(project: Path) -> dict[str, tuple[int, int]]:
    return {path.relative_to(project).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns) for path in (project / ".git").rglob("*") if path.is_file()}


def _snapshot(project: Path, tmp_path: Path, *, mode: str = "compact", reuse: dict | None = None):
    return recovery.build_consistent_snapshot(project, tmp_path, (".git",), archive._should_exclude, git_history_mode=mode, git_bundle_reuse=reuse)


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_compact_retains_all_unpublished_branches_stashes_index_and_tree_without_source_writes(tmp_path: Path, object_format: str) -> None:
    project, old, baseline = _project(tmp_path, object_format=object_format)
    _git(project, "checkout", "-b", "unpublished-side")
    side = _commit(project, "side", "unpublished side branch")
    _git(project, "tag", "-a", "local-tag", "-m", "unpublished annotated tag")
    _git(project, "checkout", "main")
    head = _commit(project, "note", "unpublished main")
    for value in (() if object_format == "sha256" else ("older stash", "newer stash")):
        (project / "note").write_text(value)
        _git(project, "stash", "push", "-m", value)
    stashes = _git(project, "stash", "list", "--format=%H %gs")
    (project / "note").write_text("staged")
    _git(project, "add", "note")
    (project / "note").write_text("unstaged")
    (project / "unique-untracked").write_text("unique work")
    status = _git(project, "status", "--porcelain=v1")
    original_metadata = _metadata(project)
    snapshot, manifest = _snapshot(project, tmp_path / "stage")
    assert _metadata(project) == original_metadata
    assert manifest["git"]["capture_mode"] == "compact"
    assert manifest["git"]["recovery_format"] == 2
    assert baseline in manifest["git"]["shallow_commits"]
    restored = tmp_path / "restored"
    shutil.copytree(snapshot, restored)
    # Recovery has no source alternates, reachable historical objects or remote.
    recovery.restore_git_recovery(restored)
    assert _git(restored, "rev-parse", "HEAD") == head
    assert _git(restored, "rev-parse", "unpublished-side") == side
    assert _git(restored, "rev-parse", "local-tag") == _git(project, "rev-parse", "local-tag")
    assert _git(restored, "stash", "list", "--format=%H %gs") == stashes
    if object_format == "sha1":
        assert _git(restored, "stash", "show", "-p", "stash@{1}").find("older stash") >= 0
    assert _git(restored, "status", "--porcelain=v1", "--untracked-files=no") == _git(project, "status", "--porcelain=v1", "--untracked-files=no")
    assert "unique-untracked" in status
    assert (restored / "unique-untracked").read_text() == "unique work"
    assert (restored / "note").read_text() == "unstaged"
    assert _git(restored, "show", ":note") == "staged"
    assert (restored / ".git/index").read_bytes() == (project / ".git/index").read_bytes()
    assert not (restored / ".git/objects/info/alternates").exists()
    assert _git(restored, "fsck", "--full", "--no-dangling") == ""
    assert subprocess.run(["git", "-C", str(restored), "cat-file", "-e", old], capture_output=True).returncode != 0
    assert _git(restored, "remote", "get-url", "origin") == "https://example.invalid/repository.git"


def test_no_published_baseline_falls_back_to_full_and_retains_multiple_stashes(tmp_path: Path) -> None:
    project, old, _baseline = _project(tmp_path)
    _git(project, "remote", "remove", "origin")
    for value in ("older", "newer"):
        (project / "note").write_text(value)
        _git(project, "stash", "push", "-m", value)
    snapshot, manifest = _snapshot(project, tmp_path / "stage")
    assert manifest["git"]["capture_mode"] == "full"
    assert manifest["git"]["compact_fallback_reason"] == "no_published_baseline"
    recovery.restore_git_recovery(snapshot)
    assert _git(snapshot, "cat-file", "-t", old) == "commit"
    assert _git(snapshot, "stash", "list", "--format=%H %gs") == _git(project, "stash", "list", "--format=%H %gs")


def test_compact_bundle_reuse_is_deterministic_and_rejects_full_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _old, _baseline = _project(tmp_path)
    _commit(project, "note", "local change")
    first, manifest = _snapshot(project, tmp_path / "first")
    second, second_manifest = _snapshot(project, tmp_path / "second")
    assert manifest == second_manifest
    bundle = first / recovery.RECOVERY_DIR_NAME / recovery.GIT_BUNDLE_NAME
    assert bundle.read_bytes() == (second / recovery.RECOVERY_DIR_NAME / recovery.GIT_BUNDLE_NAME).read_bytes()
    original = recovery._create_git_bundle
    calls = []

    def record(*args):
        calls.append(True)
        original(*args)

    monkeypatch.setattr(recovery, "_create_git_bundle", record)
    reuse = {"bundle_path": bundle, "git": manifest["git"]}
    _snapshot(project, tmp_path / "reuse", reuse=reuse)
    assert not calls
    full, full_manifest = _snapshot(project, tmp_path / "full", mode="full", reuse=reuse)
    assert calls == [True]
    assert full_manifest["git"]["capture_mode"] == "full"
    recovery.restore_git_recovery(full)
    assert _git(full, "rev-list", "--count", "HEAD") == "4"


def test_split_index_and_http_remote_identity_restore_without_url_credentials(tmp_path: Path) -> None:
    project, _old, _baseline = _project(tmp_path)
    _git(project, "remote", "set-url", "origin", "https://user:token@example.invalid/repository.git?access_token=secret#token")
    _git(project, "update-index", "--split-index")
    (project / "note").write_text("staged split index")
    _git(project, "add", "note")
    before = _metadata(project)
    before_times = _metadata_times(project)
    snapshot, manifest = _snapshot(project, tmp_path / "stage")
    assert _metadata(project) == before
    assert _metadata_times(project) == before_times
    assert manifest["git"]["shared_index_name"].startswith("sharedindex.")
    assert "token" not in json.dumps(manifest)
    recovery.restore_git_recovery(snapshot)
    assert (snapshot / ".git/index").read_bytes() == (project / ".git/index").read_bytes()
    assert _git(snapshot, "show", ":note") == "staged split index"
    assert _git(snapshot, "remote", "get-url", "origin") == "https://example.invalid/repository.git"


@pytest.mark.parametrize("bad_boundary", ["../escape", "f" * 40])
def test_restore_rejects_invalid_or_missing_shallow_boundary(tmp_path: Path, bad_boundary: str) -> None:
    project, _old, _baseline = _project(tmp_path)
    snapshot, _manifest = _snapshot(project, tmp_path / "stage")
    path = snapshot / recovery.RECOVERY_DIR_NAME / recovery.RECOVERY_MANIFEST_NAME
    manifest = json.loads(path.read_text())
    manifest["git"]["shallow_commits"] = [bad_boundary]
    path.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match=r"(?:Invalid Git shallow|Missing Git shallow)"):
        recovery.restore_git_recovery(snapshot)


def test_compact_preserves_unmerged_index_stages(tmp_path: Path) -> None:
    project, _old, _baseline = _project(tmp_path)
    _git(project, "checkout", "-b", "side")
    _commit(project, "note", "side conflict")
    _git(project, "checkout", "main")
    _commit(project, "note", "main conflict")
    merge = subprocess.run(["git", "-C", str(project), "merge", "side"], capture_output=True)
    assert merge.returncode == 1
    original = (project / ".git/index").read_bytes()
    snapshot, _manifest = _snapshot(project, tmp_path / "stage")
    recovery.restore_git_recovery(snapshot)
    assert (snapshot / ".git/index").read_bytes() == original
    assert _git(snapshot, "ls-files", "--stage") == _git(project, "ls-files", "--stage")
    for entry in _git(project, "ls-files", "--stage").splitlines():
        object_id = entry.split()[1]
        assert _git(snapshot, "cat-file", "blob", object_id) == _git(project, "cat-file", "blob", object_id)


def test_compact_preserves_untracked_stash_and_disconnected_local_branch(tmp_path: Path) -> None:
    project, _old, _baseline = _project(tmp_path)
    (project / "stashed-original").write_text("unique stashed work")
    _git(project, "stash", "push", "--include-untracked", "-m", "untracked original")
    _git(project, "checkout", "--orphan", "unpublished-independent")
    _git(project, "rm", "-rf", ".")
    independent = _commit(project, "independent", "unpublished independent root")
    _git(project, "checkout", "main")
    snapshot, manifest = _snapshot(project, tmp_path / "stage")
    assert independent not in manifest["git"]["shallow_commits"]
    recovery.restore_git_recovery(snapshot)
    assert _git(snapshot, "show", "unpublished-independent:independent") == "unpublished independent root"
    assert _git(snapshot, "show", "stash@{0}^3:stashed-original") == "unique stashed work"
    assert _git(snapshot, "fsck", "--full", "--no-dangling") == ""


@pytest.mark.parametrize("uncertain", ["unconfigured_remote", "non_commit_ref", "replacement_ref"])
def test_uncertain_published_baselines_keep_full_history(tmp_path: Path, uncertain: str) -> None:
    project, old, baseline = _project(tmp_path)
    if uncertain == "unconfigured_remote":
        _git(project, "update-ref", "refs/remotes/unknown/main", baseline)
    elif uncertain == "non_commit_ref":
        blob = _git(project, "rev-parse", "HEAD:note")
        _git(project, "update-ref", "refs/tags/blob-tag", blob)
    else:
        _git(project, "replace", old, baseline)
    snapshot, manifest = _snapshot(project, tmp_path / "stage")
    assert manifest["git"]["capture_mode"] == "full"
    assert manifest["git"]["compact_fallback_reason"]
    recovery.restore_git_recovery(snapshot)
    assert _git(snapshot, "--no-replace-objects", "cat-file", "-t", old) == "commit"
    assert _git(snapshot, "--no-replace-objects", "fsck", "--full", "--no-dangling") == ""


def test_legacy_full_manifest_without_new_fields_remains_readable(tmp_path: Path) -> None:
    project, old, _baseline = _project(tmp_path)
    snapshot, manifest = _snapshot(project, tmp_path / "stage", mode="full")
    for field in ("capture_mode", "shallow_commits", "stash_entries", "remote_config", "shared_index_name", "shared_index_checksum", "recovery_format"):
        manifest["git"].pop(field, None)
    (snapshot / recovery.RECOVERY_DIR_NAME / recovery.RECOVERY_MANIFEST_NAME).write_text(json.dumps(manifest))
    assert recovery.restore_git_recovery(snapshot)["git_restored"] is True
    assert _git(snapshot, "cat-file", "-t", old) == "commit"


def test_snapshot_fails_closed_when_stash_reflog_changes_during_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _old, _baseline = _project(tmp_path)
    (project / "note").write_text("stash original")
    _git(project, "stash", "push", "-m", "original")
    original = recovery.create_git_recovery_payload

    def capture_then_change(*args, **kwargs):
        manifest = original(*args, **kwargs)
        _git(project, "reflog", "expire", "--expire=now", "refs/stash")
        return manifest

    monkeypatch.setattr(recovery, "create_git_recovery_payload", capture_then_change)
    with pytest.raises(RuntimeError, match="source changed during capture"):
        _snapshot(project, tmp_path / "stage")


def test_published_refs_unrelated_to_current_unpublished_work_do_not_retain_historical_trees(tmp_path: Path) -> None:
    project, old, baseline = _project(tmp_path)
    _git(project, "tag", "old-published-tag", old)
    _git(project, "branch", "old-published-branch", old)
    _commit(project, "note", "unpublished main")
    snapshot, manifest = _snapshot(project, tmp_path / "stage")
    assert manifest["git"]["omitted_published_ref_count"] == 2
    assert not any("old-published" in line for line in manifest["git"]["refs"])
    assert baseline in manifest["git"]["shallow_commits"]
    recovery.restore_git_recovery(snapshot)
    assert subprocess.run(["git", "-C", str(snapshot), "cat-file", "-e", old], capture_output=True).returncode != 0
    assert _git(snapshot, "fsck", "--full", "--no-dangling") == ""


@pytest.mark.parametrize("corrupt", [False, True])
def test_restore_rejects_missing_or_corrupt_exact_index_before_initializing_git(tmp_path: Path, corrupt: bool) -> None:
    project, _old, _baseline = _project(tmp_path)
    snapshot, _manifest = _snapshot(project, tmp_path / "stage")
    index = snapshot / recovery.RECOVERY_DIR_NAME / recovery.GIT_INDEX_NAME
    if corrupt:
        index.write_bytes(b"corrupt index")
    else:
        index.unlink()
    with pytest.raises(RuntimeError, match="Git recovery index checksum mismatch"):
        recovery.restore_git_recovery(snapshot)
    assert not (snapshot / ".git").exists()


def test_existing_synthetic_objects_in_source_are_not_freshened_by_capture(tmp_path: Path) -> None:
    project, _old, _baseline = _project(tmp_path)
    first, _manifest = _snapshot(project, tmp_path / "first")
    # Old backups wrote their synthetic objects into source Git. Seed those
    # same objects to cover Git's alternate-object last-used mtime refresh.
    _git(project, "bundle", "unbundle", str(first / recovery.RECOVERY_DIR_NAME / recovery.GIT_BUNDLE_NAME))
    before = _metadata_times(project)
    _snapshot(project, tmp_path / "second")
    assert _metadata_times(project) == before


def test_already_shallow_source_keeps_full_available_git_with_existing_boundaries(tmp_path: Path) -> None:
    project, _old, _baseline = _project(tmp_path)
    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "--depth=1", project.as_uri(), str(shallow))
    original = _metadata_times(shallow)
    snapshot, manifest = _snapshot(shallow, tmp_path / "stage")
    assert manifest["git"]["capture_mode"] == "full"
    assert manifest["git"]["compact_fallback_reason"] == "source_already_shallow"
    assert manifest["git"]["shallow_commits"]
    assert _metadata_times(shallow) == original
    recovery.restore_git_recovery(snapshot)
    assert _git(snapshot, "fsck", "--full", "--no-dangling") == ""
    assert _git(snapshot, "rev-list", "--count", "HEAD") == "1"


def test_unpublished_annotated_tag_on_old_published_commit_retains_annotation(tmp_path: Path) -> None:
    project, old, _baseline = _project(tmp_path)
    _git(project, "tag", "-a", "unpublished-note", old, "-m", "unique unpublished annotation")
    tag_id = _git(project, "rev-parse", "unpublished-note")
    snapshot, manifest = _snapshot(project, tmp_path / "stage")
    assert old in manifest["git"]["shallow_commits"]
    assert f"{tag_id} refs/tags/unpublished-note" in manifest["git"]["refs"]
    recovery.restore_git_recovery(snapshot)
    assert _git(snapshot, "cat-file", "tag", tag_id) == _git(project, "cat-file", "tag", tag_id)
    assert _git(snapshot, "fsck", "--full", "--no-dangling") == ""
