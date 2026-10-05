"""Capsule and truthful delivery behavior, plus quiet cancellable multi-page wait."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import fleet_sessions as service
from app.storage import fleet_events as fleet
from app.storage.connection import get_connection


def test_native_reservation_has_one_concurrent_winner_and_retains_receipts(ensure_test_project, monkeypatch):
    trace = "native-send:" + uuid.uuid4().hex
    monkeypatch.setattr(fleet, "get_redis", lambda: MagicMock())
    try:
        def reserve(_):
            return fleet.append_fleet_event(ensure_test_project, trace, source_key="request", event_type="native.delivery.reserved", attributes={"instruction_digest": "fixture"}, return_created=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, range(4)))
        assert sum(result["created"] for result in results) == 1
        assert len({result["id"] for result in results}) == 1
        with pytest.raises(fleet.SourceKeyConflict):
            fleet.append_fleet_event(ensure_test_project, trace, source_key="request", event_type="native.delivery.reserved", attributes={"instruction_digest": "changed"}, return_created=True)
        fleet.append_fleet_event(ensure_test_project, trace, source_key="result", event_type="native.delivery.result", attributes={"delivery": "queued"})
        with get_connection() as conn:
            conn.execute("UPDATE events SET timestamp = NOW() - INTERVAL '40 days' WHERE trace_id = %s", (trace,))
            conn.commit()
        fleet.cleanup_fleet_events()
        assert len(fleet.read_fleet_page(ensure_test_project, trace)) == 2
        assert reserve(0)["created"] is False
    finally:
        with get_connection() as conn:
            conn.execute("DELETE FROM events WHERE trace_id = %s", (trace,))
            conn.commit()


@pytest.fixture
def roots(ensure_test_project, monkeypatch):
    handles = []
    monkeypatch.setattr(fleet, "get_redis", lambda: MagicMock())
    monkeypatch.setattr(service, "_host_start", MagicMock(return_value={
        "owner": "aico", "hostIdentity": "aabbccdd", "generation": "a" * 64,
        "logicalSessionId": "aico-root-fixture", "surfaceLocator": "aico://widget/aabbccdd",
    }))
    monkeypatch.setattr(service, "_host_end", MagicMock(return_value=True))
    monkeypatch.setattr(service, "_host_request", MagicMock(side_effect=httpx.ConnectError("fixture unavailable")))

    def start(**kwargs):
        root = "root-" + uuid.uuid4().hex
        handles.append(root)
        return service.start_root(ensure_test_project, "/fixture/project", root=root, tool="codex", instruction="Review exact source refs.", **kwargs)

    yield start
    with get_connection() as conn:
        conn.execute("DELETE FROM events WHERE trace_id = ANY(%s::text[])", (handles,))
        conn.commit()


def test_unavailable_host_and_send_are_honest_and_idempotent(roots, monkeypatch):
    monkeypatch.setattr(service, "_host_start", MagicMock(side_effect=httpx.ConnectError("fixture unavailable")))
    state = roots(scope={"source": "revision:1"})
    root = state["root"]
    assert state["capabilities"]["launch"] == "unavailable"
    result = service.send_instruction(root, "Check password=private\x1b", source_key="instruction:1", scope=state["scope"])
    assert result["delivery"] == "available-via-wait"
    assert result["capability"] == "fleet-stream"
    assert result["native_capability"] == "unavailable"
    assert result["retained"] is True
    assert service.send_instruction(root, "Check password=private\x1b", source_key="instruction:1", scope=state["scope"]) == result
    event = fleet.read_fleet_page(state["project_id"], root)[-1]
    assert event["attributes"]["instruction"] == "Check [REDACTED]"
    assert event["attributes"]["instruction_digest"] == hashlib.sha256(b"Check [REDACTED]").hexdigest()
    service.close_root(root)
    with pytest.raises(ValueError, match="closed"):
        service.send_instruction(root, "Another instruction", source_key="instruction:2", scope=state["scope"])


def test_same_root_retry_does_not_recreate_uncertain_host(roots, monkeypatch):
    monkeypatch.setattr(service, "_host_start", MagicMock(side_effect=httpx.ConnectError("fixture unavailable")))
    first = roots(scope={})
    retry = service.start_root(first["project_id"], "/fixture/project", root=first["root"], tool="codex", instruction="Review exact source refs.", scope={})
    assert retry["root"] == first["root"]
    cast(MagicMock, service._host_start).assert_called_once()


def test_focus_allocation_dynamic_disjoint_facets_and_reassignment(roots):
    scope = {"target": "target:fixture", "claim": "claim:fixture", "run": "run:fixture"}
    lead = roots(scope=scope, role="neri-target-root")
    with pytest.raises(ValueError, match="open lead"):
        roots(scope=scope, role="neri-target-root")
    first = roots(scope=scope, role="neri-support-root", lead_root=lead["root"], facet="source:module-a")
    second = roots(scope=scope, role="neri-support-root", lead_root=lead["root"], facet="impact:workflow-b")
    assert first["offline"] and second["support_only"]
    with pytest.raises(ValueError, match="facet"):
        roots(scope=scope, role="neri-support-root", lead_root=lead["root"], facet="source:module-a")
    service.close_root(first["root"])
    replacement = roots(scope=scope, role="neri-support-root", lead_root=lead["root"], facet="source:module-a")
    assert replacement["root"] != first["root"]
    # Other target portfolio/lead roots remain independent.
    other = roots(scope={**scope, "target": "target:other"}, role="neri-target-root")
    assert other["root"] != lead["root"]


def test_support_must_match_lead_scope_and_cannot_be_unlinked(roots):
    scope = {"target": "target:a", "claim": "claim:a", "run": "run:a"}
    lead = roots(scope=scope, role="neri-target-root")
    with pytest.raises(ValueError, match="exact target"):
        roots(scope={**scope, "run": "run:b"}, role="neri-support-root", lead_root=lead["root"], facet="fixture")
    with pytest.raises(ValueError, match="requires a lead"):
        roots(scope=scope, role="neri-support-root", facet="fixture")


@pytest.mark.asyncio
async def test_wait_drains_multiple_pages_by_sequence(monkeypatch):
    monkeypatch.setattr(service, "root_state", lambda _root: {"project_id": "fixture"})
    records = [{"sequence": i} for i in range(1, 206)]
    reads = []

    def page(_project, _root, *, cursor, limit):
        reads.append(cursor)
        return [r for r in records if r["sequence"] > cursor][:limit]

    monkeypatch.setattr(service, "read_fleet_page", page)
    result = await service.wait_events("root-fixture", page_size=100)
    assert result["cursor"] == 205
    assert result["events"] == records
    assert reads == [0, 100, 200]


@pytest.mark.asyncio
async def test_wait_timeout_and_cancellation_emit_nothing(monkeypatch):
    monkeypatch.setattr(service, "root_state", lambda _root: {"project_id": "fixture"})
    monkeypatch.setattr(service, "read_fleet_page", lambda *args, **kwargs: [])
    append = MagicMock()
    monkeypatch.setattr(service, "append_fleet_event", append)
    @asynccontextmanager
    async def subscribed(_root):
        class Quiet:
            async def get_message(self, **kwargs):
                await asyncio.sleep(300)
        yield Quiet()
    monkeypatch.setattr(service, "fleet_wake_subscription", subscribed)
    assert (await service.wait_events("root-fixture", cursor=42, timeout=0))["events"] == []
    pending = asyncio.create_task(service.wait_events("root-fixture", cursor=42))
    await asyncio.sleep(0.02)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    append.assert_not_called()


def test_aico_protocol_uses_private_socket_and_verified_descriptor(monkeypatch):
    descriptor = {"owner": "aico", "hostIdentity": "widget:1", "generation": "end:1", "logicalSessionId": "aico-root-1", "surfaceLocator": "aico://widget/1"}
    request = MagicMock()
    request.post.return_value.json.return_value = descriptor
    manager = MagicMock()
    manager.__enter__.return_value = request
    monkeypatch.setenv("AICO_GUI_CONTROL_SOCKET", "/fixture/private.sock")
    transport = MagicMock()
    monkeypatch.setattr(service.httpx, "HTTPTransport", transport)
    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: manager)
    assert service._host_start("root-fixture", "fixture", "/fixture", "codex", "Exact capsule", role="neri-support-root", lead_root="root-lead", facet="source:module-a") == {**descriptor, "status": None}
    transport.assert_called_once_with(uds="/fixture/private.sock")
    assert request.post.call_args.kwargs["json"]["requestId"] == "root-fixture"
    assert request.post.call_args.kwargs["json"]["role"] == "neri-support-root"
    assert request.post.call_args.kwargs["json"]["leadRootReference"] == "root-lead"
    assert request.post.call_args.kwargs["json"]["facetCapsuleRef"] == "source:module-a"


def test_uncertain_close_does_not_release_lead_or_facet(roots, monkeypatch):
    scope = {"target": "target:uncertain", "claim": "claim:a", "run": "run:a"}
    lead = roots(scope=scope, role="neri-target-root")
    support = roots(scope=scope, role="neri-support-root", lead_root=lead["root"], facet="source:a")
    monkeypatch.setattr(service, "_host_end", MagicMock(return_value=False))
    assert service.close_root(support["root"])["status"] == "close-uncertain"
    with pytest.raises(ValueError, match="facet"):
        roots(scope=scope, role="neri-support-root", lead_root=lead["root"], facet="source:a")
    assert service.close_root(lead["root"])["status"] == "close-uncertain"
    with pytest.raises(ValueError, match="open lead"):
        roots(scope=scope, role="neri-target-root")


@pytest.mark.asyncio
async def test_quiet_redis_wait_has_no_short_database_poll(monkeypatch):
    monkeypatch.setattr(service, "root_state", lambda _root: {"project_id": "fixture"})
    read = MagicMock(return_value=[])
    monkeypatch.setattr(service, "read_fleet_page", read)
    subscribed = asyncio.Event()
    released = []

    @asynccontextmanager
    async def subscription(_root):
        class Quiet:
            async def get_message(self, **kwargs):
                subscribed.set()
                await asyncio.sleep(300)
        try:
            yield Quiet()
        finally:
            released.append(True)

    monkeypatch.setattr(service, "fleet_wake_subscription", subscription)
    pending = asyncio.create_task(service.wait_events("root-fixture"))
    await asyncio.wait_for(subscribed.wait(), timeout=1)
    await asyncio.sleep(0.3)
    assert read.call_count == 2
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert released == [True]


@pytest.mark.asyncio
async def test_subscription_gap_and_advisory_wake_recheck_cursor(monkeypatch):
    monkeypatch.setattr(service, "root_state", lambda _root: {"project_id": "fixture"})
    records = []
    reads = []
    def page(_project, _root, *, cursor, limit):
        reads.append(cursor)
        return records if cursor == 0 else []
    monkeypatch.setattr(service, "read_fleet_page", page)
    @asynccontextmanager
    async def subscribed(_root):
        class Wake:
            async def get_message(self, **kwargs):
                records.append({"sequence": 1})
                return {"data": b"ignored-advisory-number"}
        yield Wake()
    monkeypatch.setattr(service, "fleet_wake_subscription", subscribed)
    result = await service.wait_events("root-fixture", timeout=1)
    assert result["cursor"] == 1
    assert reads == [0, 0, 0]


def test_end_uses_exact_generation_fence(monkeypatch):
    request = MagicMock()
    request.post.return_value.json.return_value = {"status": "ended"}
    manager = MagicMock()
    manager.__enter__.return_value = request
    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: manager)
    assert service._host_end({"owner": "aico", "hostIdentity": "aabbccdd", "generation": "b" * 64})
    request.post.assert_called_once_with("http://aico/v1/sessions/aabbccdd/end", json={"generation": "b" * 64})
    assert not service._host_end({"owner": "aico", "hostIdentity": "wrong", "generation": "b" * 64})


def test_initial_prompt_is_transient_and_surface_is_explicit(roots):
    state = roots(scope={})
    event = fleet.fleet_root_events(state["root"])[0]
    assert "instruction" not in event["attributes"]
    assert event["attributes"]["surface"] == "aico"
    assert len(event["attributes"]["instruction_digest"]) == 64


def test_a_term_start_activate_and_end_use_exact_owner_route(monkeypatch):
    descriptor = {"owner": "a-term", "hostIdentity": "session-uuid", "generation": "exact-generation", "logicalSessionId": "a-term-root-1", "surfaceLocator": "a-term://pane/session-uuid"}
    request = MagicMock()
    request.post.return_value.json.return_value = descriptor
    manager = MagicMock()
    manager.__enter__.return_value = request
    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: manager)
    monkeypatch.setenv("A_TERM_ROOT_CONTROL_URL", "http://127.0.0.1:8002")
    assert service._host_start("root-fixture", "fixture", "/fixture", "claude-code", "Source refs", role="portfolio-root", lead_root=None, facet=None, surface="a-term") == {**descriptor, "status": None}
    assert request.post.call_args.args == ("http://127.0.0.1:8002/v1/roots",)
    monkeypatch.setattr(service, "reconcile_root", lambda root: {"status": "registered", "surface": "a-term", "host": descriptor})
    assert service.arrange_root("root-fixture")["applied"]
    assert request.post.call_args.args == ("http://127.0.0.1:8002/v1/roots/root-fixture/show",)
    assert service.arrange_root("root-fixture", bounds={"x": 0, "y": 0, "width": 400, "height": 300})["capability"] == "unsupported"
    request.post.return_value.json.return_value = {**descriptor, "requestId": "root-fixture", "status": "ended", "generation": None}
    assert service._host_end(descriptor, root="root-fixture")
    assert request.post.call_args.args == ("http://127.0.0.1:8002/v1/roots/root-fixture/end",)
    assert request.post.call_args.kwargs["json"] == {"generation": "exact-generation"}


def test_a_term_auth_failure_is_unavailable_without_alternate_route(monkeypatch):
    state = {"status": "registered", "surface": "a-term", "host": {"generation": "generation", "owner": "a-term", "hostIdentity": "session"}}
    monkeypatch.setattr(service, "reconcile_root", lambda root: state)
    request = MagicMock(side_effect=httpx.HTTPStatusError("owner auth required", request=httpx.Request("POST", "http://127.0.0.1:8002"), response=httpx.Response(401)))
    monkeypatch.setattr(service, "_host_request", request)
    result = service.arrange_root("root-fixture")
    assert result == {"root": "root-fixture", "capability": "unavailable", "applied": False}
    assert request.call_count == 1


def test_position_validates_bounds_and_checks_exact_generation(monkeypatch):
    descriptor = {"owner": "aico", "hostIdentity": "aabbccdd", "generation": "a" * 64}
    monkeypatch.setattr(service, "reconcile_root", lambda root: {"status": "registered", "surface": "aico", "host": descriptor})
    request = MagicMock(return_value=descriptor)
    monkeypatch.setattr(service, "_host_request", request)
    bounds = {"x": 100, "y": 100, "width": 400, "height": 300}
    assert service.arrange_root("root-fixture", bounds=bounds)["applied"]
    assert request.call_args.args == ("aico", "/v1/roots/root-fixture/position", {"generation": "a" * 64, "bounds": bounds})
    with pytest.raises(ValueError, match="Bounds"):
        service.arrange_root("root-fixture", bounds={**bounds, "width": 100})
    request.return_value = {**descriptor, "generation": "different"}
    assert not service.arrange_root("root-fixture")["applied"]


@pytest.mark.asyncio
async def test_commit_in_subscribe_gap_is_drained_without_waiting(monkeypatch):
    monkeypatch.setattr(service, "root_state", lambda _root: {"project_id": "fixture"})
    records = []
    monkeypatch.setattr(service, "read_fleet_page", lambda *args, **kwargs: records[:])
    wake = MagicMock()
    @asynccontextmanager
    async def subscribed(_root):
        records.append({"sequence": 1})
        yield wake
    monkeypatch.setattr(service, "fleet_wake_subscription", subscribed)
    result = await service.wait_events("root-fixture", timeout=1)
    assert result["cursor"] == 1
    wake.get_message.assert_not_called()


@pytest.mark.asyncio
async def test_missed_publish_is_reconciled_once_at_deadline(monkeypatch):
    monkeypatch.setattr(service, "root_state", lambda _root: {"project_id": "fixture"})
    read = MagicMock(side_effect=[[], [], [{"sequence": 1}]])
    monkeypatch.setattr(service, "read_fleet_page", read)
    @asynccontextmanager
    async def subscribed(_root):
        class Quiet:
            async def get_message(self, **kwargs):
                await asyncio.sleep(300)
        yield Quiet()
    monkeypatch.setattr(service, "fleet_wake_subscription", subscribed)
    result = await service.wait_events("root-fixture", timeout=0.03)
    assert result["cursor"] == 1
    assert read.call_count == 3


@pytest.mark.asyncio
async def test_redis_failure_uses_bounded_fallback(monkeypatch):
    import redis
    monkeypatch.setattr(service, "root_state", lambda _root: {"project_id": "fixture"})
    read = MagicMock(side_effect=[[], [{"sequence": 1}]])
    monkeypatch.setattr(service, "read_fleet_page", read)
    @asynccontextmanager
    async def unavailable(_root):
        raise redis.ConnectionError("fixture unavailable")
        yield  # pragma: no cover
    monkeypatch.setattr(service, "fleet_wake_subscription", unavailable)
    result = await service.wait_events("root-fixture", timeout=0.03)
    assert result["cursor"] == 1
    assert read.call_count == 2


def test_uncertain_root_reconciliation_uses_get_and_pins_identity(roots, monkeypatch):
    monkeypatch.setattr(service, "_host_start", MagicMock(side_effect=httpx.ConnectError("fixture unavailable")))
    state = roots(scope={})
    descriptor = {
        "owner": "aico", "requestId": state["root"], "role": "portfolio-root", "leadRootReference": None,
        "facetCapsuleRef": None, "hostIdentity": "aabbccdd", "generation": "a" * 64,
        "logicalSessionId": "aico-root-fixture", "surfaceLocator": "aico://widget/aabbccdd", "status": "running",
    }
    request = MagicMock(return_value=descriptor)
    monkeypatch.setattr(service, "_host_request", request)
    reconciled = service.reconcile_root(state["root"])
    assert reconciled["host"]["generation"] == "a" * 64
    assert request.call_args.kwargs == {"method": "GET"}
    cast(MagicMock, service._host_start).assert_called_once()
    request.return_value = {**descriptor, "generation": "b" * 64}
    assert service.reconcile_root(state["root"])["host"]["generation"] == "a" * 64


@pytest.mark.asyncio
async def test_master_instruction_and_root_delta_share_idempotent_wait_stream(roots):
    state = roots(scope={"source": "source:fixture"})
    before = fleet.read_fleet_page(state["project_id"], state["root"])[-1]["sequence"]
    instruction = service.send_instruction(state["root"], "Review the new business workflow reference.", source_key="instruction:revision:1", scope=state["scope"])
    assert service.send_instruction(state["root"], "Review the new business workflow reference.", source_key="instruction:revision:1", scope=state["scope"]) == instruction
    with pytest.raises(fleet.SourceKeyConflict):
        service.send_instruction(state["root"], "Different instruction.", source_key="instruction:revision:1", scope=state["scope"])
    received = await service.wait_events(state["root"], cursor=before, timeout=0)
    assert len(received["events"]) == 1
    assert received["events"][0]["attributes"]["instruction"] == "Review the new business workflow reference."
    delta = fleet.append_fleet_event(state["project_id"], state["root"], source_key="support:revision:2", event_type="support.delta", attributes={"source_ref": "source:fixture:2", "kind": "business-change"})
    fan_in = await service.wait_events(state["root"], cursor=received["cursor"], timeout=0)
    assert fan_in["events"] == [delta]


def test_matching_provider_tombstone_confirms_close_without_end_retry(roots, monkeypatch):
    state = roots(scope={})
    descriptor = {
        "owner": "aico", "requestId": state["root"], "role": "portfolio-root", "leadRootReference": None,
        "facetCapsuleRef": None, "hostIdentity": "aabbccdd", "generation": None,
        "logicalSessionId": "aico-root-fixture", "surfaceLocator": "aico://widget/aabbccdd", "status": "ended",
    }
    monkeypatch.setattr(service, "_host_request", MagicMock(return_value=descriptor))
    end = MagicMock(side_effect=AssertionError("An already-ended owner must not be ended again"))
    monkeypatch.setattr(service, "_host_end", end)
    assert service.close_root(state["root"])["status"] == "closed"
    end.assert_not_called()
