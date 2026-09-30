"""Deliver durable wire receipts through Agent Hub's async SDK and ledger."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from codex_managed_outbox import ManagedOutbox


async def deliver(outbox: ManagedOutbox, client, *, execution_owner_secret: str, session_id: str | None = None, register_only: bool = False) -> int:
    """A lost response leaves the original envelope pending for exact replay."""
    from agent_hub.models.native_observation import NativeObservationBatch, NativeSourceRegistration

    accepted = 0
    lease = outbox.delivery_lease()
    await asyncio.to_thread(lease.__enter__)
    try:
        for thread in await asyncio.to_thread(outbox.threads):
            if session_id is not None and thread["id"] != session_id:
                continue
            try:
                session = await client.get_session(thread["id"])
                if session.project_id != thread["project"] or session.provider != "codex":
                    await asyncio.to_thread(outbox.delivery_health, "project_binding_conflict")
                    continue
                registration = NativeSourceRegistration.model_validate(json.loads(thread["registration"]))
                source = await client.register_native_source(thread["id"], registration, execution_owner_secret=execution_owner_secret)
                await asyncio.to_thread(outbox.bind_source, thread["id"], source.model_dump(mode="json"))
                # Preserve the rollout namespace. The rollout adapter still owns
                # projection and its cursor, and verifies this path independently.
                path = (session.provider_metadata or {}).get("transcript_path")
                if path:
                    rollout = registration.model_copy(update={"source_kind": "rollout", "transcript_path": path, "epoch": "rollout", "producer_id": "summitflow/codex-session-sync", "reconcile_existing_rollout": True})
                    await client.register_native_source(thread["id"], rollout, execution_owner_secret=execution_owner_secret)
                if register_only:
                    continue
                while (observation := await asyncio.to_thread(outbox.pending, thread["id"])) is not None and observation["position"] < thread["next_position"]:
                    batch = NativeObservationBatch.model_validate({"observations": [observation], "acknowledged_position": thread["acknowledged"]})
                    result = await client.ingest_native_observations(thread["id"], source.source_id, batch, execution_owner_secret=execution_owner_secret)
                    if not await asyncio.to_thread(outbox.accept, thread["id"], observation["position"], result.model_dump(mode="json")):
                        break
                    accepted += 1
            except Exception:
                await asyncio.to_thread(outbox.delivery_health, "delivery_unavailable")
                # Other owned threads remain independent. No sleep or retry loop;
                # the existing sync timer retries the exact pending receipt.
    finally:
        await asyncio.to_thread(lease.__exit__, None, None, None)
    return accepted


def configured_outbox() -> ManagedOutbox | None:
    path = os.environ.get("SUMMITFLOW_CODEX_OUTBOX")
    if not path:
        return None
    return ManagedOutbox(Path(path), max_bytes=int(os.environ["SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES"]), retention_seconds=int(os.environ["SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS"]))


def recover_configured_outbox(api_url: str, *, session_id: str | None = None, register_only: bool = False) -> dict | None:
    """Called by the existing host collector even when managed capture is off."""
    from codex_sync_api import HTTP_TIMEOUT
    from dotenv import dotenv_values

    outbox = configured_outbox()
    if outbox is None:
        return None
    # Use the existing approved secret source, never a log or alternate credential.
    credentials = dotenv_values(Path.home() / ".env.local")
    secret = os.environ.get("INTERNAL_SERVICE_SECRET") or credentials.get("INTERNAL_SERVICE_SECRET")
    client_id = os.environ.get("SUMMITFLOW_CLIENT_ID") or credentials.get("SUMMITFLOW_CLIENT_ID")
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
