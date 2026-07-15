from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_transcripts = importlib.import_module("codex_sync_transcripts")


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )


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
    (proc_root / "123" / "cmdline").write_bytes(b"/usr/local/bin/codex\0")
    (fd_dir / "26").symlink_to(transcript)

    assert codex_sync_transcripts.iter_open_transcript_paths(
        proc_root=proc_root,
        transcripts_root=transcripts_root,
    ) == {transcript.resolve()}


def test_read_transcript_info_keeps_first_child_session_meta(tmp_path: Path) -> None:
    transcript = tmp_path / "child.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "child-session",
                    "cwd": "/srv/workspaces/projects/a-loom",
                    "source": {
                        "subagent": {
                            "thread_spawn": {
                                "parent_thread_id": "parent-session",
                                "agent_nickname": "Leibniz",
                                "agent_path": "/root/aico_session_federation",
                            }
                        }
                    },
                },
            },
            {
                "type": "session_meta",
                "payload": {
                    "id": "parent-session",
                    "cwd": "/wrong/parent/cwd",
                    "source": "cli",
                },
            },
            {"type": "turn_context", "payload": {"model": "gpt-5.4"}},
        ],
    )

    info = codex_sync_transcripts.read_transcript_info(transcript)

    assert info is not None
    assert info.session_id == "child-session"
    assert info.cwd == Path("/srv/workspaces/projects/a-loom")
    assert info.parent_session_id == "parent-session"
    assert info.agent_nickname == "Leibniz"
    assert info.agent_path == "/root/aico_session_federation"


def test_read_transcript_info_root_has_no_parent_identity(tmp_path: Path) -> None:
    transcript = tmp_path / "root.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "root-session",
                    "cwd": "/srv/workspaces/projects/a-loom",
                    "source": "cli",
                },
            },
            {"type": "turn_context", "payload": {"model": "gpt-5.4"}},
        ],
    )

    info = codex_sync_transcripts.read_transcript_info(transcript)

    assert info is not None
    assert info.session_id == "root-session"
    assert info.parent_session_id is None
    assert info.agent_nickname is None
    assert info.agent_path is None
