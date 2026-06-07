from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_transcripts = importlib.import_module("codex_sync_transcripts")


def test_has_live_codex_process_detects_wrapper_or_binary(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / "123"
    proc_dir.mkdir(parents=True)
    (proc_dir / "cmdline").write_bytes(b"bash\0/home/demo/bin/codex\0--yolo\0")

    assert codex_sync_transcripts.has_live_codex_process(proc_root)


def test_has_live_codex_process_ignores_sync_script(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / "123"
    proc_dir.mkdir(parents=True)
    (proc_dir / "cmdline").write_bytes(b"python\0scripts/codex-session-sync.py\0")

    assert not codex_sync_transcripts.has_live_codex_process(proc_root)


def test_iter_open_transcript_paths_returns_open_codex_jsonl(tmp_path: Path) -> None:
    transcripts_root = tmp_path / "sessions"
    transcript = transcripts_root / "2026" / "04" / "rollout.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}", encoding="utf-8")

    proc_root = tmp_path / "proc"
    fd_dir = proc_root / "123" / "fd"
    fd_dir.mkdir(parents=True)
    (fd_dir / "26").symlink_to(transcript)

    assert codex_sync_transcripts.iter_open_transcript_paths(
        proc_root=proc_root,
        transcripts_root=transcripts_root,
    ) == {transcript.resolve()}
