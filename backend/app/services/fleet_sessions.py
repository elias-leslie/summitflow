"""Lean fleet control, with explicit host capability and source-only telemetry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
import redis

from ..storage.fleet_events import (
    append_fleet_event,
    content_digest,
    fleet_root_events,
    read_fleet_page,
)
from .pubsub import fleet_wake_subscription

RootRole = Literal["portfolio-root", "neri-target-root", "neri-support-root"]
RootSurface = Literal["aico", "a-term"]
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
# Owners bound a resumed launch prompt to 2000 UTF-8 bytes of tab/newline-only text.
_RESUME_PROMPT_BYTES = 2000
# Fleet directions name the start cursor; reserve its widest decimal form.
_CURSOR_PLACEHOLDER = 10**19
_SECRET = re.compile(r"(?i)(?:bearer\s+\S+|(?:password|api[_-]?key|secret|token)\s*[:=]\s*\S+)")


def sanitized_instruction(instruction: str) -> str:
    """Bound the transient instruction; callers still supply sanitized content."""
    instruction = "".join(c for c in instruction if c in "\n\t" or (c.isprintable() and c != "\x1b"))
    instruction = _SECRET.sub("[REDACTED]", instruction).strip()
    if not instruction or len(instruction.encode()) > 2000:
        raise ValueError("Instruction must contain 1-2000 sanitized UTF-8 bytes")
    return instruction


def root_state(root: str) -> dict[str, Any]:
    events = fleet_root_events(root)
    if not events or events[0]["event_type"] != "root.started":
        raise LookupError("Fleet root not found")
    initial = events[0]
    state = {
        "root": root, "project_id": initial["project_id"],
        **initial["attributes"], "status": "registered", "host": None,
        "capabilities": {"launch": "unobserved", "send": "fleet-stream", "native_send": "unavailable", "terminate": "unavailable"},
    }
    for event in events[1:]:
        if event["event_type"] == "root.host-observed":
            state["host"] = event["attributes"]
            state["capabilities"]["launch"] = "host-acknowledged"
        elif event["event_type"] == "root.host-unavailable":
            state["capabilities"]["launch"] = "unavailable"
        elif event["event_type"] == "root.closed":
            state["status"] = "closed"
            state["capabilities"]["send"] = "unavailable"
            state["capabilities"]["terminate"] = "host-acknowledged"
        elif event["event_type"] == "root.close-uncertain":
            if state["status"] != "closed":
                state["status"] = "close-uncertain"
                state["capabilities"]["send"] = "unavailable"
    return state


def _host_request(surface: str, path: str, payload: dict[str, Any], *, owner_control: bool = False, method: str = "POST") -> dict[str, Any]:
    if surface == "aico":
        name = "AICO_CONTROL_SOCKET" if owner_control else "AICO_GUI_CONTROL_SOCKET"
        filename = "control.sock" if owner_control else "gui-control.sock"
        socket = os.environ.get(name, f"/run/user/{os.getuid()}/aico/{filename}")
        with httpx.Client(transport=httpx.HTTPTransport(uds=socket), timeout=30) as client:
            response = client.get(f"http://aico{path}") if method == "GET" else client.post(f"http://aico{path}", json=payload)
    elif surface == "a-term":
        base = os.environ.get("A_TERM_ROOT_CONTROL_URL", "http://127.0.0.1:8002").rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
            raise ValueError("A-Term root control requires the existing local owner route")
        # Existing password/proxy mode rejection remains provider-unavailable;
        # this adapter never invents credentials or bypasses owner auth.
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.get(base + path) if method == "GET" else client.post(base + path, json=payload)
    else:
        raise ValueError("Unsupported root surface")
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Invalid host acknowledgment")
    return result


def _host_start(
    root: str, project_id: str, project_root: str, tool: str, prompt: str,
    *, role: str, lead_root: str | None, facet: str | None, surface: RootSurface = "aico",
    resume_session: str | None = None,
) -> dict[str, Any]:
    """Aico's private GUI protocol; acknowledgment is not model/queue evidence."""
    body: dict[str, Any] = {
        "requestId": root, "tool": tool, "projectId": project_id,
        "projectRoot": project_root, "initialPrompt": prompt,
        "role": role, "leadRootReference": lead_root, "facetCapsuleRef": facet,
    }
    if resume_session is not None:
        # The owner's resume adapter validates the exact native ID; fresh
        # launches keep the original body and digest.
        body["resumeSessionId"] = resume_session
    descriptor = _host_request(surface, "/v1/roots", body)
    if (descriptor.get("owner") != surface
            or not descriptor.get("logicalSessionId") or not descriptor.get("hostIdentity")
            or not descriptor.get("surfaceLocator")
            or (not descriptor.get("generation") and descriptor.get("status") not in {"pending", "uncertain", "ended"})):
        raise ValueError("Host returned no verified root descriptor")
    # Keep only the protocol descriptor; never retain unrelated host output.
    return {key: descriptor.get(key) for key in (
        "owner", "hostIdentity", "generation", "logicalSessionId", "surfaceLocator", "status",
    )}


def reconcile_root(root: str) -> dict[str, Any]:
    """Reconcile a retained host request by GET, never recreate an uncertain root."""
    state = root_state(root)
    if state["status"] == "closed":
        return state
    try:
        observed = _host_request(state["surface"], f"/v1/roots/{quote(root, safe='')}", {}, method="GET")
    except (httpx.HTTPError, ValueError, OSError):
        return state
    if (observed.get("owner") != state["surface"] or observed.get("requestId") != root
            or observed.get("role") != state["role"] or observed.get("leadRootReference") != state["lead_root"]
            or observed.get("facetCapsuleRef") != state["facet"] or not observed.get("hostIdentity")
            or not observed.get("logicalSessionId") or not observed.get("surfaceLocator")):
        return state
    prior = state["host"]
    if prior and any(prior.get(key) != observed.get(key) for key in ("hostIdentity", "logicalSessionId", "surfaceLocator")):
        return state
    if prior and prior.get("generation") and observed.get("generation") != prior["generation"] and observed.get("status") != "ended":
        return state
    descriptor = {key: observed.get(key) for key in ("owner", "hostIdentity", "generation", "logicalSessionId", "surfaceLocator", "status")}
    if prior and observed.get("status") == "ended":
        descriptor["generation"] = prior.get("generation")
    digest = content_digest("root.host-observed", descriptor)
    append_fleet_event(state["project_id"], root, source_key=f"root:host:reconcile:{digest}", event_type="root.host-observed", attributes=descriptor)
    return root_state(root)


def _host_end(descriptor: dict[str, Any], *, root: str | None = None) -> bool:
    """Use only Aico's exact owner identity and persisted generation fence."""
    widget = descriptor.get("hostIdentity")
    generation = descriptor.get("generation")
    surface = descriptor.get("owner")
    if not isinstance(generation, str) or not generation:
        return False
    if surface == "aico":
        if not isinstance(widget, str) or not re.fullmatch(r"[0-9a-f]{8}", widget) or not re.fullmatch(r"[0-9a-f]{64}", generation):
            return False
        result = _host_request(surface, f"/v1/sessions/{widget}/end", {"generation": generation}, owner_control=True)
    elif surface == "a-term" and root:
        result = _host_request(surface, f"/v1/roots/{quote(root, safe='')}/end", {"generation": generation})
        return (result.get("status") == "ended" and result.get("owner") == surface
                and result.get("requestId") == root and result.get("hostIdentity") == widget
                and result.get("logicalSessionId") == descriptor.get("logicalSessionId"))
    else:
        return False
    return result == {"status": "ended"}


def _host_prompt(prompt: str, root: str, *, role: str, scope: dict[str, str],
                 lead_root: str | None, facet: str | None, cursor: int) -> str:
    # Support instructions explicitly carry their bounded assignment.
    host_prompt = (
        prompt + f"\nFleet root: {root}. Role: {role}. Scope refs: {json.dumps(scope, sort_keys=True)}. "
        f"Read follow-up instructions with `st sessions wait {root} --cursor {cursor}` "
        "and retain each returned cursor. Return only compact non-secret typed source references or change deltas "
        f"with `st sessions emit {root} EVENT_TYPE --source-key REVISION --attributes JSON`."
    )
    if role == "neri-support-root":
        host_prompt = (
            f"Support facet: {facet}. Lead: {lead_root}. Scope: {json.dumps(scope, sort_keys=True)}. "
            "Do not claim or operate the target. Work only on the supplied facet and source capsule.\n" + host_prompt
        )
    return host_prompt


def start_root(
    project_id: str, project_root: str, *, tool: str, instruction: str,
    scope: dict[str, str], role: RootRole = "portfolio-root", lead_root: str | None = None,
    facet: str | None = None, root: str | None = None,
    surface: RootSurface = "aico", resume_session: str | None = None,
) -> dict[str, Any]:
    """Register one immutable root capsule before an idempotent Aico launch request.

    The lead/facet relationship is descriptive allocation, never target authority.
    An uncertain launch is retained and never automatically recreated. An optional
    exact native resume ID is passed through to the owner's resume adapter in a
    newly allocated root; the capsule retains only its digest.
    """
    if tool not in {"codex", "claude-code"}:
        raise ValueError("Host tool must be codex or claude-code")
    if surface not in {"aico", "a-term"}:
        raise ValueError("Unsupported root surface")
    if role not in {"portfolio-root", "neri-target-root", "neri-support-root"}:
        raise ValueError("Unknown fleet root role")
    prompt = sanitized_instruction(instruction)
    if len(scope) > 32 or not all(len(k) <= 128 and len(v) <= 512 for k, v in scope.items()):
        raise ValueError("Scope must contain bounded source references")
    if role == "neri-support-root":
        if not lead_root or not facet or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", facet):
            raise ValueError("A support root requires a lead and one bounded facet")
        lead = root_state(lead_root)
        if lead["role"] != "neri-target-root" or lead["status"] != "registered" or lead["project_id"] != project_id:
            raise ValueError("Support lead must be an open target root in the same project")
        if not all(scope.get(key) and scope.get(key) == lead["scope"].get(key) for key in ("target", "claim", "run")):
            raise ValueError("Support root must reference the lead's exact target, claim, and run")
    elif lead_root is not None or facet is not None:
        raise ValueError("Only a support root may name a lead or facet")
    if role == "neri-target-root" and not all(scope.get(key) for key in ("target", "claim", "run")):
        raise ValueError("Target root requires exact target, claim, and run references")
    root = root or "root-" + uuid.uuid4().hex
    if not re.fullmatch(r"root-[0-9a-f]{32}", root):
        raise ValueError("Invalid opaque root handle")
    if resume_session is not None:
        if not _KEY.fullmatch(resume_session):
            raise ValueError("Resume requires one exact bounded native session ID")
        # Reject before registering intent: owners refuse a longer resumed prompt.
        widest = _host_prompt(prompt, root, role=role, scope=scope, lead_root=lead_root,
                              facet=facet, cursor=_CURSOR_PLACEHOLDER)
        if len(widest.encode()) > _RESUME_PROMPT_BYTES:
            raise ValueError("Resume instruction plus fleet directions exceed 2000 UTF-8 bytes")
    capsule = {
        "tool": tool, "surface": surface, "project_root": project_root,
        "instruction_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "scope": scope, "role": role, "lead_root": lead_root, "facet": facet,
        "support_only": role == "neri-support-root",
        "offline": role == "neri-support-root",
    }
    if resume_session is not None:
        # Retain no native thread binding; the digest makes a changed retry conflict.
        capsule["resume_session_digest"] = hashlib.sha256(resume_session.encode()).hexdigest()
    event = append_fleet_event(project_id, root, source_key="root:start", event_type="root.started", attributes=capsule)
    # Already observed or failed/uncertain starts never create another host root.
    if len(fleet_root_events(root)) > 1:
        return root_state(root)
    try:
        host_prompt = _host_prompt(prompt, root, role=role, scope=scope, lead_root=lead_root,
                                   facet=facet, cursor=event["sequence"])
        descriptor = _host_start(root, project_id, project_root, tool, host_prompt,
                                 role=role, lead_root=lead_root, facet=facet, surface=surface,
                                 resume_session=resume_session)
    except (httpx.HTTPError, ValueError, OSError):
        append_fleet_event(project_id, root, source_key="root:host", event_type="root.host-unavailable", attributes={
            "capability": "unavailable", "request_id": root, "delivery": "unknown",
        })
    else:
        append_fleet_event(project_id, root, source_key="root:host", event_type="root.host-observed", attributes=descriptor)
    result = root_state(root)
    result["cursor"] = event["sequence"]
    return result


def send_instruction(root: str, instruction: str, *, source_key: str, scope: dict[str, str]) -> dict[str, Any]:
    state = root_state(root)
    if state["status"] != "registered":
        raise ValueError("Fleet root is closed")
    if scope != state["scope"]:
        raise ValueError("Instruction scope must match the root capsule exactly")
    prompt = sanitized_instruction(instruction)
    event = append_fleet_event(state["project_id"], root, source_key=source_key, event_type="instruction.retained", attributes={
        "instruction": prompt, "instruction_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "scope": scope, "capability": "fleet-stream", "native_capability": "unavailable", "delivery": "available-via-wait",
    }, require_open=True)
    return {"root": root, "sequence": event["sequence"], "digest": event["digest"],
            "source_key": source_key, "capability": "fleet-stream", "native_capability": "unavailable", "delivery": "available-via-wait", "retained": True}


def close_root(root: str) -> dict[str, Any]:
    state = reconcile_root(root)
    if state["status"] == "closed":
        return state
    try:
        tombstone = bool(state["host"]) and state["host"].get("status") == "ended"
        ended = tombstone or (bool(state["host"]) and _host_end(state["host"], root=root))
    except (httpx.HTTPError, ValueError, OSError):
        ended = False
    if ended:
        append_fleet_event(state["project_id"], root, source_key="root:close", event_type="root.closed", attributes={
            "host_termination": "owner-tombstone-ended" if tombstone else "generation-fenced-ended", "host": state["host"],
        })
    else:
        append_fleet_event(state["project_id"], root, source_key="root:close-uncertain", event_type="root.close-uncertain", attributes={
            "host_termination": "unconfirmed", "allocation_reusable": False,
        })
    return root_state(root)


def arrange_root(root: str, *, bounds: dict[str, int] | None = None) -> dict[str, Any]:
    """Activate or position through the exact generation-fenced owner surface."""
    state = reconcile_root(root)
    if state["status"] != "registered" or not state["host"] or not state["host"].get("generation"):
        return {"root": root, "capability": "unavailable", "applied": False}
    if bounds is not None:
        if set(bounds) != {"x", "y", "width", "height"} or any(type(v) is not int or abs(v) > 100000 for v in bounds.values()) or bounds["width"] < 360 or bounds["height"] < 240:
            raise ValueError("Bounds require integer x/y and width >= 360, height >= 240 within 100000")
        if state["surface"] == "a-term":
            return {"root": root, "capability": "unsupported", "applied": False}
    action = "position" if bounds is not None else "show"
    payload = {"generation": state["host"]["generation"]}
    if bounds is not None:
        payload["bounds"] = bounds
    try:
        observed = _host_request(state["surface"], f"/v1/roots/{quote(root, safe='')}/{action}", payload)
    except (httpx.HTTPError, ValueError, OSError):
        return {"root": root, "capability": "unavailable", "applied": False}
    applied = all(observed.get(key) == state["host"][key] for key in ("owner", "hostIdentity", "generation"))
    return {"root": root, "capability": "host-acknowledged" if applied else "unavailable", "applied": applied}


async def wait_events(root: str, *, cursor: int = 0, timeout: float = 300, page_size: int = 100) -> dict[str, Any]:
    """Drain every currently committed page; quiet timeout creates no event."""
    if cursor < 0 or not 0 <= timeout <= 300 or not 1 <= page_size <= 1000:
        raise ValueError("Invalid fleet cursor, timeout, or page size")
    state = await asyncio.to_thread(root_state, root)
    deadline = time.monotonic() + timeout
    async def drain() -> list[dict[str, Any]]:
        nonlocal cursor
        records: list[dict[str, Any]] = []
        while True:
            page = await asyncio.to_thread(read_fleet_page, state["project_id"], root, cursor=cursor, limit=page_size)
            records.extend(page)
            if page:
                cursor = page[-1]["sequence"]
            if len(page) < page_size:
                return records

    records = await drain()
    if not records and time.monotonic() < deadline:
        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())), fleet_wake_subscription(root) as subscription:
                # Recheck after subscribe so a commit between the initial read
                # and subscription is observed even when its wake was missed.
                records = await drain()
                while not records and time.monotonic() < deadline:
                    message = await subscription.get_message(ignore_subscribe_messages=True, timeout=max(0, deadline - time.monotonic()))
                    if message is not None:
                        records = await drain()
                if not records:
                    # A publisher can fail to wake a healthy subscriber. One
                    # deadline reconciliation covers that asymmetric failure.
                    records = await drain()
        except TimeoutError:
            records = await drain()
        except (redis.RedisError, OSError):
            # Disconnected Redis has a bounded low-frequency recovery path.
            while not records and time.monotonic() < deadline:
                await asyncio.sleep(min(30, max(0, deadline - time.monotonic())))
                records = await drain()
    return {"root": root, "cursor": cursor, "events": records, "advisory": True}
