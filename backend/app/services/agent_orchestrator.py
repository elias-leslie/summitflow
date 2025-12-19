"""Agent Orchestrator - Autonomous task execution with complexity-based routing.

This module implements the autonomous execution loop for agent tasks, including:
- Complexity assessment for routing decisions
- Spec generation for complex features
- Plan generation and breakdown
- Criterion-by-criterion execution
- Cross-agent delegation
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from .agents import AgentType, get_agent

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

ComplexityLevel = Literal["simple", "medium", "complex"]

# Keywords that indicate different domains
FRONTEND_KEYWORDS = {
    "ui",
    "frontend",
    "react",
    "component",
    "page",
    "button",
    "form",
    "input",
    "modal",
    "dialog",
    "style",
    "css",
    "tailwind",
    "responsive",
    "layout",
    "render",
    "display",
    "view",
    "screen",
    "click",
    "hover",
    "animation",
    "navigation",
    "menu",
    "sidebar",
    "header",
    "footer",
}

BACKEND_KEYWORDS = {
    "api",
    "backend",
    "endpoint",
    "route",
    "server",
    "fastapi",
    "celery",
    "task",
    "service",
    "storage",
    "crud",
    "validation",
    "authentication",
    "authorization",
    "middleware",
    "request",
    "response",
    "handler",
    "controller",
}

DATABASE_KEYWORDS = {
    "database",
    "db",
    "sql",
    "postgresql",
    "postgres",
    "table",
    "column",
    "migration",
    "schema",
    "query",
    "index",
    "foreign key",
    "constraint",
    "transaction",
    "model",
    "entity",
}


def _detect_domains(text: str) -> set[str]:
    """Detect which domains (frontend/backend/database) are referenced in text.

    Args:
        text: Text to analyze (criterion description, feature description, etc.)

    Returns:
        Set of detected domains: {"frontend", "backend", "database"}
    """
    text_lower = text.lower()
    domains: set[str] = set()

    for keyword in FRONTEND_KEYWORDS:
        if keyword in text_lower:
            domains.add("frontend")
            break

    for keyword in BACKEND_KEYWORDS:
        if keyword in text_lower:
            domains.add("backend")
            break

    for keyword in DATABASE_KEYWORDS:
        if keyword in text_lower:
            domains.add("database")
            break

    return domains


def _extract_all_text(feature: dict[str, Any]) -> str:
    """Extract all relevant text from a feature for domain analysis.

    Args:
        feature: Feature dict with name, description, acceptance_criteria, etc.

    Returns:
        Combined text from all relevant fields.
    """
    parts: list[str] = []

    # Feature name and description
    if feature.get("name"):
        parts.append(feature["name"])
    if feature.get("description"):
        parts.append(feature["description"])
    if feature.get("category"):
        parts.append(feature["category"])

    # Acceptance criteria
    criteria = feature.get("acceptance_criteria", [])
    for criterion in criteria:
        if criterion.get("description"):
            parts.append(criterion["description"])
        if criterion.get("type"):
            parts.append(criterion["type"])

    return " ".join(parts)


def assess_complexity(feature: dict[str, Any]) -> ComplexityLevel:
    """Assess the complexity of a feature for routing decisions.

    Complexity levels:
    - simple: <3 criteria AND single domain
    - medium: 3-5 criteria
    - complex: >5 criteria OR multi-domain (2+ domains)

    Args:
        feature: Feature dict with acceptance_criteria list

    Returns:
        Complexity level: "simple", "medium", or "complex"
    """
    criteria = feature.get("acceptance_criteria", [])
    criteria_count = len(criteria)

    # Detect domains from all feature text
    all_text = _extract_all_text(feature)
    detected_domains = _detect_domains(all_text)
    domain_count = len(detected_domains)

    logger.debug(f"Complexity assessment: criteria={criteria_count}, domains={detected_domains}")

    # Complex: >5 criteria OR multi-domain (2+ domains)
    if criteria_count > 5 or domain_count >= 2:
        return "complex"

    # Medium: 3-5 criteria
    if criteria_count >= 3:
        return "medium"

    # Simple: <3 criteria AND single domain (or no detected domains)
    return "simple"


def get_complexity_summary(feature: dict[str, Any]) -> dict[str, Any]:
    """Get detailed complexity assessment with breakdown.

    Args:
        feature: Feature dict with acceptance_criteria list

    Returns:
        Dict with complexity level and detailed breakdown.
    """
    criteria = feature.get("acceptance_criteria", [])
    all_text = _extract_all_text(feature)
    detected_domains = _detect_domains(all_text)
    complexity = assess_complexity(feature)

    return {
        "level": complexity,
        "criteria_count": len(criteria),
        "detected_domains": list(detected_domains),
        "domain_count": len(detected_domains),
        "is_multi_domain": len(detected_domains) >= 2,
        "reasons": _get_complexity_reasons(len(criteria), detected_domains, complexity),
    }


def _get_complexity_reasons(
    criteria_count: int,
    domains: set[str],
    complexity: ComplexityLevel,
) -> list[str]:
    """Generate human-readable reasons for complexity assessment."""
    reasons: list[str] = []

    if complexity == "complex":
        if criteria_count > 5:
            reasons.append(f"High criteria count ({criteria_count} > 5)")
        if len(domains) >= 2:
            reasons.append(f"Multi-domain: {', '.join(sorted(domains))}")
    elif complexity == "medium":
        reasons.append(f"Moderate criteria count ({criteria_count})")
        if len(domains) == 1:
            reasons.append(f"Single domain: {next(iter(domains))}")
    else:  # simple
        if criteria_count == 0:
            reasons.append("No acceptance criteria defined")
        else:
            reasons.append(f"Few criteria ({criteria_count})")
        if len(domains) <= 1:
            domain_str = next(iter(domains)) if domains else "none detected"
            reasons.append(f"Single domain: {domain_str}")

    return reasons


# =========================================================================
# Spec Generation
# =========================================================================

SPEC_GENERATION_PROMPT = """You are a technical architect creating a detailed specification for a software feature.

Analyze the following feature and create a comprehensive specification document that an AI agent can use to implement this feature.

FEATURE:
Name: {name}
Category: {category}
Description: {description}

ACCEPTANCE CRITERIA:
{criteria_list}

Create a detailed specification that includes:

1. **OVERVIEW**: Brief summary of what needs to be built (2-3 sentences)

2. **TECHNICAL APPROACH**: How to implement this feature
   - Architecture decisions
   - Technology choices (use existing patterns from the codebase)
   - Key components to create or modify

3. **IMPLEMENTATION STEPS**: Ordered list of specific implementation tasks
   - Each step should be concrete and actionable
   - Group by domain (backend, frontend, database) if multi-domain

4. **DEPENDENCIES**: External libraries, services, or prerequisite work

5. **ACCEPTANCE CRITERIA MAPPING**: For each criterion, explain:
   - How to implement it
   - How to verify it passes

6. **EDGE CASES**: Potential issues to handle

7. **TESTING STRATEGY**: How to verify the implementation works

Output the specification in MARKDOWN format.
"""


def generate_spec(
    feature: dict[str, Any],
    agent_type: AgentType = "gemini",
    model: str | None = None,
) -> str:
    """Generate a detailed specification for a feature using an AI agent.

    This is used for complex features that need detailed planning before
    implementation. The spec helps guide the agent through implementation.

    Args:
        feature: Feature dict with name, description, acceptance_criteria
        agent_type: Which agent to use ("claude" or "gemini")
        model: Optional model override

    Returns:
        Specification document as markdown string

    Raises:
        RuntimeError: If spec generation fails
    """
    agent = get_agent(agent_type, model)

    # Format criteria list
    criteria = feature.get("acceptance_criteria", [])
    criteria_lines = []
    for i, c in enumerate(criteria, 1):
        status = "✓" if c.get("passes") else "○"
        criteria_lines.append(f"{i}. [{status}] {c.get('description', 'No description')}")

    criteria_list = "\n".join(criteria_lines) if criteria_lines else "No criteria defined"

    # Build the prompt
    prompt = SPEC_GENERATION_PROMPT.format(
        name=feature.get("name", "Unnamed Feature"),
        category=feature.get("category", "general"),
        description=feature.get("description", "No description provided"),
        criteria_list=criteria_list,
    )

    logger.info(f"Generating spec for feature: {feature.get('name')}")

    try:
        response = agent.generate(
            prompt=prompt,
            system="You are a senior software architect. Provide clear, actionable specifications.",
            max_tokens=4096,
            temperature=0.7,
        )

        spec_content = response.content
        logger.info(
            f"Spec generated: {len(spec_content)} chars, "
            f"{response.usage.get('output_tokens', 0)} tokens"
        )

        return spec_content

    except Exception as e:
        logger.error(f"Failed to generate spec: {e}")
        raise RuntimeError(f"Spec generation failed: {e}") from e


def generate_spec_for_task(
    feature: dict[str, Any],
    task: dict[str, Any],
    agent_type: AgentType = "gemini",
    model: str | None = None,
) -> dict[str, Any]:
    """Generate spec and return with metadata for task storage.

    Args:
        feature: Feature dict
        task: Task dict (for context)
        agent_type: Which agent to use
        model: Optional model override

    Returns:
        Dict with spec_content and metadata
    """
    spec_content = generate_spec(feature, agent_type, model)

    return {
        "spec_content": spec_content,
        "generated_by": agent_type,
        "feature_id": feature.get("feature_id"),
        "complexity": assess_complexity(feature),
    }


# =========================================================================
# Plan Generation
# =========================================================================

PLAN_GENERATION_PROMPT = """You are a technical project manager breaking down a feature into actionable subtasks.

FEATURE:
Name: {name}
Category: {category}
Description: {description}

ACCEPTANCE CRITERIA:
{criteria_list}

{spec_section}

Create an implementation plan as a JSON array of subtasks. Each subtask should:
1. Be small enough to complete in one session
2. Map to one or more acceptance criteria
3. Have clear dependencies on other subtasks (if any)

Output ONLY valid JSON in this exact format:
{{
  "subtasks": [
    {{
      "id": "st-001",
      "title": "Short descriptive title",
      "description": "What to implement in this subtask",
      "domain": "backend|frontend|database",
      "criteria_ids": ["ac-001"],
      "depends_on": [],
      "estimated_complexity": "small|medium|large"
    }}
  ],
  "execution_order": ["st-001", "st-002"],
  "parallel_groups": [["st-001"], ["st-002", "st-003"]]
}}

RULES:
1. Order subtasks by dependency (dependencies first)
2. Group subtasks that can run in parallel
3. Each criterion should be covered by at least one subtask
4. Include setup tasks (database, dependencies) before implementation
5. Include testing/verification as final subtask(s)
"""


def generate_plan(
    feature: dict[str, Any],
    spec: str | None = None,
    agent_type: AgentType = "gemini",
    model: str | None = None,
) -> dict[str, Any]:
    """Generate an implementation plan for a feature.

    The plan breaks down the feature into subtasks with dependencies,
    enabling criterion-by-criterion execution.

    Args:
        feature: Feature dict with name, description, acceptance_criteria
        spec: Optional spec document (from generate_spec)
        agent_type: Which agent to use
        model: Optional model override

    Returns:
        Plan dict with subtasks, execution_order, parallel_groups

    Raises:
        RuntimeError: If plan generation fails
    """

    agent = get_agent(agent_type, model)

    # Format criteria list
    criteria = feature.get("acceptance_criteria", [])
    criteria_lines = []
    for i, c in enumerate(criteria, 1):
        status = "✓" if c.get("passes") else "○"
        criteria_lines.append(
            f"{i}. [{status}] ID: {c.get('id', f'ac-{i:03d}')} - {c.get('description', 'No description')}"
        )

    criteria_list = "\n".join(criteria_lines) if criteria_lines else "No criteria defined"

    # Include spec if provided
    spec_section = ""
    if spec:
        # Truncate spec if too long
        truncated_spec = spec[:3000] + "..." if len(spec) > 3000 else spec
        spec_section = f"\nSPECIFICATION (summarized):\n{truncated_spec}\n"

    # Build the prompt
    prompt = PLAN_GENERATION_PROMPT.format(
        name=feature.get("name", "Unnamed Feature"),
        category=feature.get("category", "general"),
        description=feature.get("description", "No description provided"),
        criteria_list=criteria_list,
        spec_section=spec_section,
    )

    logger.info(f"Generating plan for feature: {feature.get('name')}")

    try:
        response = agent.generate(
            prompt=prompt,
            system="You are a technical project manager. Output ONLY valid JSON, no markdown or explanations.",
            max_tokens=4096,
            temperature=0.5,
        )

        # Parse JSON from response
        plan = _parse_plan_json(response.content)

        logger.info(
            f"Plan generated: {len(plan.get('subtasks', []))} subtasks, "
            f"{response.usage.get('output_tokens', 0)} tokens"
        )

        return plan

    except Exception as e:
        logger.error(f"Failed to generate plan: {e}")
        raise RuntimeError(f"Plan generation failed: {e}") from e


def _parse_plan_json(response_text: str) -> dict[str, Any]:
    """Parse plan JSON from agent response.

    Handles various response formats:
    - Pure JSON
    - JSON in markdown code blocks
    - JSON with leading/trailing text
    """
    import json
    import re

    # Try direct JSON parse first
    try:
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in text
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # Return minimal valid plan if parsing fails
    logger.warning("Failed to parse plan JSON, returning minimal plan")
    return {
        "subtasks": [],
        "execution_order": [],
        "parallel_groups": [],
        "parse_error": "Failed to parse agent response as JSON",
        "raw_response": response_text[:500],
    }


def generate_plan_for_task(
    feature: dict[str, Any],
    task: dict[str, Any],
    spec: str | None = None,
    agent_type: AgentType = "gemini",
    model: str | None = None,
) -> dict[str, Any]:
    """Generate plan and return with metadata for task storage.

    Args:
        feature: Feature dict
        task: Task dict (for context)
        spec: Optional spec document
        agent_type: Which agent to use
        model: Optional model override

    Returns:
        Dict with plan_content and metadata
    """
    plan = generate_plan(feature, spec, agent_type, model)

    return {
        "plan_content": plan,
        "generated_by": agent_type,
        "feature_id": feature.get("feature_id"),
        "subtask_count": len(plan.get("subtasks", [])),
    }


# =========================================================================
# Criterion-by-Criterion Execution
# =========================================================================

CRITERION_EXECUTION_PROMPT = """You are implementing a specific acceptance criterion for a software feature.

FEATURE CONTEXT:
Name: {feature_name}
Description: {feature_description}

CRITERION TO IMPLEMENT:
ID: {criterion_id}
Description: {criterion_description}

{spec_section}

{plan_section}

YOUR TASK:
1. Implement ONLY what's needed to make this criterion pass
2. Be specific and actionable
3. Provide code if needed, or specific instructions
4. Explain how to verify the criterion passes

Output your implementation response as markdown.
"""


def execute_criterion(
    task: dict[str, Any],
    criterion: dict[str, Any],
    feature: dict[str, Any],
    agent_type: AgentType = "gemini",
    model: str | None = None,
) -> dict[str, Any]:
    """Execute a single acceptance criterion using an AI agent.

    This function:
    1. Updates task.current_criterion_id
    2. Executes agent with criterion-specific prompt
    3. Returns agent's response with execution metadata

    The caller is responsible for:
    - Updating criterion status (passes=true) after verification
    - Capturing evidence
    - Advancing to next criterion

    Args:
        task: Task dict from database
        criterion: Criterion dict to execute
        feature: Feature dict with context
        agent_type: Which agent to use
        model: Optional model override

    Returns:
        Dict with:
        - response: Agent's response content
        - criterion_id: ID of criterion executed
        - tokens_used: Token count for this execution
        - success: Whether execution completed without error

    Raises:
        RuntimeError: If execution fails
    """
    from ..storage import tasks as task_storage

    agent = get_agent(agent_type, model)

    criterion_id = criterion.get("id", "unknown")
    criterion_desc = criterion.get("description", "No description")

    # Update current_criterion_id before starting
    task_storage.update_task(task["id"], current_criterion_id=criterion_id)
    task_storage.append_progress_log(
        task["id"], f"Starting criterion: {criterion_id} - {criterion_desc[:50]}..."
    )

    # Build spec section if available
    spec_section = ""
    if task.get("spec_content"):
        spec = task["spec_content"]
        truncated = spec[:2000] + "..." if len(spec) > 2000 else spec
        spec_section = f"\nSPECIFICATION (relevant parts):\n{truncated}\n"

    # Build plan section if available
    plan_section = ""
    if task.get("plan_content"):
        plan = task["plan_content"]
        if isinstance(plan, dict):
            # Find subtasks related to this criterion
            related_subtasks = [
                st for st in plan.get("subtasks", []) if criterion_id in st.get("criteria_ids", [])
            ]
            if related_subtasks:
                subtask_text = "\n".join(
                    [f"- {st['title']}: {st.get('description', '')}" for st in related_subtasks]
                )
                plan_section = f"\nRELATED SUBTASKS:\n{subtask_text}\n"

    # Build the prompt
    prompt = CRITERION_EXECUTION_PROMPT.format(
        feature_name=feature.get("name", "Unknown Feature"),
        feature_description=feature.get("description", "No description"),
        criterion_id=criterion_id,
        criterion_description=criterion_desc,
        spec_section=spec_section,
        plan_section=plan_section,
    )

    logger.info(f"Executing criterion: {criterion_id}")

    try:
        response = agent.generate(
            prompt=prompt,
            system="You are a skilled software developer. Implement the criterion precisely and concisely.",
            max_tokens=4096,
            temperature=0.7,
        )

        tokens_used = response.usage.get("output_tokens", 0) + response.usage.get("input_tokens", 0)

        # Log completion
        task_storage.append_progress_log(
            task["id"],
            f"Criterion {criterion_id} executed ({tokens_used} tokens)",
        )

        logger.info(f"Criterion {criterion_id} executed: {tokens_used} tokens")

        return {
            "response": response.content,
            "criterion_id": criterion_id,
            "tokens_used": tokens_used,
            "success": True,
        }

    except Exception as e:
        logger.error(f"Failed to execute criterion {criterion_id}: {e}")
        task_storage.append_progress_log(task["id"], f"Criterion {criterion_id} FAILED: {e}")
        raise RuntimeError(f"Criterion execution failed: {e}") from e


# Transient errors that should be retried
TRANSIENT_ERROR_PATTERNS = [
    "timeout",
    "connection",
    "rate limit",
    "temporarily unavailable",
    "503",
    "429",
    "overloaded",
    "capacity",
    "network",
    "socket",
]


def is_transient_error(error: Exception) -> bool:
    """Check if an error is transient and should be retried.

    Args:
        error: The exception to check

    Returns:
        True if the error appears transient
    """
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in TRANSIENT_ERROR_PATTERNS)


def execute_criterion_with_retry(
    task: dict[str, Any],
    criterion: dict[str, Any],
    feature: dict[str, Any],
    agent_type: AgentType = "gemini",
    model: str | None = None,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> dict[str, Any]:
    """Execute a criterion with automatic retry on transient failures.

    Args:
        task: Task dict from database
        criterion: Criterion dict to execute
        feature: Feature dict with context
        agent_type: Which agent to use
        model: Optional model override
        max_retries: Maximum number of retry attempts (default 3)
        retry_delay: Delay between retries in seconds (default 5.0)

    Returns:
        Dict with execution result, including retry_count and is_transient

    Raises:
        RuntimeError: If all retry attempts fail
    """
    from ..storage import tasks as task_storage

    criterion_id = criterion.get("id", "unknown")
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            result = execute_criterion(
                task=task,
                criterion=criterion,
                feature=feature,
                agent_type=agent_type,
                model=model,
            )
            result["retry_count"] = attempt
            result["is_transient"] = False
            return result

        except Exception as e:
            last_error = e
            is_transient = is_transient_error(e)

            if attempt < max_retries and is_transient:
                # Log retry attempt
                task_storage.append_progress_log(
                    task["id"],
                    f"Criterion {criterion_id} failed (transient): {e}. "
                    f"Retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})",
                )
                logger.warning(
                    f"Transient error for criterion {criterion_id}, "
                    f"retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(retry_delay)
                # Exponential backoff for subsequent retries
                retry_delay = min(retry_delay * 2, 60.0)
            else:
                # Non-transient error or max retries reached
                if not is_transient:
                    task_storage.append_progress_log(
                        task["id"],
                        f"Criterion {criterion_id} failed (non-transient): {e}. No retry.",
                    )
                else:
                    task_storage.append_progress_log(
                        task["id"],
                        f"Criterion {criterion_id} failed after {attempt + 1} attempts: {e}",
                    )
                # Return failure result instead of raising
                return {
                    "response": None,
                    "criterion_id": criterion_id,
                    "tokens_used": 0,
                    "success": False,
                    "retry_count": attempt,
                    "is_transient": is_transient,
                    "error": str(e),
                }

    # This shouldn't be reached, but just in case
    return {
        "response": None,
        "criterion_id": criterion_id,
        "tokens_used": 0,
        "success": False,
        "retry_count": max_retries,
        "is_transient": True,
        "error": str(last_error) if last_error else "Unknown error",
    }


def mark_criterion_passed(
    task: dict[str, Any],
    criterion_id: str,
    feature: dict[str, Any],
    evidence_id: str | None = None,
) -> bool:
    """Mark a criterion as passed after verification.

    Args:
        task: Task dict
        criterion_id: ID of criterion to mark
        feature: Feature dict
        evidence_id: Optional evidence ID to link

    Returns:
        True if marked successfully
    """
    from ..storage import features as feature_storage
    from ..storage import tasks as task_storage

    result = feature_storage.update_criterion_status(
        project_id=feature["project_id"],
        feature_id=feature["feature_id"],
        criterion_id=criterion_id,
        passes=True,
        evidence_id=evidence_id,
    )

    if result:
        task_storage.append_progress_log(task["id"], f"Criterion {criterion_id} PASSED ✓")
        return True

    task_storage.append_progress_log(
        task["id"], f"Failed to mark criterion {criterion_id} as passed"
    )
    return False


def get_next_criterion(feature: dict[str, Any]) -> dict[str, Any] | None:
    """Get the next unpassed criterion for a feature.

    Args:
        feature: Feature dict with acceptance_criteria

    Returns:
        Next criterion dict or None if all passed
    """
    criteria = feature.get("acceptance_criteria", [])
    for criterion in criteria:
        if not criterion.get("passes"):
            return criterion
    return None


def get_execution_progress(feature: dict[str, Any]) -> dict[str, Any]:
    """Get execution progress summary for a feature.

    Args:
        feature: Feature dict with acceptance_criteria

    Returns:
        Dict with total, passed, remaining counts and percentage
    """
    criteria = feature.get("acceptance_criteria", [])
    total = len(criteria)
    passed = sum(1 for c in criteria if c.get("passes"))

    return {
        "total": total,
        "passed": passed,
        "remaining": total - passed,
        "percentage": (passed / total * 100) if total > 0 else 0,
        "all_passed": passed == total and total > 0,
    }


# =========================================================================
# Auto-Continue Execution
# =========================================================================


def execute_all_criteria(
    task: dict[str, Any],
    feature: dict[str, Any],
    agent_type: AgentType = "gemini",
    model: str | None = None,
    delay_seconds: float = 3.0,
    stop_on_failure: bool = True,
    auto_mark_passed: bool = True,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> dict[str, Any]:
    """Execute all unpassed criteria in sequence with auto-continue.

    This function implements the autonomous loop:
    1. Get next unpassed criterion
    2. Execute criterion with automatic retry on transient failures
    3. Optionally mark as passed
    4. Wait for delay
    5. Continue to next criterion
    6. Stop on completion or failure

    Args:
        task: Task dict from database
        feature: Feature dict with acceptance_criteria
        agent_type: Which agent to use
        model: Optional model override
        delay_seconds: Delay between criteria (default 3.0)
        stop_on_failure: Stop if a criterion fails (default True)
        auto_mark_passed: Automatically mark criteria as passed (default True)
        max_retries: Maximum retry attempts per criterion (default 3)
        retry_delay: Initial delay between retries (default 5.0)

    Returns:
        Dict with:
        - completed: Number of criteria completed
        - failed: Number of criteria failed
        - total_tokens: Total tokens used
        - all_passed: Whether all criteria are now passed
        - stopped_at: Criterion ID where execution stopped (if any)
        - error: Error message if execution failed
    """
    from ..storage import features as feature_storage
    from ..storage import tasks as task_storage

    result = {
        "completed": 0,
        "failed": 0,
        "total_tokens": 0,
        "all_passed": False,
        "stopped_at": None,
        "error": None,
        "executions": [],
    }

    task_storage.append_progress_log(
        task["id"],
        f"Starting auto-execution: delay={delay_seconds}s, stop_on_failure={stop_on_failure}",
    )

    # Keep executing until all criteria pass or we hit a failure
    while True:
        # Refresh feature to get latest criteria status
        fresh_feature = feature_storage.get_feature(feature["project_id"], feature["feature_id"])
        if not fresh_feature:
            result["error"] = "Feature not found"
            break

        # Get next unpassed criterion
        criterion = get_next_criterion(fresh_feature)
        if criterion is None:
            # All criteria passed
            result["all_passed"] = True
            task_storage.append_progress_log(task["id"], "All criteria passed! ✓")
            break

        criterion_id = criterion.get("id", "unknown")

        # Execute the criterion with retry logic
        execution = execute_criterion_with_retry(
            task=task,
            criterion=criterion,
            feature=fresh_feature,
            agent_type=agent_type,
            model=model,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        result["total_tokens"] += execution.get("tokens_used", 0)
        result["executions"].append(
            {
                "criterion_id": criterion_id,
                "success": execution.get("success", False),
                "tokens_used": execution.get("tokens_used", 0),
                "retry_count": execution.get("retry_count", 0),
            }
        )

        if execution.get("success"):
            result["completed"] += 1

            # Auto-mark as passed if enabled
            if auto_mark_passed:
                mark_criterion_passed(
                    task=task,
                    criterion_id=criterion_id,
                    feature=fresh_feature,
                )

            # Wait before next criterion
            if delay_seconds > 0:
                task_storage.append_progress_log(
                    task["id"], f"Waiting {delay_seconds}s before next criterion..."
                )
                time.sleep(delay_seconds)
        else:
            result["failed"] += 1
            result["stopped_at"] = criterion_id
            result["error"] = execution.get("error", "Unknown error")

            # Update task with error message on persistent failure
            task_storage.update_task_status(
                task["id"],
                "failed",
                error_message=f"Criterion {criterion_id} failed: {execution.get('error', 'Unknown error')}",
                validate_transition=False,  # Allow transition even if task is not running
            )

            if stop_on_failure:
                task_storage.append_progress_log(
                    task["id"],
                    f"Stopping: criterion {criterion_id} failed after {execution.get('retry_count', 0) + 1} attempts",
                )
                break

    # Final progress summary
    task_storage.append_progress_log(
        task["id"],
        f"Auto-execution complete: {result['completed']} completed, "
        f"{result['failed']} failed, {result['total_tokens']} tokens",
    )

    return result


async def execute_all_criteria_async(
    task: dict[str, Any],
    feature: dict[str, Any],
    agent_type: AgentType = "gemini",
    model: str | None = None,
    delay_seconds: float = 3.0,
    stop_on_failure: bool = True,
    auto_mark_passed: bool = True,
) -> dict[str, Any]:
    """Async version of execute_all_criteria for use in async contexts.

    Same parameters and return value as execute_all_criteria.
    """
    import asyncio

    from ..storage import features as feature_storage
    from ..storage import tasks as task_storage

    result = {
        "completed": 0,
        "failed": 0,
        "total_tokens": 0,
        "all_passed": False,
        "stopped_at": None,
        "error": None,
        "executions": [],
    }

    task_storage.append_progress_log(
        task["id"],
        f"Starting async auto-execution: delay={delay_seconds}s",
    )

    while True:
        fresh_feature = feature_storage.get_feature(feature["project_id"], feature["feature_id"])
        if not fresh_feature:
            result["error"] = "Feature not found"
            break

        criterion = get_next_criterion(fresh_feature)
        if criterion is None:
            result["all_passed"] = True
            task_storage.append_progress_log(task["id"], "All criteria passed! ✓")
            break

        criterion_id = criterion.get("id", "unknown")

        try:
            # Run sync execution in thread pool
            # Use functools.partial to avoid closure issues
            import functools

            loop = asyncio.get_event_loop()
            execution = await loop.run_in_executor(
                None,
                functools.partial(
                    execute_criterion,
                    task=task,
                    criterion=criterion,
                    feature=fresh_feature,
                    agent_type=agent_type,
                    model=model,
                ),
            )

            result["total_tokens"] += execution.get("tokens_used", 0)
            result["executions"].append(
                {
                    "criterion_id": criterion_id,
                    "success": execution.get("success", False),
                    "tokens_used": execution.get("tokens_used", 0),
                }
            )

            if execution.get("success"):
                result["completed"] += 1

                if auto_mark_passed:
                    mark_criterion_passed(
                        task=task,
                        criterion_id=criterion_id,
                        feature=fresh_feature,
                    )

                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
            else:
                result["failed"] += 1
                result["stopped_at"] = criterion_id
                if stop_on_failure:
                    break

        except Exception as e:
            result["failed"] += 1
            result["error"] = str(e)
            result["stopped_at"] = criterion_id
            if stop_on_failure:
                break

    return result


# =========================================================================
# Commit per Criterion
# =========================================================================


def commit_for_criterion(
    task: dict[str, Any],
    criterion: dict[str, Any],
    feature: dict[str, Any],
    project_path: str,
) -> str | None:
    """Create a git commit after a criterion passes.

    Commit message format: feat({feature}): {criterion} [task-{id}]

    Args:
        task: Task dict
        criterion: Criterion dict that was just completed
        feature: Feature dict
        project_path: Path to the git repository

    Returns:
        Commit SHA if created, None if nothing to commit
    """
    from ..storage import tasks as task_storage
    from . import git_service

    criterion_id = criterion.get("id", "unknown")
    criterion_desc = criterion.get("description", "criterion completed")
    feature_name = feature.get("name", "feature")

    # Create a slug from the feature name for the commit type
    feature_slug = git_service.slugify(feature_name, max_length=20)

    # Truncate criterion description for commit message
    criterion_short = criterion_desc[:50] + "..." if len(criterion_desc) > 50 else criterion_desc

    # Build commit message
    commit_message = (
        f"feat({feature_slug}): {criterion_short} [task-{task['id'].replace('task-', '')}]"
    )

    try:
        commit_sha = git_service.commit_changes(
            message=commit_message,
            project_path=project_path,
            add_all=True,
        )

        if commit_sha:
            # Add commit to task's commits array
            task_storage.add_commit(task["id"], commit_sha)
            task_storage.append_progress_log(
                task["id"], f"Commit created: {commit_sha[:8]} for {criterion_id}"
            )
            logger.info(f"Commit created for {criterion_id}: {commit_sha[:8]}")
            return commit_sha
        else:
            task_storage.append_progress_log(task["id"], f"No changes to commit for {criterion_id}")
            return None

    except Exception as e:
        task_storage.append_progress_log(
            task["id"], f"Failed to create commit for {criterion_id}: {e}"
        )
        logger.error(f"Commit failed for {criterion_id}: {e}")
        return None


def execute_criterion_with_commit(
    task: dict[str, Any],
    criterion: dict[str, Any],
    feature: dict[str, Any],
    project_path: str,
    agent_type: AgentType = "gemini",
    model: str | None = None,
) -> dict[str, Any]:
    """Execute a criterion and create a commit if it passes.

    Combines execute_criterion, mark_criterion_passed, and commit_for_criterion
    into a single workflow.

    Args:
        task: Task dict
        criterion: Criterion dict to execute
        feature: Feature dict
        project_path: Path to git repository
        agent_type: Which agent to use
        model: Optional model override

    Returns:
        Dict with execution result plus commit_sha
    """
    # Execute the criterion
    result = execute_criterion(
        task=task,
        criterion=criterion,
        feature=feature,
        agent_type=agent_type,
        model=model,
    )

    # If successful, mark as passed and commit
    if result.get("success"):
        criterion_id = criterion.get("id")

        # Mark criterion as passed
        mark_criterion_passed(
            task=task,
            criterion_id=criterion_id,
            feature=feature,
        )

        # Create commit
        commit_sha = commit_for_criterion(
            task=task,
            criterion=criterion,
            feature=feature,
            project_path=project_path,
        )

        result["commit_sha"] = commit_sha

    return result


# =========================================================================
# Cross-Agent Delegation
# =========================================================================

DELEGATION_PROMPT = """You are being asked to help with a specific question from another AI agent.

CONTEXT:
{context}

QUESTION:
{query}

Provide a clear, actionable response focused on the specific question asked.
If you need more context, say so clearly.
"""


def delegate_to_agent(
    context: str,
    query: str,
    target_agent: AgentType = "gemini",
    model: str | None = None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Delegate a question to another agent.

    This enables cross-agent collaboration where one agent can ask
    another for help with specific aspects (e.g., Claude asking
    Gemini for UI design suggestions).

    Args:
        context: Background context for the question
        query: The specific question to answer
        target_agent: Which agent to delegate to ("gemini" or "claude")
        model: Optional model override
        task: Optional task for logging

    Returns:
        Dict with:
        - response: Agent's response content
        - agent: Which agent responded
        - tokens_used: Token count
        - success: Whether delegation succeeded
    """
    from ..storage import tasks as task_storage

    agent = get_agent(target_agent, model)

    if task:
        task_storage.append_progress_log(
            task["id"], f"Delegating to {target_agent}: {query[:50]}..."
        )

    prompt = DELEGATION_PROMPT.format(context=context, query=query)

    try:
        response = agent.generate(
            prompt=prompt,
            system=f"You are a {target_agent} AI assistant helping another AI agent.",
            max_tokens=4096,
            temperature=0.7,
        )

        tokens_used = response.usage.get("output_tokens", 0) + response.usage.get("input_tokens", 0)

        if task:
            task_storage.append_progress_log(
                task["id"],
                f"Delegation response from {target_agent}: {tokens_used} tokens",
            )

        logger.info(f"Delegation to {target_agent} completed: {tokens_used} tokens")

        return {
            "response": response.content,
            "agent": target_agent,
            "tokens_used": tokens_used,
            "success": True,
        }

    except Exception as e:
        logger.error(f"Delegation to {target_agent} failed: {e}")
        if task:
            task_storage.append_progress_log(
                task["id"], f"Delegation to {target_agent} FAILED: {e}"
            )
        return {
            "response": None,
            "agent": target_agent,
            "tokens_used": 0,
            "success": False,
            "error": str(e),
        }


def delegate_to_gemini(
    context: str,
    query: str,
    model: str | None = None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience function to delegate to Gemini.

    Args:
        context: Background context
        query: The question to answer
        model: Optional model override
        task: Optional task for logging

    Returns:
        Delegation result dict
    """
    return delegate_to_agent(
        context=context,
        query=query,
        target_agent="gemini",
        model=model,
        task=task,
    )


def delegate_to_claude(
    context: str,
    query: str,
    model: str | None = None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience function to delegate to Claude.

    Args:
        context: Background context
        query: The question to answer
        model: Optional model override
        task: Optional task for logging

    Returns:
        Delegation result dict
    """
    return delegate_to_agent(
        context=context,
        query=query,
        target_agent="claude",
        model=model,
        task=task,
    )


def should_delegate(
    criterion: dict[str, Any],
    current_agent: AgentType,
    delegation_enabled: bool = True,
) -> tuple[bool, AgentType | None, str | None]:
    """Determine if a criterion should be delegated to another agent.

    Simple heuristic: delegate UI/design questions to Gemini,
    backend/code questions to Claude.

    Args:
        criterion: The criterion being worked on
        current_agent: The agent currently executing
        delegation_enabled: Whether delegation is allowed

    Returns:
        Tuple of (should_delegate, target_agent, reason)
    """
    if not delegation_enabled:
        return False, None, None

    desc = criterion.get("description", "").lower()
    crit_type = criterion.get("type", "").lower()

    # UI/design keywords suggest Gemini
    ui_keywords = {"ui", "design", "layout", "style", "component", "visual", "responsive"}
    # Backend/code keywords suggest Claude
    backend_keywords = {"api", "endpoint", "database", "backend", "server", "logic", "algorithm"}

    # If current agent is Claude and criterion is UI-focused, suggest Gemini
    if current_agent == "claude" and any(kw in desc or kw in crit_type for kw in ui_keywords):
        return True, "gemini", "UI/design criterion - Gemini excels at visual design"

    # If current agent is Gemini and criterion is backend-focused, suggest Claude
    if current_agent == "gemini" and any(kw in desc or kw in crit_type for kw in backend_keywords):
        return True, "claude", "Backend/code criterion - Claude excels at code"

    return False, None, None
