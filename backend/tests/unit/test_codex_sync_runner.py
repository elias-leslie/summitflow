from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_runner = importlib.import_module("codex_sync_runner")
codex_sync_transcripts = importlib.import_module("codex_sync_transcripts")
codex_sync_bindings = importlib.import_module("codex_sync_bindings")


def _project(project_id: str = "a-loom") -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_aliases": [],
        "branch": "main",
        "repo_root": f"/srv/workspaces/projects/{project_id}",
        "git_context": "abc123 test",
    }


def _binding(session_id: str, project_id: str = "rootfall"):
    return codex_sync_bindings.ProjectBinding(
        session_id=session_id,
        project_id=project_id,
        project_root=f"/srv/workspaces/projects/{project_id}",
        bound_at="2026-07-15T00:00:00+00:00",
        source="explicit",
        parent_session_id=None,
    )


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


def test_unbound_aico_personal_workspace_still_skips_without_api_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    owner = codex_sync_transcripts.AicoProcessOwner(
        harness="codex",
        aico_session_id="aico-widget-35f62654",
        aico_widget_id="35f62654",
        aico_project_id="__aico_personal_workspace__",
    )
    info = _info(tmp_path, "unbound-personal-session", owner=owner)
    info = codex_sync_transcripts.TranscriptInfo(
        **{**info.__dict__, "cwd": Path("/home/demo/.local/share/aico/personal-workspace")}
    )
    calls: list[object] = []
    monkeypatch.setattr(codex_sync_runner, "build_project_context", lambda _cwd: None)
    monkeypatch.setattr(codex_sync_runner, "upsert_session", lambda *args, **_kwargs: calls.append(args))

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
    assert detail.startswith("skip unmapped/unregistered cwd=")
    assert calls == []


def test_personal_workspace_explicit_binding_upserts_exact_rootfall_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    owner = codex_sync_transcripts.AicoProcessOwner(
        harness="codex",
        aico_session_id="aico-widget-35f62654",
        aico_widget_id="35f62654",
        aico_project_id="__aico_personal_workspace__",
    )
    info = _info(tmp_path, "rootfall-session", owner=owner)
    info = codex_sync_transcripts.TranscriptInfo(
        **{**info.__dict__, "cwd": Path("/home/demo/.local/share/aico/personal-workspace")}
    )
    captured: dict[str, object] = {}

    def project_context(cwd: Path):
        return _project("rootfall") if cwd == Path("/srv/workspaces/projects/rootfall") else None

    def fake_upsert(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return True, "", 200

    monkeypatch.setattr(codex_sync_runner, "build_project_context", project_context)
    monkeypatch.setattr(codex_sync_runner, "upsert_session", fake_upsert)
    monkeypatch.setattr(
        codex_sync_runner,
        "ingest_transcript",
        lambda *_args, **_kwargs: (True, "checkpoint-1", "appended=1", "", 200),
    )

    state: dict[str, object] = {"transcripts": {}}
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
        project_binding=_binding(info.session_id),
    )

    assert ok
    args = cast(tuple[object, ...], captured["args"])
    assert args[0] == "rootfall-session"
    assert cast(dict[str, object], args[1])["project_id"] == "rootfall"
    assert args[3] == Path("/srv/workspaces/projects/rootfall")
    kwargs = cast(dict[str, object], captured["kwargs"])
    metadata = cast(dict[str, object], kwargs["provider_metadata"])
    external = cast(dict[str, object], metadata["external_identity"])
    assert external["aico_project_id"] == "__aico_personal_workspace__"
    assert external["project_mapping_state"] == "explicit_binding"
    transcripts = cast(dict[str, dict[str, object]], state["transcripts"])
    assert transcripts[str(info.path)]["project_binding_fingerprint"]


def test_binding_request_validates_registered_root_and_current_git_mapping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    info = _info(tmp_path, "bind-request-session")
    root = Path("/srv/workspaces/projects/rootfall")
    monkeypatch.setattr(
        codex_sync_runner,
        "fetch_registered_project_root",
        lambda _project_id: root,
    )

    def mismatched_context(cwd: Path):
        return _project("rootfall") if cwd == root else _project("a-loom")

    monkeypatch.setattr(codex_sync_runner, "build_project_context", mismatched_context)
    binding, error = codex_sync_runner._project_binding_request(
        _args(
            bind_session=info.session_id,
            bind_project="rootfall",
            project_root=root,
        ),
        [info],
    )

    assert binding is None
    assert error.startswith("conflict Codex thread binding/Git project mismatch")


def test_explicit_binding_still_rejects_mapped_git_project_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    info = _info(tmp_path, "mismatch-bound-session")
    calls: list[object] = []

    def project_context(cwd: Path):
        if cwd == info.cwd:
            return _project("a-loom")
        return _project("rootfall")

    monkeypatch.setattr(codex_sync_runner, "build_project_context", project_context)
    monkeypatch.setattr(codex_sync_runner, "upsert_session", lambda *args, **_kwargs: calls.append(args))

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
        project_binding=_binding(info.session_id),
    )

    assert not ok
    assert status is None
    assert detail.startswith("conflict Codex thread binding/Git project mismatch")
    assert calls == []


def test_binding_change_wakes_previously_skipped_transcript(
    tmp_path: Path,
    monkeypatch,
) -> None:
    info = _info(tmp_path, "newly-bound-session")
    state: dict[str, object] = {
        "transcripts": {
            str(info.path): {
                "session_id": info.session_id,
                "mtime": info.mtime,
                "size": info.size,
                "status": "skipped",
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
        project_bindings={info.session_id: _binding(info.session_id)},
    )

    assert len(calls) == 1
    assert calls[0]["ingest_required"] is True
    assert calls[0]["heartbeat_required"] is True


def test_child_inherits_parent_binding_before_agent_hub_upsert(
    tmp_path: Path,
    monkeypatch,
) -> None:
    owner = codex_sync_transcripts.AicoProcessOwner(
        harness="codex",
        aico_session_id="aico-widget-35f62654",
        aico_widget_id="35f62654",
        aico_project_id="__aico_personal_workspace__",
    )
    parent = _info(tmp_path, "parent-session", owner=owner)
    child = _info(
        tmp_path,
        "child-session",
        parent_session_id="parent-session",
        owner=owner,
    )
    personal = Path("/home/demo/.local/share/aico/personal-workspace")
    parent = codex_sync_transcripts.TranscriptInfo(**{**parent.__dict__, "cwd": personal})
    child = codex_sync_transcripts.TranscriptInfo(**{**child.__dict__, "cwd": personal})
    upserts: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        codex_sync_runner,
        "build_project_context",
        lambda cwd: _project("rootfall")
        if cwd == Path("/srv/workspaces/projects/rootfall")
        else None,
    )

    def fake_upsert(*args, **kwargs):
        upserts.append((*args, kwargs.get("parent_session_id")))
        return True, "", 200

    monkeypatch.setattr(codex_sync_runner, "upsert_session", fake_upsert)
    monkeypatch.setattr(
        codex_sync_runner,
        "ingest_transcript",
        lambda *_args, **_kwargs: (True, "checkpoint", "appended=1", "", 200),
    )
    monkeypatch.setattr(
        codex_sync_runner,
        "send_heartbeat",
        lambda *_args, **_kwargs: (True, "", 200),
    )
    bindings = {parent.session_id: _binding(parent.session_id)}

    changed, _ = codex_sync_runner._sync_infos(
        args=_args(force=True),
        state={"transcripts": {}},
        infos=[parent, child],
        api_url="http://agent-hub.test/api",
        client_id="summitflow",
        source_path="/scripts/codex-session-sync.py",
        log_fn=lambda _message: None,
        live_transcript_paths={parent.path, child.path},
        saw_live_codex_process=True,
        project_bindings=bindings,
    )

    assert changed
    assert [call[0] for call in upserts] == ["parent-session", "child-session"]
    assert all(cast(dict[str, object], call[1])["project_id"] == "rootfall" for call in upserts)
    assert upserts[1][-1] == "parent-session"
    assert bindings["child-session"].source == "inherited"


def test_child_sync_is_deferred_when_parent_sync_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent = _info(tmp_path, "parent-session")
    child = _info(tmp_path, "child-session", parent_session_id="parent-session")
    calls: list[str] = []
    logs: list[str] = []

    def fake_sync_transcript(**kwargs):
        info = cast(codex_sync_transcripts.TranscriptInfo, kwargs["info"])
        calls.append(info.session_id)
        return False, "upstream unavailable", 503

    monkeypatch.setattr(codex_sync_runner, "sync_transcript", fake_sync_transcript)
    bindings = {parent.session_id: _binding(parent.session_id)}
    codex_sync_runner._prepare_project_bindings([parent, child], bindings, None)

    codex_sync_runner._sync_infos(
        args=_args(force=True),
        state={"transcripts": {}},
        infos=[parent, child],
        api_url="http://agent-hub.test/api",
        client_id="summitflow",
        source_path="/scripts/codex-session-sync.py",
        log_fn=logs.append,
        live_transcript_paths={parent.path, child.path},
        saw_live_codex_process=True,
        project_bindings=bindings,
    )

    assert calls == ["parent-session"]
    assert any("Deferred Codex child sync" in message for message in logs)


def test_binding_is_persisted_before_remote_sync_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    info = _info(tmp_path, "bound-before-remote")
    binding = _binding(info.session_id)
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(codex_sync_runner, "sync_lock", nullcontext)
    monkeypatch.setattr(codex_sync_runner, "load_state", lambda: {"transcripts": {}})
    monkeypatch.setattr(codex_sync_runner, "load_project_bindings", lambda: {})
    monkeypatch.setattr(
        codex_sync_runner,
        "discover_open_transcripts",
        codex_sync_transcripts.OpenTranscriptSnapshot.empty,
    )
    monkeypatch.setattr(
        codex_sync_runner,
        "_transcript_infos",
        lambda *_args, **_kwargs: [info],
    )
    monkeypatch.setattr(
        codex_sync_runner,
        "_project_binding_request",
        lambda *_args, **_kwargs: (binding, ""),
    )
    monkeypatch.setattr(
        codex_sync_runner,
        "_live_session_context",
        lambda *_args, **_kwargs: ({info.path}, True),
    )

    def save_bindings(snapshot):
        events.append(("persist", dict(snapshot)))

    def remote_sync(**_kwargs):
        events.append(("remote", {}))
        return False, False

    monkeypatch.setattr(codex_sync_runner, "save_project_bindings_locked", save_bindings)
    monkeypatch.setattr(codex_sync_runner, "_sync_infos", remote_sync)
    monkeypatch.setattr(codex_sync_runner, "save_state", lambda _state: None)

    result = codex_sync_runner.run_sync(
        _args(
            bind_session=info.session_id,
            bind_project="rootfall",
            project_root=Path("/srv/workspaces/projects/rootfall"),
        ),
        api_url="http://agent-hub.test/api",
        client_id="summitflow",
        source_path="/scripts/codex-session-sync.py",
        log_fn=lambda _message: None,
    )

    assert result == 2
    assert [event[0] for event in events] == ["persist", "remote"]
    assert events[0][1][info.session_id] == binding


def test_parent_binding_rejects_existing_child_in_another_project() -> None:
    request = _binding("parent-session")
    child = codex_sync_bindings.ProjectBinding(
        session_id="child-session",
        project_id="a-loom",
        project_root="/srv/workspaces/projects/a-loom",
        bound_at="2026-07-15T00:00:00+00:00",
        source="inherited",
        parent_session_id="parent-session",
    )
    bindings = {child.session_id: child}

    changed, error = codex_sync_runner._prepare_project_bindings([], bindings, request)

    assert not changed
    assert "child/parent project binding mismatch" in error
    assert "parent-session" not in bindings


def test_corrupt_binding_snapshot_fails_closed_with_diagnostic(monkeypatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr(codex_sync_runner, "sync_lock", nullcontext)
    monkeypatch.setattr(codex_sync_runner, "load_state", lambda: {"transcripts": {}})
    monkeypatch.setattr(
        codex_sync_runner,
        "load_project_bindings",
        lambda: (_ for _ in ()).throw(ValueError("broken JSON")),
    )

    result = codex_sync_runner.run_sync(
        _args(),
        api_url="http://agent-hub.test/api",
        client_id="summitflow",
        source_path="/scripts/codex-session-sync.py",
        log_fn=logs.append,
    )

    assert result == 2
    assert logs == ["[WARN] Invalid Codex project binding snapshot: broken JSON"]
