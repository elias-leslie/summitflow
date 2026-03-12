"""Display helpers for the persona CLI."""

from __future__ import annotations

from typing import Any


def field_status(persona: dict[str, Any], field: str) -> str:
    val = persona.get(field)
    if not val:
        return "unset"
    return f"set ({len(val)} chars)" if isinstance(val, str) else "set"


def print_persona(persona: dict[str, Any]) -> None:
    preview = ""
    if persona.get("personality"):
        lines = persona["personality"].strip().splitlines()
        preview = lines[0][:60] if lines else ""
    print(f"persona | {persona.get('name', '?')} | agent={persona.get('agent_slug', '?')}")
    print(f"  voice={persona.get('voice_id', '?')} enabled={persona.get('voice_enabled', False)}")
    print(f"  heartbeat={persona.get('heartbeat_interval_minutes', 0)}m")
    mode = persona.get("session_reset_mode", "off")
    if mode == "daily":
        detail = f" hour={persona.get('session_reset_hour', 0)}"
    elif mode == "idle":
        detail = f" idle={persona.get('session_reset_idle_minutes', 30)}m"
    else:
        detail = ""
    print(f"  session_reset={mode}{detail}")
    print(f"  personality_v{persona.get('version', 0)}: {preview}")
    print(f"  heartbeat_instructions: {field_status(persona, 'heartbeat_instructions')}")
    print(f"  user_context: {field_status(persona, 'user_context')}")
    if persona.get("onboarding_phase"):
        print(f"  onboarding_phase: {persona['onboarding_phase']}")


def print_heartbeat_result(status: dict[str, Any]) -> None:
    """Print heartbeat completion summary with session metrics."""
    sid = status.get("last_session_id", "?")
    last_run = status.get("last_run", "?")
    parts = [f"last_run={last_run}"]
    if status.get("last_turns") is not None:
        parts.append(f"turns={status['last_turns']}")
    if status.get("last_tool_calls") is not None:
        parts.append(f"tool_calls={status['last_tool_calls']}")
    fmt = status.get("last_format_compliant")
    had_error = status.get("last_had_error")
    if fmt is not None:
        parts.append(f"format_ok={'yes' if fmt else 'NO'}")
    if had_error is not None:
        parts.append(f"errors={'YES' if had_error else 'none'}")
    if status.get("last_auto_journaled"):
        parts.append("auto_journaled=yes")
    print(f"Heartbeat complete | session={sid}")
    print(f"  {' | '.join(parts)}")


def get_dispatch_hint(client: Any, project_id: str | None) -> str | None:
    """Return a one-line dispatch hint from the canonical project pulse."""
    if not project_id:
        return None
    payload = client.get(client._global_url(f"/projects/{project_id}/pulse"))
    if not isinstance(payload, dict):
        return None
    running_tasks = payload.get("running_tasks", [])
    if not running_tasks:
        return None
    active_owners = payload.get("active_owners", [])
    active_sessions = payload.get("active_sessions", [])
    task = running_tasks[0] if isinstance(running_tasks[0], dict) else {}
    owner = active_owners[0] if active_owners and isinstance(active_owners[0], dict) else {}
    session = active_sessions[0] if active_sessions and isinstance(active_sessions[0], dict) else {}
    task_id = task.get("id") or "?"
    title = str(task.get("title") or "")[:70]
    agent_slug = owner.get("agent_slug") or session.get("agent_slug") or "agent"
    session_id = str(owner.get("session_id") or session.get("id") or "")[:8]
    return f"Dispatch detected: {task_id} | {agent_slug} | {session_id} | {title}"


def maybe_report_dispatch(client: Any, project: str | None, reported: bool) -> bool:
    """Show dispatch hint once; return updated reported flag."""
    if reported or not client:
        return reported
    hint = get_dispatch_hint(client, project)
    if hint:
        print(f"\n  {hint}", end="", flush=True)
        return True
    return reported


def print_preview_detail(
    preview_data: dict[str, Any],
    mode: str,
    project: str | None,
    phase: str | None,
    full_context: str,
) -> None:
    """Print the full preview detail: header, sections, memory UUIDs, and context."""
    print(
        f"{preview_data.get('name', 'Persona')} preview | "
        f"mode={preview_data.get('task_type') or mode} | "
        f"sections={len(preview_data.get('sections') or [])} | "
        f"mandates={preview_data.get('mandate_count', 0)} | "
        f"guardrails={preview_data.get('guardrail_count', 0)}"
    )
    if project:
        print(f"project={project}")
    if phase:
        print(f"phase={phase}")
    if preview_data.get("memory_query"):
        print(f"memory_query={preview_data['memory_query']}")

    for section in preview_data.get("sections") or []:
        print(
            "\n"
            f"=== {section.get('label', 'Section')} | "
            f"{section.get('placement', 'system')} | "
            f"{section.get('source_kind', 'unknown')} | "
            f"{section.get('source_id', '-')}"
            f" | {section.get('estimated_tokens', 0)} tok ==="
        )
        print(section.get("content", ""))

    if preview_data.get("loaded_memory_uuids"):
        print("\n=== Loaded Memory UUIDs ===")
        for uuid in preview_data["loaded_memory_uuids"]:
            print(uuid)

    print("\n=== Full Context ===")
    print(full_context)
