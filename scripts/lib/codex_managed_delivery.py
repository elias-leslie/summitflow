"""Deliver durable wire receipts through Agent Hub's async SDK and ledger."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from codex_managed_outbox import ManagedOutbox
from codex_managed_update import ManagedUpdateError as ManagedUpdateError


async def deliver(outbox: ManagedOutbox, client, *, execution_owner_secret: str, session_id: str | None = None, register_only: bool = False) -> int:
    """A lost response leaves the original envelope pending for exact replay."""
    from agent_hub.models.native_observation import NativeObservationBatch, NativeSourceRegistration

    accepted = 0
    lease = outbox.delivery_lease()
    await asyncio.to_thread(lease.__enter__)
    try:
        for thread in await asyncio.to_thread(outbox.streams):
            if session_id is not None and thread["id"] != session_id:
                continue
            try:
                session = await client.get_session(thread["id"])
                if session.project_id != thread["project"] or session.provider != "codex":
                    await asyncio.to_thread(outbox.delivery_health, "project_binding_conflict")
                    continue
                registration = NativeSourceRegistration.model_validate(json.loads(thread["registration"]))
                generation = thread["generation"]
                if generation:
                    predecessor = await asyncio.to_thread(outbox.predecessor, thread["id"], generation)
                    if not predecessor:
                        await asyncio.to_thread(outbox.delivery_health, "predecessor_registration_pending")
                        continue
                    registration = registration.model_copy(update={"predecessor_source_id": predecessor})
                source = await client.register_native_source(thread["id"], registration, execution_owner_secret=execution_owner_secret)
                await asyncio.to_thread(outbox.bind_source, thread["id"], source.model_dump(mode="json"), generation)
                # Preserve the rollout namespace. The rollout adapter still owns
                # projection and its cursor, and verifies this path independently.
                path = (session.provider_metadata or {}).get("transcript_path")
                if path and generation == 0:
                    rollout = registration.model_copy(update={"source_kind": "rollout", "transcript_path": path, "epoch": "rollout", "producer_id": "summitflow/codex-session-sync", "reconcile_existing_rollout": True, "generation": 0, "predecessor_source_id": None})
                    await client.register_native_source(thread["id"], rollout, execution_owner_secret=execution_owner_secret)
                if register_only:
                    continue
                while (observation := await asyncio.to_thread(outbox.pending, thread["id"], generation)) is not None and observation["position"] < thread["next_position"]:
                    batch = NativeObservationBatch.model_validate({"observations": [observation], "acknowledged_position": thread["acknowledged"]})
                    result = await client.ingest_native_observations(thread["id"], source.source_id, batch, execution_owner_secret=execution_owner_secret)
                    if not await asyncio.to_thread(outbox.accept, thread["id"], observation["position"], result.model_dump(mode="json"), generation):
                        break
                    thread["acknowledged"] = observation["position"]
                    accepted += 1
            except Exception:
                await asyncio.to_thread(outbox.delivery_health, "delivery_unavailable")
                # Other owned threads remain independent. No sleep or retry loop;
                # the existing sync timer retries the exact pending receipt.
        if not register_only and session_id is None and await asyncio.to_thread(outbox.quarantines):
            from agent_hub.models.native_observation import (
                NativeQuarantineBatch,
                NativeQuarantineRegistration,
            )

            for row in await asyncio.to_thread(outbox.quarantines):
                # Legacy unbound evidence had no truthful project/profile binding.
                # Retain it for explicit association rather than invent provenance.
                if not row["registration"]:
                    await asyncio.to_thread(outbox.delivery_health, "quarantine_binding_required")
                    continue
                try:
                    registration = NativeQuarantineRegistration.model_validate(json.loads(row["registration"]))
                    source = await client.register_native_quarantine(registration, execution_owner_secret=execution_owner_secret)
                    await asyncio.to_thread(outbox.bind_quarantine, row["id"], source.model_dump(mode="json"))
                    batch = NativeQuarantineBatch.model_validate({"observations": [{"position": row["position"], "payload": json.loads(row["payload"]), "source_reference": json.loads(row["source_reference"])}]})
                    result = await client.ingest_native_quarantine(source.source_id, batch, execution_owner_secret=execution_owner_secret)
                    if await asyncio.to_thread(outbox.accept_quarantine, row["id"], result.model_dump(mode="json")):
                        accepted += 1
                except Exception:
                    await asyncio.to_thread(outbox.delivery_health, "quarantine_delivery_unavailable")
                    break
        await asyncio.to_thread(outbox.reclaim)
    finally:
        await asyncio.to_thread(lease.__exit__, None, None, None)
    return accepted


def managed_settings() -> dict:
    """Existing trusted host settings, with explicit process overrides."""
    from dotenv import dotenv_values

    values = dotenv_values(Path.home() / ".env.local")
    values.update(os.environ)
    return values


def configured_paths() -> dict[str, Path]:
    settings = managed_settings()
    raw = settings.get("SUMMITFLOW_CODEX_OUTBOXES_JSON")
    if not raw:
        return {}
    mapping = json.loads(raw)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("managed_outbox_project_mapping_invalid")
    paths = {}
    for project, value in mapping.items():
        if not isinstance(project, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project) or not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("managed_outbox_project_mapping_invalid")
        paths[project] = Path(value)
    if len({path.resolve() for path in paths.values()}) != len(paths):
        raise ValueError("managed_outbox_projects_require_independent_paths")
    return paths


def configured_path(project_id: str | None = None) -> Path | None:
    paths = configured_paths()
    if paths:
        selected = project_id or ("agent-hub" if "agent-hub" in paths else sorted(paths)[0])
        return paths.get(selected)
    value = managed_settings().get("SUMMITFLOW_CODEX_OUTBOX")
    return Path(value) if value else None


def configured_outbox(project_id: str | None = None) -> ManagedOutbox | None:
    paths = configured_paths()
    selected = project_id or ("agent-hub" if "agent-hub" in paths else next(iter(sorted(paths)), None))
    path = configured_path(selected)
    if path is None:
        return None
    settings = managed_settings()
    outbox = ManagedOutbox(path, max_bytes=int(settings["SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES"]), retention_seconds=int(settings["SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS"]))
    if paths:
        projects = {thread["project"] for thread in outbox.threads()}
        bound = outbox.metadata("project").get("project_id")
        if bound:
            projects.add(bound)
        if projects - {selected}:
            raise ValueError("managed_outbox_project_binding_mismatch")
        if not bound:
            outbox.metadata("project", {"project_id": selected})
    return outbox


def agent_hub_frontend_url() -> str:
    """Use the registered operator frontend, which is distinct from its API."""
    try:
        from app.project_identity import get_project_identity

        identity = get_project_identity("agent-hub") or {}
        host = (identity.get("hosts") or {}).get("production_frontend")
        if isinstance(host, str) and host:
            if "://" in host:
                return host.rstrip("/")
            return ("http://" if host.startswith(("localhost", "127.0.0.1")) else "https://") + host
        from app.config import AGENT_HUB_FRONTEND_PORT

        return f"http://localhost:{AGENT_HUB_FRONTEND_PORT}"
    except (ImportError, ValueError, OSError):
        return ""


def operator_status(outbox: ManagedOutbox | None = None, *, project_id: str | None = None) -> dict:
    """Shared content-free local owner contract for HTTP and the existing CLI."""
    from codex_managed_capture import capture_enabled, codex_binary, conformance

    paths = configured_paths()
    selected = project_id or ("agent-hub" if "agent-hub" in paths else next(iter(sorted(paths)), None))
    outbox = outbox or configured_outbox(selected)
    result = {"available": outbox is not None, "project_id": selected, "configured_projects": sorted(paths), "installed_version": None, "installed_schema_fingerprint": None, "installed_protocol_status": "unavailable", "capture_enabled": capture_enabled(), "health": "rollout_only", "delivery_health": "unavailable", "capture_disabled": False, "capture_gaps": 0, "pending": 0, "pending_bytes": 0, "quarantined": 0, "quarantined_bytes": 0, "used_bytes": 0, "quota_bytes": 0, "raw_retention_seconds": 0, "physical_bytes": 0, "process_active": False, "threads": [], "actions": [], "promotion_state": "agent_hub_controlled", "agent_hub_url": agent_hub_frontend_url(), "update": {"state": "unavailable", "latest_version": None, "candidate_version": None, "active_version": None, "previous_version": None, "error_code": None}}
    try:
        import subprocess

        binary = codex_binary()
        result["installed_version"] = subprocess.run([binary, "--version"], capture_output=True, check=True, text=True, timeout=10).stdout.strip()
        _, fingerprint, _ = conformance(binary, outbox=outbox)
        result.update(installed_schema_fingerprint=fingerprint, installed_protocol_status="compatible")
    except (ValueError, OSError, subprocess.SubprocessError, ImportError):
        result["installed_protocol_status"] = "unsupported" if result["installed_version"] else "unavailable"
    if outbox:
        from codex_managed_update import update_actions, update_status

        result.update(outbox.status())
        result["update"] = update_status(outbox)
        projects = {thread["project"] for thread in outbox.threads()}
        bound = outbox.metadata("project").get("project_id")
        if bound:
            projects.add(bound)
        if len(projects) == 1:
            result["project_id"] = next(iter(projects))
            if not paths:
                result["configured_projects"] = [result["project_id"]]
            if project_id and result["project_id"] != project_id:
                result.update(available=False, project_id=project_id, actions=[])
                return result
            result["actions"] = ["enable" if result["capture_disabled"] else "disable", "drain"]
            result["actions"].extend(update_actions(outbox))
    return result


def operator_action(action: str, *, project_id: str) -> dict:
    """Act only on the configured project process owner; never a path from HTTP."""
    outbox = configured_outbox(project_id)
    if outbox is None:
        raise ValueError("managed_outbox_unavailable")
    projects = {thread["project"] for thread in outbox.threads()}
    bound = outbox.metadata("project").get("project_id")
    if bound:
        projects.add(bound)
    if projects != {project_id}:
        raise ValueError("managed_outbox_project_binding_mismatch")
    if action == "disable":
        outbox.disable_capture()
    elif action == "enable":
        outbox.enable_capture()
    elif action == "drain":
        recover_configured_outbox(os.environ.get("AGENT_HUB_API", "http://localhost:8003/api"), project_id=project_id)
    elif action in {"check-update", "stage-update", "qualify-update", "promote-update", "rollback-update"}:
        from codex_managed_update import update_action

        update_action(outbox, action)
    else:
        raise ValueError("managed_action_unsupported")
    return operator_status(outbox, project_id=project_id)


def owner_credentials() -> tuple[str | None, str | None]:
    from dotenv import dotenv_values
    # Use the existing approved secret source, never a log or alternate credential.
    credentials = dotenv_values(Path.home() / ".env.local")
    secret = os.environ.get("INTERNAL_SERVICE_SECRET") or credentials.get("INTERNAL_SERVICE_SECRET")
    client_id = os.environ.get("SUMMITFLOW_CLIENT_ID") or credentials.get("SUMMITFLOW_CLIENT_ID")
    return secret, client_id


def recover_configured_outbox(api_url: str, *, project_id: str | None = None, session_id: str | None = None, register_only: bool = False) -> dict | None:
    """Called by the existing host collector even when managed capture is off."""
    from codex_sync_api import HTTP_TIMEOUT

    outbox = configured_outbox(project_id)
    if outbox is None:
        return None
    secret, client_id = owner_credentials()
    if not secret or not client_id:
        outbox.delivery_health("delivery_credentials_unavailable")
        return outbox.status()

    async def run():
        from agent_hub import AsyncAgentHubClient

        async with AsyncAgentHubClient(base_url=api_url.removesuffix("/api"), client_id=client_id, client_name="summitflow/codex-managed", request_source="codex-managed-capture", timeout=HTTP_TIMEOUT) as client:
            await deliver(outbox, client, execution_owner_secret=secret, session_id=session_id, register_only=register_only)

    try:
        asyncio.run(run())
    except Exception:
        outbox.delivery_health("delivery_unavailable")
    return outbox.status()


def recover_configured_outboxes(api_url: str) -> list[dict]:
    """Existing collector drains independent configured owners even if one fails."""
    results = []
    for project in sorted(configured_paths()) or [None]:
        try:
            status = recover_configured_outbox(api_url, project_id=project)
            if status:
                results.append(status)
        except (ValueError, KeyError, OSError, RuntimeError):
            results.append({"project_id": project, "health": "delivery_unavailable", "pending": 0, "capture_gaps": 0})
    return results
