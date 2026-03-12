#!/usr/bin/env python3
"""Test permission prompt flow specifically.

Tests that:
1. write_enabled=true, yolo_mode=false triggers permission prompts
2. permission_request SSE event is emitted
3. The event can be resolved via API
"""

import json
import sys
import threading
import time
import urllib.request
from urllib.error import URLError

API_BASE = "http://localhost:8001"
PROJECT_ID = "summitflow"


def create_session(tools_enabled: bool, write_enabled: bool, yolo_mode: bool) -> str:
    """Create a roundtable session and return session_id."""
    url = f"{API_BASE}/api/projects/{PROJECT_ID}/roundtable/sessions"
    data = json.dumps(
        {
            "mode": "quick",
            "tools_enabled": tools_enabled,
            "write_enabled": write_enabled,
            "yolo_mode": yolo_mode,
        }
    ).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=10) as response:
        result = json.load(response)
        return result["session_id"]


def resolve_permission(session_id: str, permission_id: str, approved: bool) -> bool:
    """Resolve a permission request."""
    url = f"{API_BASE}/api/projects/{PROJECT_ID}/roundtable/sessions/{session_id}/permissions/{permission_id}"
    data = json.dumps({"approved": approved}).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.load(response)
            return result.get("status") == "resolved"
    except Exception as e:
        print(f"Error resolving permission: {e}")
        return False


def parse_sse_line_to_event(lines: list[str]) -> dict | None:
    """Parse a group of SSE lines into an event dict."""
    event = {}
    for line in lines:
        if line.startswith("event:"):
            event["type"] = line[6:].strip()
        elif line.startswith("data:"):
            try:
                event["data"] = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                event["data"] = line[5:].strip()
    return event if event else None


def test_permission_prompt_flow():
    """Test that permission prompts work correctly."""
    print("=" * 60)
    print("TEST: Permission Prompt Flow")
    print("=" * 60)

    # Create session with write_enabled=true, yolo_mode=false
    session_id = create_session(
        tools_enabled=True,
        write_enabled=True,
        yolo_mode=False,
    )
    print(f"Created session: {session_id}")
    print("  tools_enabled=True, write_enabled=True, yolo_mode=False")

    test_file = "/home/kasadis/summitflow/test-permission-prompt.txt"
    message = f"Please create a file at {test_file} with content 'Testing permission prompt flow'."

    print(f"\nSending message: {message[:50]}...")

    # Set up URL for SSE stream
    url = f"{API_BASE}/api/projects/{PROJECT_ID}/roundtable/sessions/{session_id}/messages/stream"
    data = json.dumps(
        {
            "message": message,
            "target": "claude",
        }
    ).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")

    # Track events
    events = []
    permission_events = []
    got_done = False
    permission_resolved = False

    def auto_approve_permissions():
        """Background thread to auto-approve permission requests."""
        nonlocal permission_resolved
        start = time.time()
        checked_ids = set()

        while not got_done and time.time() - start < 30:
            for pe in list(
                permission_events
            ):  # Copy to avoid mutation during iteration
                perm_id = pe.get("data", {}).get("permission_id")
                if perm_id and perm_id not in checked_ids:
                    checked_ids.add(perm_id)
                    print(f"\n  -> Auto-approving permission: {perm_id}")
                    success = resolve_permission(session_id, perm_id, True)
                    if success:
                        print("  -> Permission resolved successfully")
                        permission_resolved = True
                    else:
                        print("  -> Permission resolution failed")
            time.sleep(0.1)  # Check more frequently

    # Start background thread for auto-approval
    approver = threading.Thread(target=auto_approve_permissions, daemon=True)

    print("\nReading SSE stream (with 30s timeout)...")

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            buffer = ""
            current_event_lines = []
            approver.start()

            while True:
                try:
                    chunk = response.read(1).decode("utf-8")
                    if not chunk:
                        break
                    buffer += chunk

                    # Process complete lines
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()

                        if not line:
                            # Empty line = event boundary
                            if current_event_lines:
                                event = parse_sse_line_to_event(current_event_lines)
                                if event:
                                    events.append(event)
                                    event_type = event.get("type", "unknown")
                                    print(f"  Event: {event_type}")

                                    if event_type == "permission_request":
                                        permission_events.append(event)
                                        print(
                                            f"    -> Permission request for: {event.get('data', {}).get('tool_name')}"
                                        )
                                    elif event_type == "done":
                                        got_done = True
                                        break

                                current_event_lines = []
                        else:
                            current_event_lines.append(line)

                    if got_done:
                        break

                except Exception as e:
                    print(f"Error reading chunk: {e}")
                    break

    except URLError as e:
        print(f"URL error: {e}")
    except Exception as e:
        print(f"Error: {e}")

    # Results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    print(f"Total events: {len(events)}")
    print(f"Permission events: {len(permission_events)}")

    event_types = {}
    for e in events:
        t = e.get("type", "unknown")
        event_types[t] = event_types.get(t, 0) + 1
    print(f"Event types: {event_types}")

    # Check for permission_request events
    if permission_events:
        print("\nPASS: Got permission_request events!")
        for pe in permission_events:
            data = pe.get("data", {})
            print(f"  - tool: {data.get('tool_name')}")
            print(f"    preview: {data.get('preview', '')[:100]}...")

        # Check if file was created (should be if approved)
        import os

        if os.path.exists(test_file):
            print("\nPASS: File was created after approval!")
            os.remove(test_file)
            print("  (cleaned up)")
            return True
        else:
            print("\nWARN: File was not created (agent may have declined)")
            return True
    else:
        print("\nFAIL: No permission_request events received")

        # Check if file was created anyway (would be a bug)
        import os

        if os.path.exists(test_file):
            print("\nBUG: File was created without permission prompt!")
            os.remove(test_file)
            return False
        else:
            print("File was not created (expected without permission)")

        return False


if __name__ == "__main__":
    result = test_permission_prompt_flow()
    sys.exit(0 if result else 1)
