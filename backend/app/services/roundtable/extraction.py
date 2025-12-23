"""TDD Spec extraction from Roundtable conversations.

Handles the extraction of Components, Capabilities, and Tests from
roundtable sessions and the acceptance workflow.
"""

from __future__ import annotations

import json as json_module
import logging
import re
from typing import TYPE_CHECKING, Any

from ..agents import AgentType, get_agent

if TYPE_CHECKING:
    from .session import RoundtableSession

logger = logging.getLogger(__name__)


# TDD Spec Extraction Prompt
SPEC_EXTRACTION_PROMPT = """Analyze the following Roundtable conversation and extract a TDD (Test-Driven Development) specification.

The spec should define:
1. Components - logical groupings of functionality (e.g., "Authentication", "User Management", "API Gateway")
2. Capabilities - specific features within each component (e.g., "Login with email/password", "Password reset flow")
3. Tests - verification steps for each capability

For each component, provide:
- A unique ID (format: COMP-XXX)
- A clear name
- A description

For each capability, provide:
- A unique ID (format: CAP-XXX)
- A clear name
- A description
- Priority (1=critical, 2=high, 3=medium, 4=low)

For each test, provide:
- Test type: "pytest" (backend unit/integration), "vitest" (frontend unit), "api" (HTTP endpoint), "ui" (browser automation)
- A descriptive name
- For pytest/vitest/api: provide "command" field
- For ui tests: provide "config" field with browser-automation settings

UI test config schema (for type: "ui"):
- script_name: Browser script to use (required). Available scripts:
  * screenshot - Take full-page screenshot
  * click-screenshot - Click element and take screenshot
  * tab-click-screenshot - Click tab and take screenshot
  * interact - Perform user interactions (click, fill, hover)
  * regression-check - All-in-one regression testing
  * console - Capture console messages
  * network - Monitor network requests
  * capture-evidence - Comprehensive evidence capture
- url: Target URL to test (required)
- args: Script-specific arguments (optional)
- assertions: List of assertions to check (optional)
  * type: console_errors, network_failures, output_contains, output_not_contains

IMPORTANT: Return ONLY valid JSON in this exact format:
{
  "components": [
    {
      "id": "COMP-AUTH",
      "name": "Authentication",
      "description": "User authentication and authorization",
      "capabilities": [
        {
          "id": "CAP-LOGIN",
          "name": "Email/Password Login",
          "description": "Users can log in with email and password",
          "priority": 1,
          "tests": [
            {
              "type": "pytest",
              "name": "test_login_success",
              "command": "pytest tests/auth/test_login.py::test_login_success"
            },
            {
              "type": "ui",
              "name": "Login form visual check",
              "config": {
                "script_name": "screenshot",
                "url": "https://example.com/login",
                "args": {"fullPage": true},
                "assertions": [{"type": "console_errors"}]
              }
            },
            {
              "type": "ui",
              "name": "Login form submission",
              "config": {
                "script_name": "interact",
                "url": "https://example.com/login",
                "args": {
                  "actions": [
                    {"type": "fill", "selector": "#email", "value": "test@example.com"},
                    {"type": "fill", "selector": "#password", "value": "password123"},
                    {"type": "click", "selector": "button[type=submit]"}
                  ]
                }
              }
            }
          ]
        }
      ]
    }
  ]
}

If no spec can be derived, return: {"components": []}

CONVERSATION:
"""


def get_effective_prompt(project_id: str, prompt_type: str) -> dict[str, Any]:
    """Get the effective prompt for a project (custom or default).

    Args:
        project_id: Project ID
        prompt_type: Type of prompt (feature_extraction, vision_extraction, goals_extraction)

    Returns:
        Prompt configuration dict with prompt_text, primary_agent, primary_model, etc.
    """
    from app.storage import extraction_prompts

    prompt = extraction_prompts.get_extraction_prompt(project_id, prompt_type)
    if prompt:
        return prompt

    # Fallback to class-level defaults (TDD spec extraction only)
    if prompt_type == "spec_extraction":
        return {
            "prompt_text": SPEC_EXTRACTION_PROMPT,
            "primary_agent": "gemini",
            "primary_model": "gemini-3-flash-preview",
            "verification_enabled": False,
            "is_default": True,
        }

    return {"prompt_text": "", "primary_agent": "claude", "is_default": True}


def extract_spec_from_conversation(
    session: RoundtableSession,
    agent_type: AgentType = "gemini",
    claude_model: str = "claude-sonnet-4-5",
    gemini_model: str = "gemini-3-flash-preview",
) -> dict:
    """Extract TDD spec (components, capabilities, tests) from a Roundtable conversation.

    Args:
        session: The roundtable session to analyze
        agent_type: Which agent to use for extraction
        claude_model: Claude model to use
        gemini_model: Gemini model to use

    Returns:
        Dict with 'components' key containing the spec structure
    """
    from app.storage import roundtable as roundtable_storage

    # Build conversation transcript
    context = session.get_context(max_messages=50)

    # Get effective prompt config (custom or default)
    prompt_config = get_effective_prompt(session.project_id, "spec_extraction")
    prompt_text = prompt_config.get("prompt_text", SPEC_EXTRACTION_PROMPT)

    # Use session override > prompt config > provided agent_type
    effective_agent = session.agent_override or prompt_config.get("primary_agent", agent_type)

    effective_model = session.get_effective_model(effective_agent, claude_model, gemini_model)
    agent = get_agent(effective_agent, model=effective_model)
    logger.info(f"Spec extraction using agent={effective_agent}, model={effective_model}")

    prompt = prompt_text + "\n\nCONVERSATION:\n" + context

    try:
        response = agent.generate(
            prompt=prompt,
            system="You are a TDD spec extraction specialist. Extract structured component/capability/test definitions from conversations.",
            max_tokens=16384,
            temperature=0.3,
        )

        # Parse JSON from response
        content = response.content.strip()

        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)

        spec = json_module.loads(content)

        # Store the spec in the session for review
        roundtable_storage.update_generated_spec(session.id, spec)

        return spec

    except Exception as e:
        logger.error(f"Spec extraction failed: {e}")
        return {"components": []}


def accept_spec(
    project_id: str,
    session_id: str,
    accepted_by: str = "user",
) -> dict:
    """Accept the generated spec and create permanent entities.

    This converts the ephemeral generated_spec into permanent:
    - accepted_specs record (permanent spec record)
    - tdd_components
    - tdd_capabilities
    - tdd_tests (with test_capability_links)

    Args:
        project_id: Project ID
        session_id: Roundtable session ID containing the spec
        accepted_by: Who accepted (user or agent name)

    Returns:
        Dict with spec_id and creation counts
    """
    from app.storage import accepted_specs as specs_storage
    from app.storage import capabilities as capabilities_storage
    from app.storage import components as components_storage
    from app.storage import roundtable as roundtable_storage
    from app.storage import tests as tests_storage

    # Get the generated spec from the session
    spec = roundtable_storage.get_generated_spec(session_id)
    if not spec:
        raise ValueError(f"No generated spec found for session {session_id}")

    components_list = spec.get("components", [])
    if not components_list:
        raise ValueError("Spec has no components")

    # Save to accepted_specs table (permanent record)
    spec_record = specs_storage.create_accepted_spec(
        project_id=project_id,
        session_id=session_id,
        spec_content=spec,
        accepted_by=accepted_by,
    )

    # Track creation counts
    components_created = 0
    capabilities_created = 0
    tests_created = 0

    # Create entities from spec
    for comp_data in components_list:
        # Create component
        try:
            component = components_storage.create_component(
                project_id=project_id,
                component_id=comp_data["id"],
                name=comp_data["name"],
                description=comp_data.get("description"),
                priority=comp_data.get("priority", 2),
            )
            components_created += 1
            component_db_id = component["id"]

            # Create capabilities for this component
            for cap_data in comp_data.get("capabilities", []):
                try:
                    capability = capabilities_storage.create_capability(
                        project_id=project_id,
                        component_id=component_db_id,
                        capability_id=cap_data["id"],
                        name=cap_data["name"],
                        description=cap_data.get("description"),
                        priority=cap_data.get("priority", 2),
                    )
                    capabilities_created += 1
                    capability_db_id = capability["id"]

                    # Create tests for this capability
                    for test_data in cap_data.get("tests", []):
                        try:
                            test = tests_storage.create_test(
                                project_id=project_id,
                                test_id=f"{cap_data['id']}-{test_data.get('name', 'test').replace(' ', '-').lower()[:20]}",
                                name=test_data["name"],
                                test_type=test_data["type"],
                                command=test_data.get("command"),
                            )
                            tests_created += 1

                            # Link test to capability
                            tests_storage.link_test_to_capability(
                                capability_db_id=capability_db_id,
                                test_db_id=test["id"],
                                is_primary=True,
                            )

                        except Exception as e:
                            logger.warning(f"Failed to create test: {e}")

                except Exception as e:
                    logger.warning(f"Failed to create capability: {e}")

        except Exception as e:
            logger.warning(f"Failed to create component: {e}")

    # Clear the generated spec from session after acceptance
    roundtable_storage.update_generated_spec(session_id, None)

    logger.info(
        f"Accepted spec {spec_record['id']}: "
        f"{components_created} components, {capabilities_created} capabilities, {tests_created} tests"
    )

    return {
        "spec_id": spec_record["id"],
        "components_created": components_created,
        "capabilities_created": capabilities_created,
        "tests_created": tests_created,
    }
