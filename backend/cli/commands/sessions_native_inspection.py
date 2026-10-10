"""Local, read-only native session receipt; no Agent Hub transport or mutation."""

from __future__ import annotations

import re
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any

import typer

from ..output import output_error, output_json
from .sessions_options import JsonOutputOption


def transcript_library() -> ModuleType:
    library = str(Path(__file__).resolve().parents[3] / "scripts/lib")
    if library not in sys.path:
        sys.path.insert(0, library)
    return import_module("codex_sync_transcripts")


def native_inspection_receipt(info: Any) -> dict[str, object]:
    """Keep the own thread, transcript runtime alias and spawned parent separate."""
    evidence = dict(info.model_evidence)
    scan = info.model_scan
    return {
        "schema_version": "native-session-inspection.v1",
        "thread_id": info.session_id,
        "transcript_runtime_session_id": info.native_session_id,
        "parent_thread_id": info.parent_session_id,
        "agent_path": info.agent_path or (None if info.parent_session_id else "/root"),
        "agent_nickname": info.agent_nickname,
        "cwd": str(info.cwd),
        "requested_model": evidence.get("requested_model"),
        "requested_reasoning_effort": evidence.get("requested_reasoning_effort"),
        "observed_model": evidence.get("observed_model"),
        "model_evidence": evidence,
        "transcript_path": str(info.path),
        "source_generation": evidence.get("source_generation") or scan.get("source_generation"),
        "source_line": evidence.get("source_line"),
        "source_timestamp": evidence.get("source_timestamp"),
        "is_open": info.is_open,
        "ownership_ambiguous": info.ownership_ambiguous,
        "identity_error": info.identity_error,
        "source_extent": info.size,
        "scanned_byte_offset": scan.get("offset"),
    }


def inspect_native_session(
    session_id: Annotated[str, typer.Argument(help="current or an exact native thread ID")] = "current",
    json_output: JsonOutputOption = False,
) -> None:
    """Inspect native identity/model-request evidence entirely from local sources."""
    library = transcript_library()
    try:
        if session_id == "current":
            info = library.resolve_current_transcript()
        else:
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", session_id) is None:
                raise ValueError("An exact native thread ID is required.")
            snapshot = library.discover_open_transcripts()
            paths = set(snapshot.paths) | set(library.TRANSCRIPTS_ROOT.rglob(f"*{session_id}.jsonl"))
            matches = [
                info for path in sorted(paths)
                if (info := library.read_transcript_info(path, open_snapshot=snapshot)) is not None
                and info.session_id == session_id
            ]
            if len(matches) != 1:
                raise ValueError("Native transcript identity is unavailable or ambiguous.")
            info = matches[0]
        receipt = native_inspection_receipt(info)
    except (OSError, ValueError) as exc:
        output_error(str(exc))
        raise typer.Exit(1) from exc
    if json_output:
        output_json(receipt)
    else:
        print(f"NATIVE_SESSION:{receipt['thread_id']}|runtime={receipt['transcript_runtime_session_id']}|parent={receipt['parent_thread_id']}|requested={receipt['requested_model']}|observed={receipt['observed_model']}|open={receipt['is_open']}")
