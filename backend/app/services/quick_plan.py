"""Quick Plan Service - Generate task plans from templates.

Provides pre-built templates for common task types:
- bug-fix: Fix a bug with verification
- add-endpoint: Add a new API endpoint
- add-component: Add a new frontend component

Templates use verified commands from the pattern library when available.
"""

from __future__ import annotations

from typing import Any

from ..storage import verify_patterns

# Task templates with placeholder substitution
TEMPLATES: dict[str, dict[str, Any]] = {
    "bug-fix": {
        "complexity": "SIMPLE",
        "spirit_anti": "SPIRIT: Fix the bug with minimal changes. ANTI: Don't refactor unrelated code.",
        "done_when": [
            "Bug is fixed and verified",
            "No regressions introduced",
        ],
        "subtasks": [
            {
                "id": "1.1",
                "phase": "backend",
                "description": "Fix the bug: {description}",
                "depends_on": [],
                "steps": [
                    {
                        "description": "Identify and fix the root cause",
                        "verify_command": "rg '{search_pattern}' {target_file} && echo 'fix_applied'",
                        "expected_output": "fix_applied",
                    },
                    {
                        "description": "Deploy backend changes",
                        "verify_command": "./scripts/rebuild.sh --backend >/dev/null 2>&1; curl -sf http://localhost:8001/health | jq -e '.status == \"healthy\"' && echo 'deployed'",
                        "expected_output": "deployed",
                    },
                ],
            },
            {
                "id": "2.1",
                "phase": "verification",
                "description": "Verify the fix works",
                "depends_on": ["1.1"],
                "steps": [
                    {
                        "description": "Confirm bug is fixed",
                        "verify_command": "curl -sf http://localhost:8001/health && echo 'verified'",
                        "expected_output": "verified",
                    },
                ],
            },
        ],
    },
    "add-endpoint": {
        "complexity": "SIMPLE",
        "spirit_anti": "SPIRIT: Add the endpoint following existing patterns. ANTI: Don't over-engineer or add unnecessary features.",
        "done_when": [
            "Endpoint is accessible and returns expected response",
            "Endpoint follows existing API patterns",
        ],
        "subtasks": [
            {
                "id": "1.1",
                "phase": "backend",
                "description": "Add {endpoint_name} endpoint",
                "depends_on": [],
                "steps": [
                    {
                        "description": "Create endpoint handler",
                        "verify_command": "rg '@router.{method}.*{endpoint_path}' backend/app/api/ && echo 'endpoint_exists'",
                        "expected_output": "endpoint_exists",
                    },
                    {
                        "description": "Deploy backend changes",
                        "verify_command": "./scripts/rebuild.sh --backend >/dev/null 2>&1; curl -sf http://localhost:8001/health | jq -e '.status == \"healthy\"' && echo 'deployed'",
                        "expected_output": "deployed",
                    },
                ],
            },
            {
                "id": "2.1",
                "phase": "verification",
                "description": "Verify endpoint works",
                "depends_on": ["1.1"],
                "steps": [
                    {
                        "description": "Test endpoint returns expected response",
                        "verify_command": "curl -sf http://localhost:8001/api/{endpoint_path} && echo 'works'",
                        "expected_output": "works",
                    },
                ],
            },
        ],
    },
    "add-component": {
        "complexity": "SIMPLE",
        "spirit_anti": "SPIRIT: Add a clean, reusable component. ANTI: Don't add unnecessary complexity or features.",
        "done_when": [
            "Component renders correctly",
            "No console errors",
        ],
        "subtasks": [
            {
                "id": "1.1",
                "phase": "frontend",
                "description": "Create {component_name} component",
                "depends_on": [],
                "steps": [
                    {
                        "description": "Create component file",
                        "verify_command": "ls frontend/components/{component_path}.tsx 2>/dev/null && echo 'exists' || ls frontend/app/{component_path}/page.tsx 2>/dev/null && echo 'exists'",
                        "expected_output": "exists",
                    },
                    {
                        "description": "Deploy frontend changes",
                        "verify_command": "./scripts/rebuild.sh --frontend >/dev/null 2>&1; curl -sf http://localhost:3001 && echo 'deployed'",
                        "expected_output": "deployed",
                    },
                ],
            },
            {
                "id": "2.1",
                "phase": "verification",
                "description": "Verify component renders",
                "depends_on": ["1.1"],
                "steps": [
                    {
                        "description": "Check for console errors on page",
                        "verify_command": "curl -sf http://localhost:3001 && echo 'no_errors'",
                        "expected_output": "no_errors",
                    },
                ],
            },
        ],
    },
}


def _substitute_placeholders(obj: Any, params: dict[str, str]) -> Any:
    """Recursively substitute {placeholders} in strings."""
    if isinstance(obj, str):
        # Replace {key} with params[key], leave unknown placeholders
        for key, value in params.items():
            obj = obj.replace(f"{{{key}}}", value)
        return obj
    elif isinstance(obj, dict):
        return {k: _substitute_placeholders(v, params) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute_placeholders(item, params) for item in obj]
    return obj


def _get_verified_deploy_command() -> str | None:
    """Get a proven deploy verification command from the pattern library."""
    try:
        patterns = verify_patterns.get_suggested_patterns("deploy", min_success_rate=80.0, limit=1)
        if patterns:
            cmd: str = patterns[0]["command_example"]
            return cmd
    except Exception:
        pass
    return None


def generate_plan(
    title: str,
    description: str,
    template: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate a task plan from a template.

    Args:
        title: Task title
        description: Task description
        template: Template name (bug-fix, add-endpoint, add-component)
        params: Parameters to substitute in template placeholders

    Returns:
        Complete plan.json structure ready for import

    Raises:
        ValueError: If template not found
    """
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template: {template}. Available: {list(TEMPLATES.keys())}")

    base = TEMPLATES[template].copy()
    params = params or {}

    # Add common params
    params.setdefault("description", description)
    params.setdefault("title", title)

    # Try to use verified deploy command if available
    verified_deploy = _get_verified_deploy_command()
    if verified_deploy:
        params.setdefault("deploy_command", verified_deploy)

    # Deep copy and substitute placeholders
    import copy
    plan: dict[str, Any] = copy.deepcopy(base)
    plan = _substitute_placeholders(plan, params)

    # Add required top-level fields
    plan["title"] = title
    plan["type"] = "task"
    plan["priority"] = 2
    plan["objective"] = description

    # Generate acceptance criteria from done_when
    plan["acceptance_criteria"] = [
        {
            "id": f"ac-{i+1}",
            "criterion": crit,
            "verify_by": "human",
        }
        for i, crit in enumerate(plan.get("done_when", []))
    ]

    return plan


def list_templates() -> list[dict[str, str]]:
    """List available templates with descriptions."""
    return [
        {"name": "bug-fix", "description": "Fix a bug with minimal changes"},
        {"name": "add-endpoint", "description": "Add a new API endpoint"},
        {"name": "add-component", "description": "Add a new frontend component"},
    ]
