"""Recovery preserves indexes that cannot be represented as a commit tree."""

import hashlib
import struct
from pathlib import Path

import pytest

from tests.tasks.test_backup_native_recovery import _git


def _index_entries(data: bytes) -> dict[bytes, bytes]:
    """Read v2/v3 fixture entries, dropping only optional cache extensions."""
    offset = 12
    entries = {}
    for _ in range(struct.unpack("!I", data[8:12])[0]):
        flags = struct.unpack("!H", data[offset + 60:offset + 62])[0]
        name_start = offset + 62 + (2 if flags & 0x4000 else 0)
        name_end = data.index(b"\0", name_start)
        end = offset + ((name_end + 1 - offset + 7) // 8) * 8
        entries[data[name_start:name_end]] = data[offset:end]
        offset = end
    return entries


@pytest.mark.parametrize("history_mode", ["full", "compact"])
def test_recovery_preserves_intent_to_add_directory_conflict(tmp_path: Path, history_mode: str) -> None:
    from app.tasks.backup_native_recovery import (
        create_git_recovery_payload,
        git_state,
        restore_git_recovery,
    )

    project = tmp_path / "source"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "base").write_text("base")
    _git(project, "add", "base")
    _git(project, "commit", "-m", "base")
    _git(project, "remote", "add", "origin", "https://example.invalid/fixture.git")
    _git(project, "update-ref", "refs/remotes/origin/main", "HEAD")
    skill = project / "skill"
    skill.write_text("")
    _git(project, "add", "-N", "skill")
    intent_entry = _index_entries((project / ".git/index").read_bytes())[b"skill"]
    skill.unlink()
    skill.mkdir()
    (skill / "SKILL.md").write_text("staged-only content")
    _git(project, "add", "skill/SKILL.md")
    staged_blob = _git(project, "rev-parse", ":skill/SKILL.md")
    entries = _index_entries((project / ".git/index").read_bytes())
    entries[b"skill"] = intent_entry
    payload = b"DIRC" + struct.pack("!II", 3, len(entries))
    payload += b"".join(entries[name] for name in sorted(entries))
    (project / ".git/index").write_bytes(payload + hashlib.sha1(payload).digest())
    original_index = (project / ".git/index").read_bytes()
    restored = tmp_path / "restored"
    restored.mkdir()

    create_git_recovery_payload(project, restored, git_state(project), git_history_mode=history_mode)
    restore_git_recovery(restored)

    assert (project / ".git/index").read_bytes() == original_index
    assert (restored / ".git/index").read_bytes() == original_index
    assert _git(restored, "cat-file", "blob", staged_blob) == "staged-only content"
    assert _git(restored, "ls-files", "--stage") == _git(project, "ls-files", "--stage")
