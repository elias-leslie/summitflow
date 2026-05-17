"""Formatting and preflight helpers for `st pulse`."""

from __future__ import annotations

from typing import Any

from ..lib.jj import JJRepoStatus


def _scope_preview(owner: dict[str, Any]) -> str:
    scope = owner.get("scope_paths") or []
    return ",".join(str(path) for path in scope[:3]) if isinstance(scope, list) else ""


def _format_owner(owner: dict[str, Any]) -> str:
    scope_preview = _scope_preview(owner)
    kind = str(owner.get("ownership_kind") or "unknown")
    if kind == "unscoped" and owner.get("task_id"):
        kind = "task_checkout"
    details = [
        str(owner.get("task_id") or "-"),
        str(owner.get("agent_slug") or "?"),
        str(owner.get("session_id") or "?")[:8],
        f"kind={kind}",
    ]
    if scope_preview:
        details.append(f"paths={scope_preview}")
    if owner.get("scope_confidence"):
        details.append(f"scope={owner['scope_confidence']}")
    if owner.get("is_stale"):
        details.append("stale=yes")
    return "WRITE " + " | ".join(details)


def _format_reader(reader: dict[str, Any]) -> str:
    paths = reader.get("observed_read_paths") or reader.get("scope_paths") or []
    path_preview = ",".join(str(path) for path in paths[:3]) if isinstance(paths, list) else ""
    details = [
        str(reader.get("task_id") or "-"),
        str(reader.get("agent_slug") or reader.get("source_client") or "?"),
        str(reader.get("session_id") or "?")[:8],
    ]
    if path_preview:
        details.append(f"paths={path_preview}")
    if reader.get("scope_confidence"):
        details.append(f"scope={reader['scope_confidence']}")
    return "READ " + " | ".join(details)


def _session_actor_label(session: dict[str, Any]) -> str:
    for key in ("agent_slug", "source_client", "request_source", "session_type"):
        value = session.get(key)
        if isinstance(value, str) and value:
            return value
    return "?"


def _format_session(session: dict[str, Any]) -> str:
    raw_live = session.get("live_activity")
    live: dict[str, Any] = raw_live if isinstance(raw_live, dict) else {}
    touched = live.get("files_touched") if isinstance(live, dict) else []
    touched_preview = ",".join(str(path) for path in touched[:2]) if isinstance(touched, list) else ""
    observed_writes = session.get("observed_write_paths") if isinstance(session.get("observed_write_paths"), list) else []
    write_preview = ",".join(str(path) for path in observed_writes[:2]) if observed_writes else ""
    model = session.get("effective_model") or session.get("requested_model") or "unknown"
    details = [
        str(session.get("lane_role") or "observer"),
        _session_actor_label(session),
        str(session.get("id") or "?")[:8],
        str(model).split("/")[-1],
        f"{live.get('health', session.get('status', 'unknown'))}/{live.get('phase', session.get('status', 'unknown'))}",
    ]
    if session.get("scope_confidence"):
        details.append(f"scope={session['scope_confidence']}")
    if write_preview:
        details.append(f"writes={write_preview}")
    if touched_preview:
        details.append(f"files={touched_preview}")
    return "SES " + " | ".join(details)


def _format_stale_session(session: dict[str, Any]) -> str:
    raw_live = session.get("live_activity")
    live: dict[str, Any] = raw_live if isinstance(raw_live, dict) else {}
    model = session.get("effective_model") or session.get("requested_model") or "unknown"
    state = live.get("lifecycle_state") or live.get("health") or session.get("status") or "unknown"
    details = [
        str(session.get("lane_role") or "observer"),
        _session_actor_label(session),
        str(session.get("id") or "?")[:8],
        str(model).split("/")[-1],
        str(state),
    ]
    reapable_reason = live.get("reapable_reason")
    if isinstance(reapable_reason, str) and reapable_reason:
        details.append(f"reason={reapable_reason}")
    return "STALE " + " | ".join(details)


def _format_task(task: dict[str, Any]) -> str:
    return "RUN " + " | ".join(
        [
            str(task.get("id") or "?"),
            str(task.get("status") or "?"),
            f"P{task.get('priority') if task.get('priority') is not None else '?'}",
            str(task.get("title") or "")[:80],
        ]
    )


def _format_stranded_task(task: dict[str, Any]) -> str:
    return "STRANDED " + " | ".join(
        [
            str(task.get("id") or "?"),
            str(task.get("status") or "?"),
            "no_owner_session",
            str(task.get("title") or "")[:80],
        ]
    )


def _truthy_count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dirty_residue_count(cleanup: dict[str, Any]) -> int:
    dirty = _truthy_count(cleanup.get("dirty_checkpoints")) + _truthy_count(
        cleanup.get("dirty_repositories")
    )
    if dirty == 0 and _truthy_count(cleanup.get("dirty_main_repo")):
        dirty = 1
    return dirty


def _needs_ownerless_review(summary: dict[str, Any], cleanup: dict[str, Any]) -> bool:
    active_agents = (
        _truthy_count(summary.get("active_owners"))
        + _truthy_count(summary.get("active_specialists"))
    )
    if active_agents or _truthy_count(summary.get("active_sessions")):
        return False
    return bool(
        _truthy_count(cleanup.get("active_checkpoints"))
        or _dirty_residue_count(cleanup)
        or _truthy_count(summary.get("stranded_tasks"))
    )


def _record_session_id(record: dict[str, Any]) -> str:
    return str(record.get("session_id") or record.get("id") or "")


def _record_has_observed_writes(record: dict[str, Any]) -> bool:
    writes = record.get("observed_write_paths")
    if not isinstance(writes, list):
        return False
    return any(str(path).strip() for path in writes)


def _nonwriter_write_sessions(payload: dict[str, Any]) -> int:
    writer_session_ids = {
        _record_session_id(record)
        for key in ("active_owners", "active_specialists")
        for record in payload.get(key, [])
        if isinstance(record, dict) and _record_session_id(record)
    }
    count = 0
    seen: set[str] = set()
    for key in ("active_sessions", "active_readers"):
        records = payload.get(key, [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or not _record_has_observed_writes(record):
                continue
            session_id = _record_session_id(record)
            if session_id and session_id in writer_session_ids:
                continue
            if session_id and session_id in seen:
                continue
            if session_id:
                seen.add(session_id)
            count += 1
    return count


def _format_nonwriter_session_review(
    project_id: Any,
    summary: dict[str, Any],
    cleanup: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> str | None:
    if _truthy_count(summary.get("active_owners")) or _truthy_count(summary.get("active_specialists")):
        return None
    nonwriter_writes = _nonwriter_write_sessions(payload or {})
    if not nonwriter_writes:
        return None
    if not (
        _truthy_count(cleanup.get("active_checkpoints"))
        or _dirty_residue_count(cleanup)
        or _truthy_count(summary.get("stranded_tasks"))
    ):
        return None
    return (
        f"SESSION-REVIEW:{project_id}|nonwriter_writes={nonwriter_writes}|dirty={_dirty_residue_count(cleanup)}|"
        f"checkpoints={_truthy_count(cleanup.get('active_checkpoints'))}|"
        "action=inspect-write-session-before-cleanup-or-adoption"
    )


def _format_ownerless_review(project_id: Any, summary: dict[str, Any], cleanup: dict[str, Any]) -> str | None:
    if not _needs_ownerless_review(summary, cleanup):
        return None
    return (
        f"REVIEW:{project_id}|ownerless=yes|dirty={_dirty_residue_count(cleanup)}|"
        f"checkpoints={_truthy_count(cleanup.get('active_checkpoints'))}|"
        f"stranded={_truthy_count(summary.get('stranded_tasks'))}|"
        "action=agent-inspect-context-status-logs-then-commit-push-prune-or-leave-explicit-handoff"
    )


def _format_jj_state(project_id: Any, status: JJRepoStatus) -> str:
    return (
        f"JJSTATE:{project_id}|state={status.state}|described={str(status.described).lower()}|"
        f"conflicts={str(status.conflicted).lower()}|unpublished={status.unpublished}|"
        f"change={status.change_id}|commit={status.commit_id}"
    )


def _format_vcs_review(project_id: Any, cleanup: dict[str, Any], jj_status: JJRepoStatus | None) -> str | None:
    dirty = _dirty_residue_count(cleanup)
    if jj_status is None:
        if not dirty:
            return None
        return f"VCS-REVIEW:{project_id}|dirty={dirty}|action=commit-push-or-continue-narrow"

    needs_revision_commit = jj_status.state not in {"clean", "described", "unpublished"}
    needs_review = bool(
        dirty
        or needs_revision_commit
        or jj_status.conflicted
        or jj_status.unpublished
    )
    if not needs_review:
        return None

    if jj_status.conflicted:
        action = "resolve-jj-conflicts"
    elif dirty or needs_revision_commit:
        action = "commit-push-or-continue-narrow"
    else:
        action = "push-unpublished"
    return (
        f"VCS-REVIEW:{project_id}|dirty={dirty}|jj_state={jj_status.state}|"
        f"described={str(jj_status.described).lower()}|unpublished={jj_status.unpublished}|"
        f"action={action}"
    )


_RESOLUTION_HINTS: dict[str, str] = {
    "jj_conflicts": "st vcs reconcile",
    "active_nonwriter_write_session": (
        "st pulse --sessions to inspect, or wait for the writer to release"
    ),
    "task_lane_conflict": (
        "st abandon <conflicting-task-id> or rebase the conflicting checkpoint branch"
    ),
}


def resolution_hint(reason: str) -> str | None:
    """Return the resolution command for a typed preflight reason, if known."""
    return _RESOLUTION_HINTS.get(reason)


def _preflight_reasons(
    summary: dict[str, Any],
    cleanup: dict[str, Any],
    jj_status: JJRepoStatus | None = None,
    payload: dict[str, Any] | None = None,
) -> list[str]:
    reasons: list[str] = []
    if jj_status and jj_status.colocated and jj_status.conflicted:
        reasons.append("jj_conflicts")
    if _format_nonwriter_session_review("?", summary, cleanup, payload):
        reasons.append("active_nonwriter_write_session")
    return reasons


def _format_preflight(
    project_id: Any,
    summary: dict[str, Any],
    cleanup: dict[str, Any],
    jj_status: JJRepoStatus | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    reasons = _preflight_reasons(summary, cleanup, jj_status, payload)
    state = "blocked" if reasons else "clear"
    detail = ",".join(reasons) if reasons else "-"
    return f"PREFLIGHT:{project_id}|claim={state}|edit={state}|reasons={detail}|source=st-pulse"


def _record_belongs_to_task(record: dict[str, Any], task_id: str) -> bool:
    for key in ("task_id", "external_id"):
        if str(record.get(key) or "") == task_id:
            return True
    for key in ("current_branch", "branch"):
        branch = record.get(key)
        if isinstance(branch, str) and branch.split("/", 1)[0] == task_id:
            return True
    return False


def _allowed_task_session_ids(payload: dict[str, Any], task_id: str) -> set[str]:
    session_ids: set[str] = set()
    for key in ("active_owners", "active_readers", "active_specialists", "active_sessions"):
        records = payload.get(key, [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or not _record_belongs_to_task(record, task_id):
                continue
            session_id = _record_session_id(record)
            if session_id:
                session_ids.add(session_id)
    return session_ids


def _filter_allowed_task_records(records: Any, task_id: str, allowed_session_ids: set[str]) -> list[Any]:
    if not isinstance(records, list):
        return []
    filtered: list[Any] = []
    for record in records:
        if not isinstance(record, dict):
            filtered.append(record)
            continue
        session_id = _record_session_id(record)
        if _record_belongs_to_task(record, task_id) or (session_id and session_id in allowed_session_ids):
            continue
        filtered.append(record)
    return filtered


def _filter_allowed_task_rows(records: Any, task_id: str) -> list[Any]:
    if not isinstance(records, list):
        return []
    return [
        record
        for record in records
        if not (
            isinstance(record, dict)
            and (str(record.get("id") or "") == task_id or _record_belongs_to_task(record, task_id))
        )
    ]


def _payload_for_allowed_task(payload: dict[str, Any], task_id: str | None) -> dict[str, Any]:
    if not task_id:
        return payload
    allowed_session_ids = _allowed_task_session_ids(payload, task_id)
    filtered = dict(payload)
    filtered["active_owners"] = _filter_allowed_task_records(payload.get("active_owners", []), task_id, allowed_session_ids)
    filtered["active_readers"] = _filter_allowed_task_records(payload.get("active_readers", []), task_id, allowed_session_ids)
    filtered["active_specialists"] = _filter_allowed_task_records(
        payload.get("active_specialists", []), task_id, allowed_session_ids
    )
    filtered["active_sessions"] = _filter_allowed_task_records(
        payload.get("active_sessions", []), task_id, allowed_session_ids
    )
    filtered["running_tasks"] = _filter_allowed_task_rows(payload.get("running_tasks", []), task_id)
    filtered["stranded_tasks"] = _filter_allowed_task_rows(payload.get("stranded_tasks", []), task_id)
    summary = dict(payload.get("summary", {}))
    summary["active_owners"] = len(filtered["active_owners"])
    summary["active_readers"] = len(filtered["active_readers"])
    summary["active_specialists"] = len(filtered["active_specialists"])
    summary["active_sessions"] = len(filtered["active_sessions"])
    summary["running_tasks"] = len(filtered["running_tasks"])
    summary["stranded_tasks"] = len(filtered["stranded_tasks"])
    filtered["summary"] = summary
    cleanup = dict(payload.get("cleanup", {}))
    checkpoint_ids = cleanup.get("checkpoint_task_ids")
    if isinstance(checkpoint_ids, list) and task_id in {str(item) for item in checkpoint_ids}:
        cleanup["checkpoint_task_ids"] = [item for item in checkpoint_ids if str(item) != task_id]
        cleanup["active_checkpoints"] = max(0, _truthy_count(cleanup.get("active_checkpoints")) - 1)
    filtered["cleanup"] = cleanup
    return filtered


def print_compact_payload(
    payload: dict[str, Any],
    *,
    details: bool,
    jj_status_for_project: Any,
) -> None:
    summary = payload.get("summary", {})
    cleanup = payload.get("cleanup", {})
    project_id = payload.get("project_id", "?")
    jj_status = jj_status_for_project(project_id)
    _print_summary_line(project_id, summary, cleanup)
    if jj_status is not None:
        print(_format_jj_state(project_id, jj_status))
    print(_format_preflight(project_id, summary, cleanup, jj_status, payload))
    _print_review_lines(project_id, summary, cleanup, jj_status, payload)
    if details:
        _print_detail_rows(payload)


def _print_summary_line(project_id: Any, summary: dict[str, Any], cleanup: dict[str, Any]) -> None:
    print(
        "PULSE:{project}|tasks={tasks}|writers={writers}|readers={readers}|specialists={specialists}|"
        "sessions={sessions}|stale={stale}|reapable={reapable}|checkpoints={checkpoints}|dirty={dirty}|cleanup={cleanup_needed}|stranded={stranded}".format(
            project=project_id,
            tasks=summary.get("running_tasks", 0),
            writers=summary.get("active_owners", 0),
            readers=summary.get("active_readers", 0),
            specialists=summary.get("active_specialists", 0),
            sessions=summary.get("active_sessions", 0),
            stale=summary.get("stale_sessions", 0),
            reapable=summary.get("reapable_sessions", 0),
            checkpoints=cleanup.get("active_checkpoints", 0),
            dirty=_dirty_residue_count(cleanup),
            cleanup_needed="yes" if cleanup.get("needs_cleanup") else "no",
            stranded=summary.get("stranded_tasks", 0),
        )
    )


def _print_review_lines(
    project_id: Any,
    summary: dict[str, Any],
    cleanup: dict[str, Any],
    jj_status: JJRepoStatus | None,
    payload: dict[str, Any],
) -> None:
    review_line = _format_ownerless_review(project_id, summary, cleanup)
    session_review_line = _format_nonwriter_session_review(project_id, summary, cleanup, payload)
    vcs_review_line = _format_vcs_review(project_id, cleanup, jj_status)
    for line in (review_line, session_review_line, vcs_review_line):
        if line:
            print(line)
    if review_line or session_review_line or vcs_review_line:
        print(
            f"ACTION:{project_id}|if_dirty=inspect-diff-once-then-commit-or-continue-narrow|"
            "ownership=diagnostic-only"
        )


def _print_detail_rows(payload: dict[str, Any]) -> None:
    _print_rows(payload.get("running_tasks", [])[:4], _format_task)
    _print_rows(payload.get("stranded_tasks", [])[:4], _format_stranded_task)
    _print_rows(payload.get("active_owners", [])[:4], _format_owner)
    _print_rows(payload.get("active_readers", [])[:4], _format_reader)
    summarized_session_ids = {
        str(row.get("session_id") or "")
        for key in ("active_owners", "active_readers", "active_specialists")
        for row in payload.get(key, [])
        if isinstance(row, dict)
    }
    visible_sessions = [
        session for session in payload.get("active_sessions", [])
        if isinstance(session, dict)
        and str(session.get("id") or "") not in summarized_session_ids
    ]
    _print_rows(visible_sessions[:4], _format_session)
    _print_rows(payload.get("stale_sessions", [])[:4], _format_stale_session)


def _print_rows(rows: list[Any], formatter: Any) -> None:
    for row in rows:
        if isinstance(row, dict):
            print(formatter(row))
