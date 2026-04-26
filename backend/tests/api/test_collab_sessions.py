from __future__ import annotations

from app.storage.connection import get_connection


def _anchor() -> dict[str, object]:
    return {
        "x": 120,
        "y": 90,
        "width": 240,
        "height": 120,
        "viewport_width": 1440,
        "viewport_height": 900,
        "scroll_x": 0,
        "scroll_y": 180,
    }


def _clear_collab_rows(project_id: str) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM collab_sessions WHERE project_id = %s OR project_id IS NULL",
            (project_id,),
        )
        conn.commit()


def test_project_design_review_session_create_annotate_grant_and_teardown(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_collab_rows(project_id)

    created = client.post(
        f"/api/projects/{project_id}/collab/sessions",
        headers={"X-User-Name": "Elias Leslie"},
        json={
            "title": "Homepage review",
            "target_url": "http://localhost:3001/projects/test-project/design",
            "target_mode": "live_browser",
            "sensitive": True,
        },
    )

    assert created.status_code == 201
    session = created.json()
    assert session["session_id"].startswith("collab-")
    assert session["project_id"] == project_id
    assert session["target_mode"] == "live_browser"
    assert session["media_strategy"] == "webrtc_staged"
    assert session["evidence_policy"] == "sensitive_blocked"
    assert session["created_by_display"] == "Elias Leslie"

    listed = client.get(f"/api/projects/{project_id}/collab/sessions")
    assert listed.status_code == 200
    assert [item["session_id"] for item in listed.json()] == [session["session_id"]]

    annotation = client.post(
        f"/api/collab/sessions/{session['session_id']}/annotations",
        json={
            "kind": "box",
            "page_key": "/projects/test-project/design",
            "page_url_snapshot": "http://localhost:3001/projects/test-project/design",
            "selector": "[data-testid='design-review']",
            "anchor": _anchor(),
            "comment": "Agent question target.",
        },
    )
    assert annotation.status_code == 201
    assert annotation.json()["annotation_id"].startswith("annotation-")

    evidence_blocked = client.post(
        f"/api/collab/sessions/{session['session_id']}/evidence-packets",
        json={
            "annotation_id": annotation.json()["annotation_id"],
            "url": "http://localhost:3001/projects/test-project/design",
            "viewport": {"width": 1440, "height": 900},
            "selector": "[data-testid='design-review']",
            "bbox": {"x": 120, "y": 90, "width": 240, "height": 120},
            "context_summary": "Compact summary only.",
        },
    )
    assert evidence_blocked.status_code == 423

    grant = client.post(
        f"/api/collab/sessions/{session['session_id']}/control-grant",
        json={"owner": "agent", "ttl_seconds": 120},
    )
    assert grant.status_code == 200
    assert grant.json()["control_owner"] == "agent"
    assert grant.json()["control_expires_at"] is not None

    detail = client.get(f"/api/collab/sessions/{session['session_id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["participants"][0]["display_name"] == "Elias Leslie"
    agent_presence = client.post(
        f"/api/collab/sessions/{session['session_id']}/participants",
        json={"actor_kind": "agent", "display_name": "Codex", "role": "viewer"},
    )
    assert agent_presence.status_code == 201
    assert agent_presence.json()["participant_id"].startswith("participant-")
    assert agent_presence.json()["participant_key"] == "agent:viewer:codex"

    detail = client.get(f"/api/collab/sessions/{session['session_id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert {item["display_name"] for item in body["participants"]} >= {
        "Codex",
        "Elias Leslie",
    }
    assert body["annotations"][0]["comment"] == "Agent question target."
    assert {event["action"] for event in body["audit_events"]} >= {
        "created",
        "annotation-created",
        "control-granted",
    }

    teardown = client.post(f"/api/collab/sessions/{session['session_id']}/teardown")
    assert teardown.status_code == 200
    assert teardown.json()["state"] == "closed"
    assert teardown.json()["control_owner"] is None


def test_non_sensitive_session_creates_compact_evidence_packet(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_collab_rows(project_id)

    created = client.post(
        "/api/collab/sessions",
        json={
            "project_id": project_id,
            "title": "Evidence packet smoke",
            "target_url": "http://localhost:3001",
            "target_mode": "manual",
            "sensitive": False,
        },
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    evidence = client.post(
        f"/api/collab/sessions/{session_id}/evidence-packets",
        json={
            "title": "Header crop",
            "url": "http://localhost:3001",
            "viewport": {"width": 1280, "height": 720},
            "selector": "header",
            "bbox": {"x": 0, "y": 0, "width": 1280, "height": 72},
            "context_summary": "Header nav active state is visible; no DOM dump attached.",
            "artifact_id": "artifact-123",
        },
    )

    assert evidence.status_code == 201
    packet = evidence.json()
    assert packet["evidence_id"].startswith("evidence-")
    assert packet["context_summary"] == "Header nav active state is visible; no DOM dump attached."
    assert packet["token_estimate"] < 30
    assert "DOM" not in packet


def test_collab_session_event_websocket_connects_and_pongs(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_collab_rows(project_id)

    created = client.post(
        "/api/collab/sessions",
        json={
            "project_id": project_id,
            "title": "Event channel smoke",
            "target_url": "about:blank",
            "sensitive": False,
        },
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    with client.websocket_connect(f"/api/collab/sessions/{session_id}/events") as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"
        assert connected["session_id"] == session_id

        websocket.send_json({"type": "ping"})
        pong = websocket.receive_json()
        assert pong["type"] == "pong"
        assert pong["session_id"] == session_id


def test_collab_session_rejects_non_http_target_and_large_context(
    client,
    ensure_test_project: str,
) -> None:
    project_id = ensure_test_project
    _clear_collab_rows(project_id)

    bad_target = client.post(
        "/api/collab/sessions",
        json={
            "project_id": project_id,
            "title": "Bad target",
            "target_url": "file:///etc/passwd",
        },
    )
    assert bad_target.status_code == 400

    created = client.post(
        "/api/collab/sessions",
        json={
            "project_id": project_id,
            "title": "Compact only",
            "target_url": "about:blank",
            "sensitive": False,
        },
    )
    assert created.status_code == 201

    too_large = client.post(
        f"/api/collab/sessions/{created.json()['session_id']}/evidence-packets",
        json={
            "context_summary": "x" * 700,
        },
    )
    assert too_large.status_code == 422
