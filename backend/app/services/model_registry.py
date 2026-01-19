"""Centralized Model Registry with capability-to-model mapping.

Per d12 decision: Create shared ModelRegistry that maps capabilities to models.
All model selection should go through this registry to ensure consistency.

Features:
- Capability-based model selection (CODING, PLANNING, REVIEW, etc.)
- Provider preferences (claude_preferred, gemini_preferred, either)
- Complexity tier override (higher tiers can request stronger models)
- Circuit breaker integration for provider fallback
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from ..constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
)
from ..logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Safety Constants (d14 decision: hardcoded, not configurable)
# =============================================================================

# Safety prime directive - prepended to ALL autonomous agent prompts
# These are guardrails for autonomous code execution
SAFETY_PRIME_DIRECTIVE: str = """## Safety Constraints (NON-NEGOTIABLE)

You are an autonomous code agent. The following constraints MUST be followed:

1. **No destructive operations**: Never delete files outside the project, never run rm -rf, never drop databases
2. **No credential exposure**: Never log, print, or commit secrets, API keys, or credentials
3. **No network exfiltration**: Never send project data to external services not explicitly configured
4. **Worktree isolation**: All file modifications MUST be in the designated worktree, never in main
5. **Rollback ready**: Every change must be reversible via git reset

"""


class ModelCapability(str, Enum):
    """Capabilities that models can fulfill."""

    # Core capabilities
    CODING = "coding"  # SWE-bench style code generation
    PLANNING = "planning"  # Architecture and task planning
    REVIEW = "review"  # Code review and auditing

    # Performance tiers
    FAST_TASK = "fast_task"  # Quick, cheap operations
    CONTEXT_HEAVY = "context_heavy"  # Large context window needed

    # Escalation levels
    WORKER = "worker"  # 3-2-1 escalation: Worker level (attempts 1-3)
    SUPERVISOR_PRIMARY = "supervisor_primary"  # Supervisor attempt 1 (Sonnet)
    SUPERVISOR_AUDIT = "supervisor_audit"  # Supervisor attempt 2 (Pro)

    # Specialized
    REASONING = "reasoning"  # Complex multi-step reasoning


ProviderPreference = Literal["claude_preferred", "gemini_preferred", "either"]


@dataclass
class ModelConfig:
    """Configuration for a model option."""

    model_id: str
    provider: Literal["claude", "gemini"]
    priority: int = 0  # Higher = preferred
    max_tokens_default: int = 8000
    supports_thinking: bool = False


@dataclass
class CircuitBreakerState:
    """State for provider circuit breaker."""

    failures: int = 0
    last_failure: datetime | None = None
    is_open: bool = False
    half_open_at: datetime | None = None


# Default capability to model mapping
DEFAULT_CAPABILITY_MODELS: dict[ModelCapability, list[ModelConfig]] = {
    ModelCapability.CODING: [
        ModelConfig(GEMINI_FLASH, "gemini", priority=1),  # 78% SWE-bench
        ModelConfig(CLAUDE_SONNET, "claude", priority=0),
    ],
    ModelCapability.PLANNING: [
        ModelConfig(CLAUDE_SONNET, "claude", priority=1),
        ModelConfig(GEMINI_PRO, "gemini", priority=0),
    ],
    ModelCapability.REVIEW: [
        ModelConfig(CLAUDE_OPUS, "claude", priority=1, supports_thinking=True),
        ModelConfig(CLAUDE_SONNET, "claude", priority=0),
    ],
    ModelCapability.FAST_TASK: [
        ModelConfig(GEMINI_FLASH, "gemini", priority=1),
        ModelConfig(CLAUDE_HAIKU, "claude", priority=0),
    ],
    ModelCapability.CONTEXT_HEAVY: [
        ModelConfig(CLAUDE_SONNET, "claude", priority=1),  # 200K context
        ModelConfig(GEMINI_PRO, "gemini", priority=0),  # 1M context
    ],
    ModelCapability.WORKER: [
        ModelConfig(GEMINI_FLASH, "gemini", priority=1),
    ],
    ModelCapability.SUPERVISOR_PRIMARY: [
        ModelConfig(CLAUDE_SONNET, "claude", priority=1),
    ],
    ModelCapability.SUPERVISOR_AUDIT: [
        ModelConfig(GEMINI_PRO, "gemini", priority=1),
    ],
    ModelCapability.REASONING: [
        ModelConfig(CLAUDE_OPUS, "claude", priority=1, supports_thinking=True),
        ModelConfig(GEMINI_PRO, "gemini", priority=0),
    ],
}


@dataclass
class ModelRegistry:
    """Central registry for model selection based on capabilities.

    Usage:
        registry = ModelRegistry()
        model, provider = registry.get_model(ModelCapability.CODING)
        model, provider = registry.get_model(ModelCapability.FAST_TASK, prefer="gemini_preferred")
    """

    capability_models: dict[ModelCapability, list[ModelConfig]] = field(
        default_factory=lambda: dict(DEFAULT_CAPABILITY_MODELS)
    )
    circuit_breakers: dict[str, CircuitBreakerState] = field(default_factory=dict)

    # Circuit breaker configuration
    failure_threshold: int = 3  # Open after 3 consecutive failures
    recovery_timeout_seconds: int = 60  # Half-open after 60s

    def get_model(
        self,
        capability: ModelCapability,
        prefer: ProviderPreference = "either",
        complexity_tier: int = 1,
    ) -> tuple[str, Literal["claude", "gemini"]]:
        """Get the best model for a capability.

        Args:
            capability: What the model needs to do
            prefer: Provider preference
            complexity_tier: 1-4, higher tiers may get stronger models

        Returns:
            Tuple of (model_id, provider)

        Raises:
            ValueError: If no suitable model found
        """
        models = self.capability_models.get(capability)
        if not models:
            raise ValueError(f"No models registered for capability: {capability}")

        # Filter by provider preference
        if prefer == "claude_preferred":
            preferred = [m for m in models if m.provider == "claude"]
            fallback = [m for m in models if m.provider == "gemini"]
        elif prefer == "gemini_preferred":
            preferred = [m for m in models if m.provider == "gemini"]
            fallback = [m for m in models if m.provider == "claude"]
        else:
            preferred = models
            fallback = []

        # Apply complexity tier override
        if complexity_tier >= 3 and capability in (
            ModelCapability.CODING,
            ModelCapability.PLANNING,
        ):
            # Upgrade to reasoning model for complex tasks
            tier_models = self.capability_models.get(ModelCapability.REASONING, [])
            if tier_models:
                preferred = tier_models + preferred

        # Sort preferred by priority, then fallback by priority
        # This ensures preferred providers come first, then fallback within each group
        preferred_sorted = sorted(preferred, key=lambda m: -m.priority)
        fallback_sorted = sorted(fallback, key=lambda m: -m.priority)
        candidates = preferred_sorted + fallback_sorted

        # Apply circuit breaker filtering
        for model in candidates:
            if not self._is_circuit_open(model.provider):
                logger.debug(
                    "model_selected",
                    capability=capability.value,
                    model=model.model_id,
                    provider=model.provider,
                )
                return model.model_id, model.provider

        # All circuits open - try first available anyway (reset circuit)
        if candidates:
            first = candidates[0]
            logger.warning(
                "all_circuits_open_using_first",
                capability=capability.value,
                model=first.model_id,
            )
            self._close_circuit(first.provider)
            return first.model_id, first.provider

        raise ValueError(f"No available models for capability: {capability}")

    def record_success(self, provider: Literal["claude", "gemini"]) -> None:
        """Record a successful call to reset circuit breaker.

        Args:
            provider: Provider that succeeded
        """
        if provider in self.circuit_breakers:
            self.circuit_breakers[provider].failures = 0
            self.circuit_breakers[provider].is_open = False
            logger.debug("circuit_closed_on_success", provider=provider)

    def record_failure(self, provider: Literal["claude", "gemini"]) -> None:
        """Record a failed call to potentially open circuit breaker.

        Args:
            provider: Provider that failed
        """
        if provider not in self.circuit_breakers:
            self.circuit_breakers[provider] = CircuitBreakerState()

        state = self.circuit_breakers[provider]
        state.failures += 1
        state.last_failure = datetime.now(UTC)

        if state.failures >= self.failure_threshold:
            state.is_open = True
            state.half_open_at = datetime.now(UTC)
            logger.warning(
                "circuit_opened",
                provider=provider,
                failures=state.failures,
            )

    def _is_circuit_open(self, provider: Literal["claude", "gemini"]) -> bool:
        """Check if circuit is open for a provider.

        Args:
            provider: Provider to check

        Returns:
            True if circuit is open (should skip this provider)
        """
        if provider not in self.circuit_breakers:
            return False

        state = self.circuit_breakers[provider]
        if not state.is_open:
            return False

        # Check if recovery timeout has passed (half-open)
        if state.half_open_at:
            elapsed = (datetime.now(UTC) - state.half_open_at).total_seconds()
            if elapsed >= self.recovery_timeout_seconds:
                logger.info("circuit_half_open", provider=provider)
                return False  # Allow one request through

        return True

    def _close_circuit(self, provider: Literal["claude", "gemini"]) -> None:
        """Force close a circuit breaker.

        Args:
            provider: Provider to close circuit for
        """
        if provider in self.circuit_breakers:
            self.circuit_breakers[provider].is_open = False
            self.circuit_breakers[provider].failures = 0
            logger.info("circuit_force_closed", provider=provider)

    def get_fallback(
        self,
        capability: ModelCapability,
        failed_provider: Literal["claude", "gemini"],
    ) -> tuple[str, Literal["claude", "gemini"]] | None:
        """Get fallback model after primary fails.

        Args:
            capability: What the model needs to do
            failed_provider: Provider that just failed

        Returns:
            Tuple of (model_id, provider) or None if no fallback
        """
        models = self.capability_models.get(capability, [])
        fallbacks = [m for m in models if m.provider != failed_provider]

        if fallbacks:
            best = max(fallbacks, key=lambda m: m.priority)
            logger.info(
                "fallback_selected",
                capability=capability.value,
                model=best.model_id,
                failed_provider=failed_provider,
            )
            return best.model_id, best.provider

        return None


class TaskPhase(str, Enum):
    """Phases of task execution."""

    PLANNING = "planning"
    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    FIX = "fix"


@dataclass
class ModelSelection:
    """Result of model selection with full context."""

    model_id: str
    provider: Literal["claude", "gemini"]
    capability: ModelCapability
    reason: str


class ModelFactory:
    """Factory for DRY model selection.

    Wraps ModelRegistry with higher-level API that maps task context
    to capabilities, then to models.

    Usage:
        factory = ModelFactory()

        # For task execution
        selection = factory.get_model(
            task_type="coding",
            complexity=2,
            phase=TaskPhase.IMPLEMENTATION,
        )

        # For fix agent
        selection = factory.get_model_for_escalation(
            level="WORKER",  # or "SUPERVISOR"
            attempt=1,
        )
    """

    def __init__(self, registry: ModelRegistry | None = None):
        """Initialize the factory.

        Args:
            registry: Optional registry to use (defaults to global singleton)
        """
        self.registry = registry or get_registry()

    def get_model(
        self,
        task_type: str = "coding",
        complexity: int = 1,
        phase: TaskPhase = TaskPhase.IMPLEMENTATION,
        require_tools: bool = False,
        provider_preference: ProviderPreference = "either",
    ) -> ModelSelection:
        """Get the best model for a task context.

        Args:
            task_type: Type of task (coding, planning, review)
            complexity: 1-4, higher = more complex
            phase: Current execution phase
            require_tools: Whether tools/function calling is required
            provider_preference: Preferred provider

        Returns:
            ModelSelection with model_id, provider, and reasoning
        """
        # Map task context to capability
        capability = self._map_to_capability(task_type, phase)

        # Get model from registry
        model_id, provider = self.registry.get_model(
            capability=capability,
            prefer=provider_preference,
            complexity_tier=complexity,
        )

        reason = f"{task_type}/{phase.value} -> {capability.value} -> {model_id}"
        logger.info(
            "model_selected_by_factory",
            task_type=task_type,
            complexity=complexity,
            phase=phase.value,
            capability=capability.value,
            model=model_id,
            provider=provider,
        )

        return ModelSelection(
            model_id=model_id,
            provider=provider,
            capability=capability,
            reason=reason,
        )

    def get_model_for_escalation(
        self,
        level: Literal["WORKER", "SUPERVISOR"],
        attempt: int,
    ) -> ModelSelection:
        """Get model for 3-2-1 escalation.

        Args:
            level: Current escalation level
            attempt: Current attempt number (1-indexed)

        Returns:
            ModelSelection for the escalation level
        """
        if level == "WORKER":
            capability = ModelCapability.WORKER
        else:
            # SUPERVISOR: attempt 1 = PRIMARY (Sonnet), attempt 2 = AUDIT (Pro)
            if attempt <= 1:
                capability = ModelCapability.SUPERVISOR_PRIMARY
            else:
                capability = ModelCapability.SUPERVISOR_AUDIT

        model_id, provider = self.registry.get_model(capability)

        reason = f"escalation/{level}/attempt-{attempt} -> {capability.value}"
        logger.info(
            "model_selected_for_escalation",
            escalation_level=level,
            attempt=attempt,
            capability=capability.value,
            model=model_id,
            provider=provider,
        )

        return ModelSelection(
            model_id=model_id,
            provider=provider,
            capability=capability,
            reason=reason,
        )

    def _map_to_capability(
        self,
        task_type: str,
        phase: TaskPhase,
    ) -> ModelCapability:
        """Map task context to capability.

        Args:
            task_type: Type of task
            phase: Current phase

        Returns:
            ModelCapability to use
        """
        # Phase-based mapping
        if phase == TaskPhase.PLANNING:
            return ModelCapability.PLANNING
        elif phase == TaskPhase.REVIEW:
            return ModelCapability.REVIEW
        elif phase == TaskPhase.ANALYSIS:
            return ModelCapability.CONTEXT_HEAVY
        elif phase == TaskPhase.FIX:
            return ModelCapability.WORKER

        # Task type based mapping for implementation
        if task_type == "review":
            return ModelCapability.REVIEW
        elif task_type == "planning":
            return ModelCapability.PLANNING
        elif task_type in ("fast", "extraction", "validation"):
            return ModelCapability.FAST_TASK
        else:
            return ModelCapability.CODING

    def record_result(
        self,
        provider: Literal["claude", "gemini"],
        success: bool,
    ) -> None:
        """Record the result of using a model.

        Updates circuit breaker state in the registry.

        Args:
            provider: Provider that was used
            success: Whether the call succeeded
        """
        if success:
            self.registry.record_success(provider)
        else:
            self.registry.record_failure(provider)


# Global singleton
_registry: ModelRegistry | None = None
_factory: ModelFactory | None = None


def get_registry() -> ModelRegistry:
    """Get the global model registry singleton.

    Returns:
        ModelRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def get_factory() -> ModelFactory:
    """Get the global model factory singleton.

    Returns:
        ModelFactory instance
    """
    global _factory
    if _factory is None:
        _factory = ModelFactory()
    return _factory
