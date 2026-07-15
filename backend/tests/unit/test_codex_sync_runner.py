from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_runner = importlib.import_module("codex_sync_runner")
codex_sync_transcripts = importlib.import_module("codex_sync_transcripts")


def _project(project_id: str = "a-loom") -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_aliases": [],
        "branch": "main",
        "repo_root": f"/srv/workspaces/projects/{project_id}",
        "git_context": "abc123 test",
    }


def _info(
    tmp_path: Path,
    session_id: str,
    *,
    parent_session_id: str | None = None,
    is_open: bool = True,
    owner=None,
):
    return codex_sync_transcripts.TranscriptInfo(
        path=(tmp_path / f"{session_id}.jsonl").resolve(),
        session_id=session_id,
        cwd=Path("/srv/workspaces/projects/a-loom"),
        model="gpt-5.4",
        mtime=10.0,
        size=200,
        parent_session_id=parent_session_id,
        agent_nickname="Leibniz" if parent_session_id else None,
        agent_path="/root/child" if parent_session_id else None,
        is_open=is_open,
        process_owner=owner,
    )


def _args(**overrides) -> argparse.Namespace:
    values = {
        "transcript": None,
        "recent_hours": 24,
        "cwd": None,
        "close": False,
        "close_inactive": False,
        "force": False,
        "verbose": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _write_rollout(
    path: Path,
    session_id: str,
    *,
    parent_session_id: str | None = None,
) -> None:
    source: object = "cli"
    if parent_session_id:
        source = {
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": parent_session_id,
                    "agent_nickname": "Child",
                    "agent_path": "/root/child",
                }
            }
        }
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": "/srv/workspaces/projects/a-loom",
                "source": source,
            },
        },
        {"type": "turn_context", "payload": {"model": "gpt-5.4"}},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )


def test_transcript_infos_include_old_open_rollouts_and_order_parent_first(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent = tmp_path / "parent.jsonl"
    child = tmp_path / "child.jsonl"
    _write_rollout(parent, "parent-session")
    _write_rollout(child, "child-session", parent_session_id="parent-session")
    os.utime(parent, (20, 20))
    os.utime(child, (10, 10))
    snapshot = codex_sync_transcripts.OpenTranscriptSnapshot(
        paths=frozenset({parent.resolve(), child.resolve()}),
        owners={},
        ambiguous_paths=frozenset(),
    )
    monkeypatch.setattr(codex_sync_runner, "iter_recent_transcripts", lambda *_a, **_kw: [])

    infos = codex_sync_runner._transcript_infos(_args(), {}, snapshot, lambda _message: None)

    assert [info.session_id for info in infos] == ["parent-session", "child-session"]
    assert all(info.is_open for info in infos)


def test_transcript_infos_revisit_old_tracked_rollout_for_inactive_close(
    tmp_path: Path,
    monkeypatch,
) -> None:
    transcript = tmp_path / "old-tracked.jsonl"
    _write_rollout(transcript, "tracked-session")
    snapshot = codex_sync_transcripts.OpenTranscriptSnapshot.empty()
    state: dict[str, object] = {
        "transcripts": {
            str(transcript.resolve()): {
                "session_id": "tracked-session",
                "status": "active",
            }
        }
    }
    monkeypatch.setattr(codex_sync_runner, "iter_recent_transcripts", lambda *_a, **_kw: [])

    infos = codex_sync_runner._transcript_infos(
        _args(close_inactive=True),
        state,
        snapshot,
        lambda _message: None,
    )

    assert [info.session_id for info in infos] == ["tracked-session"]
    assert infos[0].is_open is False


def test_sync_passes_aico_external_identity_parent_and_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    owner = codex_sync_transcripts.AicoProcessOwner(
        harness="codex",
        aico_session_id="aico-widget-35f62654",
        aico_widget_id="35f62654",
        aico_project_id="a-loom",
    )
    info = _info(tmp_path, "child-session", parent_session_id="parent-session", owner=owner)
    state: dict[str, object] = {"transcripts": {}}
    captured: dict[str, object] = {}
    monkeypatch.setattr(codex_sync_runner, "build_project_context", lambda _cwd: _project())

    def fake_upsert(*args, **kwargs):
        captured["upsert_args"] = args
        captured["upsert_kwargs"] = kwargs
        return True, "", 200

    monkeypatch.setattr(codex_sync_runner, "upsert_session", fake_upsert)
    monkeypatch.setattr(
        codex_sync_runner,
        "ingest_transcript",
        lambda *_args, **_kwargs: (True, "checkpoint-1", "appended=1 skipped=0", "", 200),
    )
    monkeypatch.setattr(
        codex_sync_runner,
        "send_heartbeat",
        lambda *_args, **_kwargs: (True, "", 200),
    )

    ok, _, _ = codex_sync_runner.sync_transcript(
        info,
        state,
        "http://agent-hub.test/api",
        "summitflow",
        "/scripts/codex-session-sync.py",
        close_session=False,
        ingest_required=True,
        heartbeat_required=True,
        log_fn=lambda _message: None,
        verbose=False,
    )

    assert ok
    kwargs = cast(dict[str, object], captured["upsert_kwargs"])
    assert kwargs["parent_session_id"] == "parent-session"
    metadata = cast(dict[str, object], kwargs["provider_metadata"])
    assert metadata["external_identity"] == {
        "harness": "codex",
        "launcher": "aico",
        "display_identity": "Leibniz",
        "runtime_session_id": "child-session",
        "agent_path": "/root/child",
        "aico_session_id": "aico-widget-35f62654",
        "aico_widget_id": "35f62654",
        "aico_project_id": "a-loom",
        "project_mapping_state": "matched",
    }
    entry = state["transcripts"][str(info.path)]
    assert isinstance(entry, dict)
    assert entry["checkpoint"] == "checkpoint-1"
    assert entry["status"] == "active"
    assert entry["last_heartbeat_at"]


def test_unchanged_open_transcript_still_heartbeats_without_ingest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    info = _info(tmp_path, "live-session")
    state: dict[str, object] = {
        "transcripts": {
            str(info.path): {
                "session_id": info.session_id,
                "mtime": info.mtime,
                "size": info.size,
                "status": "active",
                "last_heartbeat_at": "2026-01-01T00:00:00+00:00",
            }
        }
    }
    calls: list[dict[str, object]] = []

    def fake_sync_transcript(**kwargs):
        calls.append(kwargs)
        return True, "ok", None

    monkeypatch.setattr(codex_sync_runner, "sync_transcript", fake_sync_transcript)

    codex_sync_runner._sync_infos(
        args=_args(),
        state=state,
        infos=[info],
        api_url="http://agent-hub.test/api",
        client_id="summitflow",
        source_path="/scripts/codex-session-sync.py",
        log_fn=lambda _message: None,
        live_transcript_paths={info.path},
        saw_live_codex_process=True,
    )

    assert len(calls) == 1
    assert calls[0]["ingest_required"] is False
    assert calls[0]["heartbeat_required"] is True
    assert calls[0]["close_session"] is False


def test_corrected_child_identity_resets_checkpoint_from_collapsed_parent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    info = _info(tmp_path, "child-session", parent_session_id="parent-session")
    state: dict[str, object] = {
        "transcripts": {
            str(info.path): {
                "session_id": "parent-session",
                "mtime": info.mtime,
                "size": info.size,
                "status": "active",
                "checkpoint": "checkpoint-written-to-parent",
            }
        }
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(codex_sync_runner, "build_project_context", lambda _cwd: _project())
    monkeypatch.setattr(
        codex_sync_runner,
        "upsert_session",
        lambda *_args, **_kwargs: (True, "", 200),
    )

    def fake_ingest(_session_id, _path, checkpoint, **_kwargs):
        captured["checkpoint"] = checkpoint
        return True, "child-checkpoint", "appended=1 skipped=0", "", 200

    monkeypatch.setattr(codex_sync_runner, "ingest_transcript", fake_ingest)

    ok, _, _ = codex_sync_runner.sync_transcript(
        info,
        state,
        "http://agent-hub.test/api",
        "summitflow",
        "/scripts/codex-session-sync.py",
        close_session=False,
        ingest_required=True,
        heartbeat_required=False,
        log_fn=lambda _message: None,
        verbose=False,
    )

    assert ok
    assert captured["checkpoint"] is None
    transcripts = cast(dict[str, dict[str, object]], state["transcripts"])
    assert transcripts[str(info.path)]["checkpoint"] == "child-checkpoint"


def test_close_inactive_closes_missing_child_without_closing_open_parent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent = _info(tmp_path, "parent-session")
    child = _info(
        tmp_path,
        "child-session",
        parent_session_id="parent-session",
        is_open=False,
    )
    heartbeat_at = datetime.now(UTC).isoformat()
    state: dict[str, object] = {
        "transcripts": {
            str(info.path): {
                "session_id": info.session_id,
                "mtime": info.mtime,
                "size": info.size,
                "status": "active",
                "last_heartbeat_at": heartbeat_at,
            }
            for info in (parent, child)
        }
    }
    calls: list[dict[str, object]] = []

    def fake_sync_transcript(**kwargs):
        calls.append(kwargs)
        return True, "ok", None

    monkeypatch.setattr(codex_sync_runner, "sync_transcript", fake_sync_transcript)

    codex_sync_runner._sync_infos(
        args=_args(close_inactive=True),
        state=state,
        infos=[parent, child],
        api_url="http://agent-hub.test/api",
        client_id="summitflow",
        source_path="/scripts/codex-session-sync.py",
        log_fn=lambda _message: None,
        live_transcript_paths={parent.path},
        saw_live_codex_process=True,
    )

    assert len(calls) == 1
    called_info = cast(codex_sync_transcripts.TranscriptInfo, calls[0]["info"])
    assert called_info.session_id == "child-session"
    assert calls[0]["close_session"] is True
    assert calls[0]["ingest_required"] is False
    assert calls[0]["heartbeat_required"] is False


def test_live_codex_process_without_detectable_fds_blocks_mass_close(tmp_path: Path) -> None:
    info = _info(tmp_path, "live-session", is_open=False)

    assert not codex_sync_runner._close_inactive_session(
        info,
        close_all=False,
        close_inactive=True,
        live_transcript_paths=set(),
        saw_live_codex_process=True,
    )


def test_aico_git_project_mismatch_fails_closed_before_api_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    owner = codex_sync_transcripts.AicoProcessOwner(
        harness="codex",
        aico_session_id="aico-widget-35f62654",
        aico_widget_id="35f62654",
        aico_project_id="rootfall",
    )
    info = _info(tmp_path, "mismatch-session", owner=owner)
    monkeypatch.setattr(codex_sync_runner, "build_project_context", lambda _cwd: _project())

    ok, detail, status = codex_sync_runner.sync_transcript(
        info,
        {"transcripts": {}},
        "http://agent-hub.test/api",
        "summitflow",
        "/scripts/codex-session-sync.py",
        close_session=False,
        ingest_required=True,
        heartbeat_required=True,
        log_fn=lambda _message: None,
        verbose=False,
    )

    assert not ok
    assert status is None
    assert detail.startswith("conflict AICO/Git project mismatch")


def test_unmapped_personal_workspace_is_explicitly_skipped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    info = _info(tmp_path, "personal-session")
    info = codex_sync_transcripts.TranscriptInfo(
        **{**info.__dict__, "cwd": Path("/home/demo/.local/share/aico/personal-workspace")}
    )
    monkeypatch.setattr(codex_sync_runner, "build_project_context", lambda _cwd: None)

    ok, detail, status = codex_sync_runner.sync_transcript(
        info,
        {"transcripts": {}},
        "http://agent-hub.test/api",
        "summitflow",
        "/scripts/codex-session-sync.py",
        close_session=False,
        ingest_required=True,
        heartbeat_required=True,
        log_fn=lambda _message: None,
        verbose=False,
    )

    assert not ok
    assert status is None
    assert detail == "skip unmapped/unregistered cwd=/home/demo/.local/share/aico/personal-workspace"
