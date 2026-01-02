"""Context Builder service - Progressive disclosure for token-efficient context loading.

Implements a 3-layer context loading system:
1. Index layer: ~500 tokens summary of available context
2. Expand layer: Full content for specific entities on demand
3. Cache layer: Redis caching for performance

Target: 87% token reduction vs loading full context.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from app.storage import memory as memory_storage
from app.storage.memory_patterns import get_pattern_by_short_id
from app.storage.memory_utils import rank_observation

logger = logging.getLogger(__name__)

# Redis for caching
REDIS_URL = "redis://localhost:6379/1"
CACHE_TTL = 3600  # 1 hour TTL


def get_redis() -> redis.Redis[str]:
    """Get Redis connection for caching."""
    return redis.from_url(REDIS_URL, decode_responses=True)


def estimate_tokens(text: str | None) -> int:
    """Estimate token count for text.

    Uses simple approximation: ~4 characters per token.
    This is a reasonable heuristic for English text.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    if not text:
        return 0
    return len(text) // 4


class ContextBuilder:
    """Builds token-efficient context summaries for agents.

    The progressive disclosure pattern:
    - build_index() returns a compact summary (~500 tokens)
    - expand_entity() returns full content for a specific item
    - This achieves ~87% token reduction vs loading everything
    """

    def __init__(self, project_id: str, session_id: str | None = None, use_cache: bool = True):
        """Initialize the context builder.

        Args:
            project_id: The project to build context for.
            session_id: Optional session filter for recent context.
            use_cache: Whether to use Redis caching (default True).
        """
        self.project_id = project_id
        self.session_id = session_id
        self.use_cache = use_cache

    def _cache_key(self, suffix: str = "") -> str:
        """Generate cache key for this project/session."""
        key = f"context:{self.project_id}"
        if self.session_id:
            key += f":{self.session_id}"
        if suffix:
            key += f":{suffix}"
        return key

    def _get_cached_index(self) -> dict[str, Any] | None:
        """Try to get cached context index."""
        if not self.use_cache:
            return None
        try:
            r = get_redis()
            cached = r.get(self._cache_key("index"))
            if cached:
                logger.debug(f"Cache HIT for {self._cache_key('index')}")
                result: dict[str, Any] = json.loads(cached)
                return result
            logger.debug(f"Cache MISS for {self._cache_key('index')}")
        except redis.RedisError as e:
            logger.warning(f"Redis error during cache get: {e}")
        return None

    def _cache_index(self, index: dict[str, Any]) -> None:
        """Cache the context index."""
        if not self.use_cache:
            return
        try:
            r = get_redis()
            r.setex(self._cache_key("index"), CACHE_TTL, json.dumps(index))
            logger.debug(f"Cached index for {self._cache_key('index')}")
        except redis.RedisError as e:
            logger.warning(f"Redis error during cache set: {e}")

    @staticmethod
    def invalidate_cache(project_id: str, session_id: str | None = None) -> None:
        """Invalidate context cache for a project.

        Call this when new observations are created or patterns change.

        Args:
            project_id: The project to invalidate cache for.
            session_id: Optional session to invalidate specifically.
        """
        try:
            r = get_redis()
            # Delete both project-level and session-specific caches
            pattern = f"context:{project_id}*"
            keys = list(r.scan_iter(pattern))
            if keys:
                r.delete(*keys)
                logger.debug(f"Invalidated {len(keys)} cache keys for {project_id}")
        except redis.RedisError as e:
            logger.warning(f"Redis error during cache invalidation: {e}")

    def build_index(
        self,
        limit: int = 20,
        include_observations: bool = True,
        include_checkpoints: bool = True,
        include_patterns: bool = True,
    ) -> dict[str, Any]:
        """Build a compact context index (~500 tokens target).

        Returns a summary of available context that agents can use to decide
        what to expand. Each item includes an id for expand_entity().

        Args:
            limit: Maximum number of items per category.
            include_observations: Include recent observations.
            include_checkpoints: Include recent checkpoints.
            include_patterns: Include applied patterns.

        Returns:
            Context index with items, token estimates, and metadata.
        """
        # Try cache first
        cached = self._get_cached_index()
        if cached:
            cached["from_cache"] = True
            return cached

        index_items: list[dict[str, Any]] = []
        total_full_tokens = 0

        # Recent observations (most valuable for agent context)
        if include_observations:
            observations = memory_storage.list_observations(
                project_id=self.project_id,
                session_id=self.session_id,
                limit=limit,
            )

            for obs in observations:
                # Calculate full content tokens for reduction tracking
                full_tokens = self._observation_full_tokens(obs)
                total_full_tokens += full_tokens

                # Compact index entry - minimize token count
                # Truncate title to 60 chars for index
                title = obs["title"][:60] + "..." if len(obs["title"]) > 60 else obs["title"]
                index_items.append(
                    {
                        "id": f"obs:{obs['id']}",
                        "t": "obs",  # Short type key
                        "ot": obs["observation_type"][:3],  # First 3 chars of type
                        "title": title,
                        "c": obs.get("concepts", [])[:2],  # Limit concepts
                        "tok": full_tokens,
                    }
                )

        # Recent checkpoints (for resume context)
        if include_checkpoints:
            checkpoints = memory_storage.list_checkpoints(
                project_id=self.project_id,
                limit=min(limit, 5),  # Checkpoints are larger, limit more
            )

            for cp in checkpoints:
                full_tokens = self._checkpoint_full_tokens(cp)
                total_full_tokens += full_tokens

                # Compact index entry
                action = (
                    cp.get("current_action", "")[:40] + "..."
                    if len(cp.get("current_action", "") or "") > 40
                    else cp.get("current_action")
                )
                index_items.append(
                    {
                        "id": f"cp:{cp['id']}",
                        "t": "cp",
                        "a": cp["agent_type"],
                        "act": action,
                        "done": len(cp.get("completed_steps") or []),
                        "left": len(cp.get("remaining_steps") or []),
                        "tok": full_tokens,
                    }
                )

        # Applied patterns (project-specific rules)
        if include_patterns:
            from app.services.memory.pattern_service import PatternService

            patterns = memory_storage.list_patterns(
                project_id=self.project_id,
                status="applied",
                limit=limit,
            )

            for pattern in patterns:
                full_tokens = self._pattern_full_tokens(pattern)
                total_full_tokens += full_tokens

                # Calculate approval boost for ranking
                approval_boost = PatternService.get_approval_boost(pattern)

                # Compact index entry
                title = (
                    pattern["title"][:50] + "..."
                    if len(pattern["title"]) > 50
                    else pattern["title"]
                )
                index_items.append(
                    {
                        "id": f"pat:{pattern['id']}",
                        "t": "pat",
                        "pt": pattern["pattern_type"][:3],
                        "title": title,
                        "use": pattern.get("usage_count", 0),
                        "boost": approval_boost,  # Approval/rejection boost multiplier
                        "tok": full_tokens,
                    }
                )

        # Calculate index token count
        index_tokens = estimate_tokens(json.dumps(index_items))

        # Calculate reduction
        reduction_pct = 0.0
        if total_full_tokens > 0:
            reduction_pct = ((total_full_tokens - index_tokens) / total_full_tokens) * 100

        result = {
            "project_id": self.project_id,
            "session_id": self.session_id,
            "items": index_items,
            "item_count": len(index_items),
            "index_tokens": index_tokens,
            "full_tokens": total_full_tokens,
            "reduction_pct": round(reduction_pct, 1),
            "from_cache": False,
            "instructions": (
                "This is a context index. Each item has an 'id' you can use with "
                "expand_entity(id) to get full content. Only expand what you need."
            ),
        }

        # Cache the result
        self._cache_index(result)

        return result

    def expand_entity(self, entity_id: str) -> dict[str, Any]:
        """Expand an entity from the index to get full content.

        Args:
            entity_id: Entity ID in format "type:uuid" (e.g., "obs:abc-123").

        Returns:
            Full entity content.

        Raises:
            ValueError: If entity_id format is invalid.
            KeyError: If entity not found.
        """
        if ":" not in entity_id:
            raise ValueError(f"Invalid entity_id format: {entity_id}. Expected 'type:uuid'.")

        entity_type, uuid = entity_id.split(":", 1)

        if entity_type == "obs":
            obs = memory_storage.get_observation(uuid)
            if not obs:
                raise KeyError(f"Observation not found: {uuid}")
            return {
                "entity_id": entity_id,
                "type": "observation",
                "content": obs,
                "token_count": self._observation_full_tokens(obs),
            }

        elif entity_type == "cp":
            cp = memory_storage.get_latest_checkpoint(uuid)
            if not cp:
                # Try by checkpoint ID directly
                checkpoints = memory_storage.list_checkpoints(
                    project_id=self.project_id,
                    limit=100,
                )
                cp = next((c for c in checkpoints if c["id"] == uuid), None)
            if not cp:
                raise KeyError(f"Checkpoint not found: {uuid}")
            return {
                "entity_id": entity_id,
                "type": "checkpoint",
                "content": cp,
                "token_count": self._checkpoint_full_tokens(cp),
            }

        elif entity_type == "pat":
            # Support both short IDs (8 chars) and full UUIDs
            pattern = get_pattern_by_short_id(uuid)
            if not pattern:
                raise KeyError(f"Pattern not found: {uuid}")

            # Track pattern usage
            memory_storage.increment_pattern_usage(str(pattern["id"]))

            # Return full pattern content using JSON-lines format
            from app.services.memory.pattern_service import PatternService

            jsonl_content = PatternService.format_pattern_jsonl(pattern, include_content=True)

            return {
                "entity_id": f"pat:{pattern['id']}",
                "type": "pattern",
                "content": pattern,  # Full dict for backward compat
                "jsonl": jsonl_content,  # Compact JSON-lines format
                "token_count": self._pattern_full_tokens(pattern),
            }

        else:
            raise ValueError(f"Unknown entity type: {entity_type}")

    def _observation_full_tokens(self, obs: dict[str, Any]) -> int:
        """Calculate token count for full observation content."""
        tokens = 0
        tokens += estimate_tokens(obs.get("title"))
        tokens += estimate_tokens(obs.get("subtitle"))
        tokens += estimate_tokens(obs.get("narrative"))
        if obs.get("facts"):
            tokens += estimate_tokens(json.dumps(obs["facts"]))
        tokens += estimate_tokens(json.dumps(obs.get("files_read", [])))
        tokens += estimate_tokens(json.dumps(obs.get("files_modified", [])))
        tokens += estimate_tokens(json.dumps(obs.get("concepts", [])))
        return tokens

    def _checkpoint_full_tokens(self, cp: dict[str, Any]) -> int:
        """Calculate token count for full checkpoint content."""
        tokens = 0
        tokens += estimate_tokens(cp.get("current_action"))
        tokens += estimate_tokens(cp.get("question"))
        tokens += estimate_tokens(cp.get("recommendation"))
        tokens += estimate_tokens(cp.get("conversation_summary"))
        if cp.get("completed_steps"):
            tokens += estimate_tokens(json.dumps(cp["completed_steps"]))
        if cp.get("remaining_steps"):
            tokens += estimate_tokens(json.dumps(cp["remaining_steps"]))
        if cp.get("files_modified"):
            tokens += estimate_tokens(json.dumps(cp["files_modified"]))
        if cp.get("decisions_made"):
            tokens += estimate_tokens(json.dumps(cp["decisions_made"]))
        if cp.get("context_snapshot"):
            tokens += estimate_tokens(json.dumps(cp["context_snapshot"]))
        return tokens

    def _pattern_full_tokens(self, pattern: dict[str, Any]) -> int:
        """Calculate token count for full pattern content."""
        tokens = 0
        tokens += estimate_tokens(pattern.get("title"))
        tokens += estimate_tokens(pattern.get("content"))
        tokens += estimate_tokens(pattern.get("rationale"))
        return tokens

    @staticmethod
    def rank_observation(
        obs: dict[str, Any],
        fts_score: float = 0.0,
        query_types: list[str] | None = None,
    ) -> float:
        """Compute multi-signal ranking score for an observation.

        Delegates to shared utility in memory_utils.py.
        Kept as static method for backward compatibility.
        """
        return rank_observation(obs, fts_score, query_types)
