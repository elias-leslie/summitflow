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
    "refactoring",  # Refactoring changes, code improvements, technical debt fixes
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

BATCH_EXTRACTION_PROMPT = """Analyze these tool executions and extract structured observations.

For EACH item below, extract an observation. Return a JSON array with one result per item.

{items_json}

---

For each item, return a JSON object with:
- "index": <the item index for matching>
- "observation_type": <one of: pattern, decision, error, constraint, architecture, user_preference, refactoring>
- "priority": <one of: high, medium, low>
- "confidence": <float 0.0-1.0, how certain you are about this extraction>
- "concepts": [<list from: debugging, code_patterns, dependencies, security, performance, testing, configuration>]
- "entities": [<list of {{"type": <type>, "value": <value>}}>] - types: project, file, error_type, tool, concept
- "title": <concise title, 5-10 words>
- "subtitle": <optional one-line clarification or null>
- "narrative": <2-3 sentences explaining significance>
- "facts": {{<key>: <value>}} or null
- "files_read": [<file paths read>] or null
- "files_modified": [<file paths modified>] or null

If an item is trivial (no insight), use:
- "index": <index>
- "skip": true
- "reason": <brief reason>

Rules:
- Return ONLY a JSON array, no markdown
- HIGH priority: error, decision, user_preference - always extract, critical insights
- MEDIUM priority: pattern, architecture - significant learnings
- LOW priority: constraint - routine observations, skip unless exceptional
- confidence: 0.9+ for clear/explicit info, 0.6-0.8 for inferred, 0.3-0.5 for uncertain
- entities: extract named items like files, error types (ImportError, TypeError), tools (pytest, git), concepts (authentication, caching)
- Include index for every result to match back to items

Example response format:
[
  {{"index": 0, "observation_type": "error", "priority": "high", "confidence": 0.95, "concepts": ["debugging"], "entities": [{{"type": "error_type", "value": "ImportError"}}, {{"type": "file", "value": "auth.py"}}], "title": "...", ...}},
  {{"index": 1, "skip": true, "reason": "trivial file read"}},
  ...
]"""

EXTRACTION_PROMPT = """Analyze this tool execution and extract a structured observation.

Tool: {tool_name}
Input: {tool_input}
Output (truncated if long):
{tool_output_preview}

---

Extract a SINGLE observation from this tool execution. Return JSON with:

{{
    "observation_type": "<one of: pattern, decision, error, constraint, architecture, user_preference, refactoring>",
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
- observation_type MUST be one of the 7 types listed
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


PRIORITY_VALUES = ["high", "medium", "low"]


@dataclass
class ExtractedObservation:
    """Structured observation extracted from tool execution."""

    observation_type: str
    title: str
    concepts: list[str]
    priority: str = "medium"  # high, medium, low
    confidence: float = 0.50  # 0.0-1.0 confidence score
    entities: list[dict[str, str]] | None = None  # [{type: "file", value: "auth.py"}]
    subtitle: str | None = None
    narrative: str | None = None
    facts: dict[str, Any] | None = None
    files_read: list[str] | None = None
    files_modified: list[str] | None = None
    discovery_tokens: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    extracted_by: str | None = None  # Model that performed extraction
    raw_excerpt: str | None = None  # Verbatim excerpt from tool output for embeddings


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
            model: LLM model to use for extraction (kept for API compatibility, ignored)
        """
        self.model = model  # Kept for logging compatibility
        self._client = None

    def _get_client(self):
        """Get or create dual provider LLM client with automatic failover."""
        if self._client is None:
            from ..agents import DualProviderClient

            self._client = DualProviderClient(
                primary="gemini",
                gemini_model="gemini-2.0-flash",
                claude_model="claude-haiku-4-5",
            )
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

            # Generate extraction using DualProviderClient
            response = client.generate(prompt=prompt)

            # Extract token usage from LLMResponse
            discovery_tokens = response.usage.get("total_tokens", 0)

            # Parse response
            content = response.content.strip()

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
                    extracted_by=response.model,
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
                extracted_by=response.model,
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

    def _parse_json_array(self, content: str) -> list[dict[str, Any]]:
        """Parse JSON array from LLM response, with robust fallback parsing."""
        # Try direct parse
        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # Try to find JSON array in content
        array_match = re.search(r"\[[\s\S]*\]", content)
        if array_match:
            try:
                result = json.loads(array_match.group(0))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # Return empty array on failure
        logger.warning(f"Failed to parse JSON array from response: {content[:200]}...")
        return []

    async def extract_batch(
        self,
        items: list[dict[str, Any]],
        max_input_chars: int = 500,
        max_output_chars: int = 1000,
        max_raw_excerpt_chars: int = 2000,
    ) -> list[ExtractedObservation]:
        """Extract observations from multiple tool executions in a single LLM call.

        Args:
            items: List of queue items with tool_name, tool_input, tool_output
            max_input_chars: Max chars for each item's input (truncated)
            max_output_chars: Max chars for each item's output (truncated)
            max_raw_excerpt_chars: Max chars for raw_excerpt (for embeddings)

        Returns:
            List of ExtractedObservation objects, one per input item.
        """
        import time

        start_time = time.time()

        if not items:
            return []

        # Format items for the prompt and capture raw excerpts
        formatted_items = []
        raw_excerpts: list[str | None] = []
        for idx, item in enumerate(items):
            tool_input_str = json.dumps(item.get("tool_input") or {})
            if len(tool_input_str) > max_input_chars:
                tool_input_str = tool_input_str[:max_input_chars] + "..."

            tool_output = item.get("tool_output") or ""
            # Store raw excerpt (max 2000 chars) for embedding use
            raw_excerpt = tool_output[:max_raw_excerpt_chars] if tool_output else None
            raw_excerpts.append(raw_excerpt)

            if len(tool_output) > max_output_chars:
                tool_output = tool_output[:max_output_chars] + "..."

            formatted_items.append(
                {
                    "index": idx,
                    "tool_name": item.get("tool_name", "unknown"),
                    "tool_input": tool_input_str,
                    "tool_output": tool_output,
                }
            )

        items_json = json.dumps(formatted_items, indent=2)
        prompt = BATCH_EXTRACTION_PROMPT.format(items_json=items_json)

        try:
            client = self._get_client()

            # Generate batch extraction using DualProviderClient
            response = client.generate(prompt=prompt)

            # Extract token usage from LLMResponse
            discovery_tokens = response.usage.get("total_tokens", 0)

            # Parse response array
            content = response.content.strip()
            results = self._parse_json_array(content)

            # Build index map for matching results to items
            result_map: dict[int, dict[str, Any]] = {}
            for r in results:
                if isinstance(r, dict) and "index" in r:
                    result_map[r["index"]] = r

            # Build observations for each item
            observations: list[ExtractedObservation] = []
            per_item_tokens = discovery_tokens // len(items) if items else 0

            for idx, item in enumerate(items):
                result = result_map.get(idx, {})

                if result.get("skip"):
                    observations.append(
                        ExtractedObservation(
                            observation_type="",
                            title="",
                            concepts=[],
                            skipped=True,
                            skip_reason=result.get("reason", "Trivial execution"),
                            discovery_tokens=per_item_tokens,
                            extracted_by=response.model,
                        )
                    )
                    continue

                # Validate and build observation
                obs_type = result.get("observation_type", "pattern")
                if obs_type not in OBSERVATION_TYPES:
                    obs_type = "pattern"

                # Validate and normalize priority
                priority = result.get("priority", "medium")
                if priority not in PRIORITY_VALUES:
                    priority = "medium"

                # Validate and normalize confidence (0.0-1.0)
                confidence = result.get("confidence", 0.50)
                try:
                    confidence = float(confidence)
                    confidence = max(0.0, min(1.0, confidence))  # Clamp to 0-1
                except (TypeError, ValueError):
                    confidence = 0.50

                concepts = result.get("concepts", [])
                concepts = [c for c in concepts if c in CONCEPT_TAGS]

                # Validate entities format
                entities = result.get("entities", [])
                if not isinstance(entities, list):
                    entities = []
                # Filter to valid entity dicts with type and value
                valid_entity_types = {"project", "file", "error_type", "tool", "concept"}
                entities = [
                    e
                    for e in entities
                    if isinstance(e, dict)
                    and e.get("type") in valid_entity_types
                    and e.get("value")
                ]

                observations.append(
                    ExtractedObservation(
                        observation_type=obs_type,
                        title=result.get("title", f"{item.get('tool_name', 'unknown')} execution"),
                        concepts=concepts,
                        priority=priority,
                        confidence=confidence,
                        entities=entities or None,
                        subtitle=result.get("subtitle"),
                        narrative=result.get("narrative"),
                        facts=result.get("facts"),
                        files_read=result.get("files_read"),
                        files_modified=result.get("files_modified"),
                        discovery_tokens=per_item_tokens,
                        extracted_by=response.model,
                        raw_excerpt=raw_excerpts[idx],
                    )
                )

            duration_seconds = time.time() - start_time
            items_per_second = len(items) / duration_seconds if duration_seconds > 0 else 0
            logger.info(
                f"batch_extraction_completed: batch_size={len(items)}, "
                f"duration_seconds={round(duration_seconds, 2)}, "
                f"items_per_second={round(items_per_second, 2)}, "
                f"total_tokens={discovery_tokens}"
            )

            return observations

        except Exception as e:
            logger.error(f"Batch extraction failed: {e}")
            # Return error observations for each item
            return [
                ExtractedObservation(
                    observation_type="error",
                    title=f"Extraction failed for {item.get('tool_name', 'unknown')}",
                    concepts=["debugging"],
                    narrative=f"Batch extraction failed: {e!s}",
                    discovery_tokens=0,
                    extracted_by=self.model,
                )
                for item in items
            ]
