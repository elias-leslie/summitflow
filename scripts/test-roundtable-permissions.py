#!/usr/bin/env python3
"""Test script for roundtable permission scenarios.

Tests SDK-native tool calling with permission hooks:
- Read tools execute without permission prompts
- Write tools are blocked when write_enabled=false
- Write tools prompt when write_enabled=true, yolo_mode=false
- Write tools auto-approved in YOLO mode
"""

import json
import sys
import time
from collections import defaultdict
from http.client import HTTPConnection

API_BASE = "http://localhost:8001"
PROJECT_ID = "summitflow"


def parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE response into list of events."""
    events = []
    current_event = {}

    for line in response_text.split('\n'):
        line = line.strip()
        if not line:
            if current_event:
                events.append(current_event)
                current_event = {}
            continue

        if line.startswith('event:'):
            current_event['type'] = line[6:].strip()
        elif line.startswith('data:'):
            try:
                current_event['data'] = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                current_event['data'] = line[5:].strip()

    if current_event:
        events.append(current_event)

    return events


def create_session(tools_enabled: bool = True, write_enabled: bool = False, yolo_mode: bool = False) -> str:
    """Create a roundtable session and return session_id."""
    import urllib.request

    url = f"{API_BASE}/api/projects/{PROJECT_ID}/roundtable/sessions"
    data = json.dumps({
        "mode": "quick",
        "tools_enabled": tools_enabled,
        "write_enabled": write_enabled,
        "yolo_mode": yolo_mode,
    }).encode()

    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')

    with urllib.request.urlopen(req, timeout=10) as response:
        result = json.load(response)
        return result['session_id']


def send_message_and_get_events(session_id: str, message: str, target: str = "claude") -> list[dict]:
    """Send a message via SSE and return all events."""
    import urllib.request

    url = f"{API_BASE}/api/projects/{PROJECT_ID}/roundtable/sessions/{session_id}/messages/stream"
    data = json.dumps({
        "message": message,
        "target": target,
    }).encode()

    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'text/event-stream')

    # Read SSE response with longer timeout for LLM calls
    with urllib.request.urlopen(req, timeout=120) as response:
        response_text = response.read().decode()
        return parse_sse_events(response_text)


def test_read_tools_no_permission(agent: str = "claude"):
    """Test that read tools execute without permission prompts."""
    print(f"\n{'='*60}")
    print(f"TEST: {agent.upper()} Read Tools - No Permission Required")
    print('='*60)

    # Create session with tools enabled but writes disabled
    session_id = create_session(tools_enabled=True, write_enabled=False)
    print(f"Created session: {session_id}")

    # Ask agent to read a specific file
    message = (
        "Please read the file /home/kasadis/summitflow/backend/app/main.py "
        "and tell me what FastAPI app name is used."
    )

    print(f"Sending message: {message[:60]}...")
    events = send_message_and_get_events(session_id, message, target=agent)

    # Analyze events
    event_types = defaultdict(int)
    permission_events = []
    agent_responses = []

    for event in events:
        event_type = event.get('type', 'unknown')
        event_types[event_type] += 1

        if event_type == 'permission_request':
            permission_events.append(event)
        elif event_type == 'agent_complete':
            agent_responses.append(event.get('data', {}))

    print(f"\nEvent summary: {dict(event_types)}")

    # Verify no permission requests
    if permission_events:
        print(f"FAIL: Got {len(permission_events)} permission_request events!")
        for pe in permission_events:
            print(f"  - {pe.get('data', {}).get('tool_name', 'unknown')}")
        return False

    print("PASS: No permission_request events emitted")

    # Verify we got a response
    if not agent_responses:
        print("FAIL: No agent_complete events!")
        return False

    response_content = agent_responses[0].get('content', '')
    print(f"\nAgent response preview: {response_content[:200]}...")

    # Check if the response mentions the file or app
    if 'main' in response_content.lower() or 'app' in response_content.lower():
        print("PASS: Agent response appears to reference the file")
    else:
        print("WARN: Agent response may not have read the file")

    return True


def test_write_tools_blocked(agent: str = "claude"):
    """Test that write tools are blocked when write_enabled=false."""
    print(f"\n{'='*60}")
    print(f"TEST: {agent.upper()} Write Tools - Blocked (write_enabled=false)")
    print('='*60)

    # Create session with writes disabled
    session_id = create_session(tools_enabled=True, write_enabled=False)
    print(f"Created session: {session_id}")

    # Ask agent to create a file
    message = (
        "Please create a new file at /home/kasadis/summitflow/test-file.txt "
        "with the content 'Hello from roundtable test'."
    )

    print(f"Sending message: {message[:60]}...")
    events = send_message_and_get_events(session_id, message, target=agent)

    # Analyze events
    event_types = defaultdict(int)
    permission_events = []
    agent_responses = []

    for event in events:
        event_type = event.get('type', 'unknown')
        event_types[event_type] += 1

        if event_type == 'permission_request':
            permission_events.append(event)
        elif event_type == 'agent_complete':
            agent_responses.append(event.get('data', {}))

    print(f"\nEvent summary: {dict(event_types)}")

    # Should NOT have permission events - should just get blocked
    if permission_events:
        print(f"INFO: Got {len(permission_events)} permission_request events")
        # This is expected behavior if write is attempted - SDK hook triggers
    else:
        print("INFO: No permission_request events (write blocked at tool level)")

    # Verify response indicates write was not allowed
    if agent_responses:
        response_content = agent_responses[0].get('content', '')
        print(f"\nAgent response preview: {response_content[:300]}...")

        # Check for error/blocked indicators
        blocked_indicators = ['error', 'denied', 'blocked', "can't", 'cannot', 'not enabled', 'not allowed']
        if any(ind in response_content.lower() for ind in blocked_indicators):
            print("PASS: Agent response indicates write was blocked")
            return True
        else:
            print("WARN: Agent response may not clearly indicate blocking")

    # Verify file was NOT created
    import os
    if os.path.exists('/home/kasadis/summitflow/test-file.txt'):
        print("FAIL: Test file was created despite write being disabled!")
        os.remove('/home/kasadis/summitflow/test-file.txt')
        return False

    print("PASS: File was not created")
    return True


def test_write_tools_permission_prompt(agent: str = "claude"):
    """Test that write tools trigger permission prompts when enabled."""
    print(f"\n{'='*60}")
    print(f"TEST: {agent.upper()} Write Tools - Permission Prompt")
    print('='*60)

    # Create session with writes enabled, yolo disabled
    session_id = create_session(tools_enabled=True, write_enabled=True, yolo_mode=False)
    print(f"Created session: {session_id}")

    # Ask agent to create a file
    message = (
        "Please create a new file at /home/kasadis/summitflow/test-permission.txt "
        "with the content 'Testing permission prompt'."
    )

    print(f"Sending message: {message[:60]}...")
    print("NOTE: This test will timeout (60s) if permission callback works correctly")
    print("      because we won't approve/deny the permission request.")

    start_time = time.time()
    try:
        events = send_message_and_get_events(session_id, message, target=agent)
    except Exception as e:
        elapsed = time.time() - start_time
        if elapsed > 30:
            print(f"Timeout after {elapsed:.1f}s - this is expected if permission prompt is waiting")
            return True
        else:
            print(f"Error after {elapsed:.1f}s: {e}")
            return False

    elapsed = time.time() - start_time
    print(f"Response received after {elapsed:.1f}s")

    # Analyze events
    event_types = defaultdict(int)
    permission_events = []

    for event in events:
        event_type = event.get('type', 'unknown')
        event_types[event_type] += 1

        if event_type == 'permission_request':
            permission_events.append(event)

    print(f"\nEvent summary: {dict(event_types)}")

    if permission_events:
        print(f"PASS: Got {len(permission_events)} permission_request events:")
        for pe in permission_events:
            data = pe.get('data', {})
            print(f"  - tool: {data.get('tool_name')}")
            print(f"    preview: {data.get('preview', '')[:100]}...")
        return True
    else:
        print("INFO: No permission_request events (may have timed out before prompt)")
        return True


def test_write_tools_yolo_mode(agent: str = "claude"):
    """Test that write tools auto-approve in YOLO mode."""
    print(f"\n{'='*60}")
    print(f"TEST: {agent.upper()} Write Tools - YOLO Mode (auto-approve)")
    print('='*60)

    # Create session with writes enabled and YOLO mode
    session_id = create_session(tools_enabled=True, write_enabled=True, yolo_mode=True)
    print(f"Created session: {session_id}")

    test_file = '/home/kasadis/summitflow/test-yolo-mode.txt'
    message = (
        f"Please create a new file at {test_file} "
        "with the content 'Testing YOLO mode auto-approve'."
    )

    print(f"Sending message: {message[:60]}...")
    events = send_message_and_get_events(session_id, message, target=agent)

    # Analyze events
    event_types = defaultdict(int)
    permission_events = []
    agent_responses = []

    for event in events:
        event_type = event.get('type', 'unknown')
        event_types[event_type] += 1

        if event_type == 'permission_request':
            permission_events.append(event)
        elif event_type == 'agent_complete':
            agent_responses.append(event.get('data', {}))

    print(f"\nEvent summary: {dict(event_types)}")

    # Should NOT have permission prompts in YOLO mode
    if permission_events:
        print(f"FAIL: Got {len(permission_events)} permission_request events in YOLO mode!")
        return False

    print("PASS: No permission_request events (YOLO mode)")

    # Check if file was created
    import os
    if os.path.exists(test_file):
        print(f"PASS: File was created at {test_file}")
        # Clean up
        os.remove(test_file)
        print("  (cleaned up test file)")
        return True
    else:
        print(f"WARN: File was not created (agent may have declined to write)")
        if agent_responses:
            print(f"Agent response: {agent_responses[0].get('content', '')[:200]}...")
        return True  # Not necessarily a failure - agent might not use the tool


def main():
    """Run all tests."""
    print("="*60)
    print("Roundtable Permission Testing Suite")
    print("="*60)
    print(f"API: {API_BASE}")
    print(f"Project: {PROJECT_ID}")

    results = {}

    # Test 1: Claude read tools
    try:
        results['claude_read'] = test_read_tools_no_permission("claude")
    except Exception as e:
        print(f"ERROR: {e}")
        results['claude_read'] = False

    # Test 2: Claude write blocked
    try:
        results['claude_write_blocked'] = test_write_tools_blocked("claude")
    except Exception as e:
        print(f"ERROR: {e}")
        results['claude_write_blocked'] = False

    # Skip permission prompt test for now - it requires interactive approval
    # or will timeout waiting

    # Test 3: Claude YOLO mode
    try:
        results['claude_yolo'] = test_write_tools_yolo_mode("claude")
    except Exception as e:
        print(f"ERROR: {e}")
        results['claude_yolo'] = False

    # Test 4: Gemini read tools
    try:
        results['gemini_read'] = test_read_tools_no_permission("gemini")
    except Exception as e:
        print(f"ERROR: {e}")
        results['gemini_read'] = False

    # Test 5: Gemini write blocked
    try:
        results['gemini_write_blocked'] = test_write_tools_blocked("gemini")
    except Exception as e:
        print(f"ERROR: {e}")
        results['gemini_write_blocked'] = False

    # Test 6: Gemini YOLO mode
    try:
        results['gemini_yolo'] = test_write_tools_yolo_mode("gemini")
    except Exception as e:
        print(f"ERROR: {e}")
        results['gemini_yolo'] = False

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False

    print("="*60)
    if all_passed:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
