"""Point-in-time capture behavior for live append-only JSONL files."""

from pathlib import Path

import pytest


def test_snapshot_keeps_inventoried_jsonl_prefix_when_writer_appends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_recovery as recovery

    project = tmp_path / "project"
    project.mkdir()
    transcript = project / "sessions" / "rollout.jsonl"
    transcript.parent.mkdir()
    inventoried_prefix = b'{"event":"before"}\n'
    transcript.write_bytes(inventoried_prefix)
    original_copy = recovery.copy_inventory_snapshot

    def copy_then_append(project_dir, destination, inventory):
        original_copy(project_dir, destination, inventory)
        with transcript.open("ab") as stream:
            stream.write(b'{"event":"after"}\n')

    monkeypatch.setattr(recovery, "copy_inventory_snapshot", copy_then_append)

    snapshot, _manifest = recovery.build_consistent_snapshot(
        project,
        tmp_path / "stage",
        (),
        lambda *_args: False,
    )

    assert (snapshot / "sessions" / "rollout.jsonl").read_bytes() == inventoried_prefix


@pytest.mark.parametrize("mutation", ["rewrite", "truncate"])
def test_snapshot_rejects_jsonl_prefix_rewrite_or_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from app.tasks import backup_native_recovery as recovery

    project = tmp_path / "project"
    project.mkdir()
    transcript = project / "session.jsonl"
    transcript.write_bytes(b'{"event":"original"}\n')
    original_copy = recovery.copy_inventory_snapshot

    def copy_then_mutate(project_dir, destination, inventory):
        original_copy(project_dir, destination, inventory)
        replacement = (
            b'{"event":"rewritten"}\n'
            if mutation == "rewrite"
            else b'{"eve'
        )
        transcript.write_bytes(replacement)

    monkeypatch.setattr(recovery, "copy_inventory_snapshot", copy_then_mutate)

    with pytest.raises(RuntimeError, match=r"changed during capture: session\.jsonl"):
        recovery.build_consistent_snapshot(
            project,
            tmp_path / "stage",
            (),
            lambda *_args: False,
        )


def test_snapshot_preserves_exact_bytes_for_stable_jsonl(tmp_path: Path) -> None:
    from app.tasks import backup_native_recovery as recovery

    project = tmp_path / "project"
    project.mkdir()
    transcript = project / "session.jsonl"
    raw_bytes = b'{"event":"complete"}\n{"event":"in-flight"'
    transcript.write_bytes(raw_bytes)

    snapshot, _manifest = recovery.build_consistent_snapshot(
        project,
        tmp_path / "stage",
        (),
        lambda *_args: False,
    )

    assert (snapshot / "session.jsonl").read_bytes() == raw_bytes


@pytest.mark.parametrize(
    ("lock_contents", "expected_in_snapshot"),
    [(b"", False), (b"valuable lock state", True)],
)
def test_snapshot_excludes_only_empty_jj_git_import_export_lock(
    tmp_path: Path,
    lock_contents: bytes,
    expected_in_snapshot: bool,
) -> None:
    from app.tasks import backup_native_recovery as recovery

    project = tmp_path / "project"
    jj_repo = project / ".jj" / "repo"
    jj_repo.mkdir(parents=True)
    transient_lock = jj_repo / "git_import_export.lock"
    transient_lock.write_bytes(lock_contents)
    valuable_lock = jj_repo / "valuable.lock"
    valuable_lock.write_bytes(b"")
    (jj_repo / "operation-state").write_bytes(b"keep")

    snapshot, _manifest = recovery.build_consistent_snapshot(
        project,
        tmp_path / "stage",
        (),
        lambda *_args: False,
    )

    assert (snapshot / ".jj" / "repo" / "git_import_export.lock").exists() is expected_in_snapshot
    assert (snapshot / ".jj" / "repo" / "valuable.lock").is_file()
    assert (snapshot / ".jj" / "repo" / "operation-state").read_bytes() == b"keep"
