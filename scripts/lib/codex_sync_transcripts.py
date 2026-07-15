"""Transcript discovery and parsing for codex-session-sync."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

TRANSCRIPTS_ROOT = Path.home() / ".codex" / "sessions"
PROC_ROOT = Path("/proc")
DEFAULT_MODEL = "unknown"
TRANSCRIPT_SCAN_LINES = 100
AICO_PERSONAL_PROJECT_ID = "__aico_personal_workspace__"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,254}$")
_AICO_ENV_KEYS = frozenset({
    "AICO_AGENT_SLUG",
    "AICO_LIFECYCLE_VERSION",
    "AICO_OWNER",
    "AICO_PROJECT_ID",
    "AICO_SESSION_ID",
    "AICO_TMUX_SERVER_ID",
    "AICO_WIDGET_ID",
    "AICO_WORKLOAD_CLASS",
})


@dataclass(frozen=True)
class AicoProcessOwner:
    """Allow-listed AICO ownership identity inherited by a Codex process."""

    harness: str
    aico_session_id: str
    aico_widget_id: str
    aico_project_id: str


@dataclass(frozen=True)
class OpenTranscriptSnapshot:
    """Open Codex transcript paths and their validated AICO owners."""

    paths: frozenset[Path]
    owners: dict[Path, AicoProcessOwner]
    ambiguous_paths: frozenset[Path]

    @classmethod
    def empty(cls) -> OpenTranscriptSnapshot:
        return cls(paths=frozenset(), owners={}, ambiguous_paths=frozenset())


@dataclass(frozen=True)
class TranscriptInfo:
    path: Path
    session_id: str
    cwd: Path
    model: str
    mtime: float
    size: int
    parent_session_id: str | None = None
    agent_nickname: str | None = None
    agent_path: str | None = None
    is_open: bool = False
    process_owner: AicoProcessOwner | None = None
    ownership_ambiguous: bool = False


def _safe_identifier(value: object) -> str:
    text = value if isinstance(value, str) else ""
    return text if _IDENTIFIER_RE.fullmatch(text) else ""


def _safe_display_identity(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _safe_agent_path(value: object) -> str | None:
    if not isinstance(value, str) or not _AGENT_PATH_RE.fullmatch(value):
        return None
    if ".." in Path(value).parts:
        return None
    return value


def _subagent_identity(source: object) -> tuple[str | None, str | None, str | None]:
    if not isinstance(source, dict):
        return None, None, None
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return None, None, None
    spawn = subagent.get("thread_spawn")
    if not isinstance(spawn, dict):
        return None, None, None
    parent = _safe_identifier(spawn.get("parent_thread_id")) or None
    nickname = _safe_display_identity(spawn.get("agent_nickname"))
    agent_path = _safe_agent_path(spawn.get("agent_path"))
    return parent, nickname, agent_path


def _extract_transcript_fields(
    path: Path,
) -> tuple[str, str, str, str | None, str | None, str | None]:
    """Extract identity from the first session_meta and model from turn context."""
    session_id = cwd = model = ""
    parent_session_id = agent_nickname = agent_path = None
    saw_session_meta = False
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= TRANSCRIPT_SCAN_LINES:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            obj_type = obj.get("type")
            if obj_type == "session_meta" and not saw_session_meta:
                # Child rollout files can contain a copied parent session_meta on
                # their second line.  The first record is the immutable identity
                # of this rollout and must never be overwritten by that copy.
                saw_session_meta = True
                session_id = _safe_identifier(payload.get("id"))
                raw_cwd = payload.get("cwd")
                cwd = raw_cwd if isinstance(raw_cwd, str) and Path(raw_cwd).is_absolute() else ""
                parent_session_id, agent_nickname, agent_path = _subagent_identity(
                    payload.get("source")
                )
            elif obj_type == "turn_context" and not model:
                raw_model = payload.get("model")
                if isinstance(raw_model, str) and len(raw_model) <= 128:
                    model = raw_model
            if saw_session_meta and session_id and cwd and model:
                break
    return session_id, cwd, model, parent_session_id, agent_nickname, agent_path


def read_transcript_info(
    path: Path,
    log_fn: object = None,
    open_snapshot: OpenTranscriptSnapshot | None = None,
) -> TranscriptInfo | None:
    """Parse a JSONL transcript file and return metadata from its header lines."""
    try:
        session_id, cwd, model, parent_session_id, agent_nickname, agent_path = (
            _extract_transcript_fields(path)
        )
    except OSError as exc:
        if log_fn:
            log_fn(f"[WARN] Failed to read transcript {path}: {exc}")
        return None
    if not session_id or not cwd:
        return None
    try:
        stat = path.stat()
        resolved = path.expanduser().resolve(strict=False)
    except OSError as exc:
        if log_fn:
            log_fn(f"[WARN] Failed to stat transcript {path}: {exc}")
        return None
    snapshot = open_snapshot or OpenTranscriptSnapshot.empty()
    return TranscriptInfo(
        path=resolved,
        session_id=session_id,
        cwd=Path(cwd),
        model=model or DEFAULT_MODEL,
        mtime=stat.st_mtime,
        size=stat.st_size,
        parent_session_id=parent_session_id,
        agent_nickname=agent_nickname,
        agent_path=agent_path,
        is_open=resolved in snapshot.paths,
        process_owner=snapshot.owners.get(resolved),
        ownership_ambiguous=resolved in snapshot.ambiguous_paths,
    )


def iter_recent_transcripts(
    recent_hours: int,
    log_fn: object = None,
    open_snapshot: OpenTranscriptSnapshot | None = None,
) -> list[TranscriptInfo]:
    if not TRANSCRIPTS_ROOT.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=recent_hours)
    transcripts: list[TranscriptInfo] = []
    for path in TRANSCRIPTS_ROOT.rglob("*.jsonl"):
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            continue
        if modified_at < cutoff:
            continue
        info = read_transcript_info(path, log_fn=log_fn, open_snapshot=open_snapshot)
        if info is not None:
            transcripts.append(info)
    transcripts.sort(key=lambda item: item.mtime)
    return transcripts


def _proc_entries(proc_root: Path = PROC_ROOT) -> list[Path]:
    try:
        return [path for path in proc_root.iterdir() if path.name.isdigit()]
    except OSError:
        return []


def _read_cmdline(proc_dir: Path) -> list[str]:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "ignore") for part in raw.split(b"\0") if part]


def _looks_like_codex_process(parts: list[str]) -> bool:
    return any(Path(part).name == "codex" for part in parts)


def has_live_codex_process(proc_root: Path = PROC_ROOT) -> bool:
    """Return True when a live process looks like a Codex CLI wrapper or binary."""
    for proc_dir in _proc_entries(proc_root):
        if _looks_like_codex_process(_read_cmdline(proc_dir)):
            return True
    return False


def _read_allowlisted_aico_environment(proc_dir: Path) -> dict[str, str]:
    try:
        raw = (proc_dir / "environ").read_bytes()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        raw_key, raw_value = item.split(b"=", 1)
        key = raw_key.decode("ascii", "ignore")
        if key not in _AICO_ENV_KEYS:
            continue
        values[key] = raw_value.decode("utf-8", "ignore")[:256]
    return values


def _validated_aico_owner(environment: dict[str, str]) -> tuple[AicoProcessOwner | None, bool]:
    """Return (owner, invalid_marker) without retaining the process environment."""
    marker = environment.get("AICO_OWNER")
    if marker is None:
        return None, False
    if marker != "aico" or environment.get("AICO_WORKLOAD_CLASS") != "durable-session":
        return None, True
    if environment.get("AICO_LIFECYCLE_VERSION") != "1":
        return None, True

    harness = _safe_identifier(environment.get("AICO_AGENT_SLUG"))
    session_id = _safe_identifier(environment.get("AICO_SESSION_ID"))
    widget_id = _safe_identifier(environment.get("AICO_WIDGET_ID"))
    project_id = environment.get("AICO_PROJECT_ID", "")
    if (
        project_id
        and project_id != AICO_PERSONAL_PROJECT_ID
        and not _safe_identifier(project_id)
    ):
        return None, True
    server_id = environment.get("AICO_TMUX_SERVER_ID", "")
    if server_id and not re.fullmatch(r"[a-f0-9]{8,64}", server_id):
        return None, True
    if harness != "codex" or not session_id or not widget_id:
        return None, True
    return (
        AicoProcessOwner(
            harness=harness,
            aico_session_id=session_id,
            aico_widget_id=widget_id,
            aico_project_id=project_id,
        ),
        False,
    )


def _resolved_transcript_target(fd: Path, root: Path) -> Path | None:
    try:
        target = os.readlink(fd)
    except OSError:
        return None
    target = target.removesuffix(" (deleted)")
    if not target.endswith(".jsonl"):
        return None
    target_path = Path(target)
    if not target_path.is_absolute():
        return None
    try:
        resolved = target_path.resolve(strict=False)
    except OSError:
        resolved = target_path
    return resolved if resolved.is_relative_to(root) else None


def discover_open_transcripts(
    *,
    proc_root: Path = PROC_ROOT,
    transcripts_root: Path = TRANSCRIPTS_ROOT,
) -> OpenTranscriptSnapshot:
    """Discover live Codex rollouts and validated AICO ownership from /proc."""
    try:
        root = transcripts_root.expanduser().resolve(strict=False)
    except OSError:
        root = transcripts_root.expanduser()

    paths: set[Path] = set()
    owners: dict[Path, AicoProcessOwner] = {}
    ambiguous: set[Path] = set()
    for proc_dir in _proc_entries(proc_root):
        if not _looks_like_codex_process(_read_cmdline(proc_dir)):
            continue
        environment = _read_allowlisted_aico_environment(proc_dir)
        owner, invalid_owner = _validated_aico_owner(environment)
        try:
            fds = list((proc_dir / "fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            resolved = _resolved_transcript_target(fd, root)
            if resolved is None:
                continue
            paths.add(resolved)
            if invalid_owner:
                ambiguous.add(resolved)
                owners.pop(resolved, None)
                continue
            if owner is None or resolved in ambiguous:
                continue
            previous = owners.get(resolved)
            if previous is not None and previous != owner:
                ambiguous.add(resolved)
                owners.pop(resolved, None)
                continue
            owners[resolved] = owner
    return OpenTranscriptSnapshot(
        paths=frozenset(paths),
        owners=owners,
        ambiguous_paths=frozenset(ambiguous),
    )


def iter_open_transcript_paths(
    *,
    proc_root: Path = PROC_ROOT,
    transcripts_root: Path = TRANSCRIPTS_ROOT,
) -> set[Path]:
    """Return Codex transcript files currently held open by live host processes."""
    return set(
        discover_open_transcripts(
            proc_root=proc_root,
            transcripts_root=transcripts_root,
        ).paths
    )
