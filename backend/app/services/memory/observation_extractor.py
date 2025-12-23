"""ObservationExtractor service for extracting structured observations from tool executions.

Uses LLM (Gemini by default) to extract semantic observations with taxonomy.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Observation taxonomy
OBSERVATION_TYPES = [
    "pattern",  # Code patterns, conventions, best practices
    "decision",  # Architectural or design decisions
    "error",  # Errors, issues, problems encountered
    "constraint",  # Constraints, limitations, requirements
    "architecture",  # System architecture, file structure
    "user_preference",  # User preferences, style choices
]

CONCEPT_TAGS = [
    "debugging",  # Bug fixes, error resolution
    "code_patterns",  # Code style, patterns, conventions
    "dependencies",  # Dependencies, imports, integrations
    "security",  # Security considerations
    "performance",  # Performance optimizations
    "testing",  # Tests, verification, validation
    "configuration",  # Config files, environment setup
]

EXTRACTION_PROMPT = """Analyze this tool execution and extract a structured observation.

Tool: {tool_name}
Input: {tool_input}
Output (truncated if long):
{tool_output_preview}

---

Extract a SINGLE observation from this tool execution. Return JSON with:

{{
    "observation_type": "<one of: pattern, decision, error, constraint, architecture, user_preference>",
    "concepts": ["<list of relevant concepts from: debugging, code_patterns, dependencies, security, performance, testing, configuration>"],
    "title": "<concise title, 5-10 words>",
    "subtitle": "<optional one-line clarification>",
    "narrative": "<2-3 sentences explaining what was learned or discovered>",
    "facts": {{
        "<key>": "<value>",
        ...
    }},
    "files_read": ["<list of files that were read>"],
    "files_modified": ["<list of files that were modified>"]
}}

Rules:
- observation_type MUST be one of the 6 types listed
- concepts MUST be from the 7 concepts listed (can be empty if none apply)
- title should be specific and searchable
- narrative should explain the significance, not just describe what happened
- facts should capture key-value pairs useful for programmatic queries
- files_read/files_modified should be file paths extracted from the tool execution

If this tool execution is trivial (e.g., just reading a small file with no insight), return:
{{
    "skip": true,
    "reason": "<brief reason>"
}}

Return ONLY valid JSON, no markdown code blocks."""


@dataclass
class ExtractedObservation:
    """Structured observation extracted from tool execution."""

    observation_type: str
    title: str
    concepts: list[str]
    subtitle: str | None = None
    narrative: str | None = None
    facts: dict[str, Any] | None = None
    files_read: list[str] | None = None
    files_modified: list[str] | None = None
    discovery_tokens: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    extracted_by: str | None = None  # Model that performed extraction


class ObservationExtractor:
    """Extract structured observations from tool executions using LLM.

    Usage:
        extractor = ObservationExtractor()
        observation = await extractor.extract(
            tool_name="Read",
            tool_input={"file": "auth.py"},
            tool_output="def authenticate(user): ..."
        )
    """

    def __init__(self, model: str = "gemini-3-flash-preview"):
        """Initialize extractor.

        Args:
            model: LLM model to use for extraction
        """
        self.model = model
        self._client = None

    def _get_client(self) -> Any:
        """Get or create LLM client."""
        if self._client is None:
            try:
                import os

                from google import genai

                # Load API key from environment or ~/.gemini/.env
                api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    gemini_env = os.path.expanduser("~/.gemini/.env")
                    if os.path.exists(gemini_env):
                        with open(gemini_env) as f:
                            for line in f:
                                if line.startswith("GEMINI_API_KEY="):
                                    api_key = line.strip().split("=", 1)[1]
                                    break

                if api_key:
                    self._client = genai.Client(api_key=api_key)
                else:
                    # Fall back to default credentials
                    self._client = genai.Client()
            except ImportError:
                logger.error("google-genai not installed")
                raise
        return self._client

    def _truncate_output(self, output: str, max_chars: int = 2000) -> str:
        """Truncate output to reasonable size for LLM context."""
        if len(output) <= max_chars:
            return output
        half = max_chars // 2
        return f"{output[:half]}\n\n... [truncated {len(output) - max_chars} chars] ...\n\n{output[-half:]}"

    async def extract(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        tool_output: str | None,
    ) -> ExtractedObservation:
        """Extract structured observation from tool execution.

        Args:
            tool_name: Name of the tool that was executed
            tool_input: Tool input parameters
            tool_output: Tool output/result

        Returns:
            ExtractedObservation with structured data
        """
        # Prepare prompt
        tool_input_str = json.dumps(tool_input, indent=2) if tool_input else "{}"
        tool_output_preview = self._truncate_output(tool_output or "")

        prompt = EXTRACTION_PROMPT.format(
            tool_name=tool_name,
            tool_input=tool_input_str,
            tool_output_preview=tool_output_preview,
        )

        try:
            client = self._get_client()

            # Generate extraction
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )

            # Extract token usage
            discovery_tokens = 0
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                discovery_tokens = getattr(usage, "total_token_count", 0)

            # Parse response
            content = response.text.strip()

            # Try to extract JSON from response
            observation = self._parse_json_response(content)

            # Check if skipped
            if observation.get("skip"):
                return ExtractedObservation(
                    observation_type="",
                    title="",
                    concepts=[],
                    skipped=True,
                    skip_reason=observation.get("reason", "Trivial execution"),
                    discovery_tokens=discovery_tokens,
                    extracted_by=self.model,
                )

            # Validate and build observation
            obs_type = observation.get("observation_type", "pattern")
            if obs_type not in OBSERVATION_TYPES:
                obs_type = "pattern"

            concepts = observation.get("concepts", [])
            concepts = [c for c in concepts if c in CONCEPT_TAGS]

            return ExtractedObservation(
                observation_type=obs_type,
                title=observation.get("title", f"{tool_name} execution"),
                concepts=concepts,
                subtitle=observation.get("subtitle"),
                narrative=observation.get("narrative"),
                facts=observation.get("facts"),
                files_read=observation.get("files_read"),
                files_modified=observation.get("files_modified"),
                discovery_tokens=discovery_tokens,
                extracted_by=self.model,
            )

        except Exception as e:
            logger.error(f"Observation extraction failed: {e}")
            # Return minimal observation on failure
            return ExtractedObservation(
                observation_type="error",
                title=f"Extraction failed for {tool_name}",
                concepts=["debugging"],
                narrative=f"Failed to extract observation: {e!s}",
                discovery_tokens=0,
                extracted_by=self.model,
            )

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling common issues."""
        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in content
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Return empty dict on failure
        logger.warning(f"Failed to parse JSON from response: {content[:200]}...")
        return {}
