"""Unit tests for ModelRegistry.

Tests capability-to-model mapping, provider preference, circuit breaker, etc.
"""

from __future__ import annotations

import pytest

from app.constants import CLAUDE_OPUS, CLAUDE_SONNET, GEMINI_FLASH, GEMINI_PRO
from app.services.model_registry import (
    ModelCapability,
    ModelFactory,
    ModelRegistry,
    TaskPhase,
    get_factory,
    get_registry,
)


class TestModelCapabilityMapping:
    """Tests for capability to model mapping."""

    @pytest.fixture
    def registry(self) -> ModelRegistry:
        """Create a fresh registry for each test."""
        return ModelRegistry()

    def test_coding_returns_gemini_flash(self, registry: ModelRegistry) -> None:
        """CODING capability returns Gemini Flash (78% SWE-bench)."""
        model, provider = registry.get_model(ModelCapability.CODING)
        assert model == GEMINI_FLASH
        assert provider == "gemini"

    def test_planning_returns_claude_sonnet(self, registry: ModelRegistry) -> None:
        """PLANNING capability returns Claude Sonnet."""
        model, provider = registry.get_model(ModelCapability.PLANNING)
        assert model == CLAUDE_SONNET
        assert provider == "claude"

    def test_review_returns_claude_opus(self, registry: ModelRegistry) -> None:
        """REVIEW capability returns Claude Opus."""
        model, provider = registry.get_model(ModelCapability.REVIEW)
        assert model == CLAUDE_OPUS
        assert provider == "claude"

    def test_fast_task_returns_gemini_flash(self, registry: ModelRegistry) -> None:
        """FAST_TASK capability returns Gemini Flash."""
        model, provider = registry.get_model(ModelCapability.FAST_TASK)
        assert model == GEMINI_FLASH
        assert provider == "gemini"

    def test_worker_returns_gemini_flash(self, registry: ModelRegistry) -> None:
        """WORKER capability returns Gemini Flash."""
        model, provider = registry.get_model(ModelCapability.WORKER)
        assert model == GEMINI_FLASH
        assert provider == "gemini"

    def test_supervisor_primary_returns_sonnet(self, registry: ModelRegistry) -> None:
        """SUPERVISOR_PRIMARY returns Claude Sonnet."""
        model, provider = registry.get_model(ModelCapability.SUPERVISOR_PRIMARY)
        assert model == CLAUDE_SONNET
        assert provider == "claude"

    def test_supervisor_audit_returns_gemini_pro(self, registry: ModelRegistry) -> None:
        """SUPERVISOR_AUDIT returns Gemini Pro."""
        model, provider = registry.get_model(ModelCapability.SUPERVISOR_AUDIT)
        assert model == GEMINI_PRO
        assert provider == "gemini"


class TestProviderPreference:
    """Tests for provider preference selection."""

    @pytest.fixture
    def registry(self) -> ModelRegistry:
        """Create a fresh registry for each test."""
        return ModelRegistry()

    def test_claude_preferred_for_coding(self, registry: ModelRegistry) -> None:
        """With claude_preferred, CODING returns Claude Sonnet."""
        model, provider = registry.get_model(ModelCapability.CODING, prefer="claude_preferred")
        assert provider == "claude"
        assert model == CLAUDE_SONNET

    def test_gemini_preferred_for_planning(self, registry: ModelRegistry) -> None:
        """With gemini_preferred, PLANNING returns Gemini Pro."""
        model, provider = registry.get_model(ModelCapability.PLANNING, prefer="gemini_preferred")
        assert provider == "gemini"
        assert model == GEMINI_PRO


class TestComplexityTierOverride:
    """Tests for complexity tier upgrades."""

    @pytest.fixture
    def registry(self) -> ModelRegistry:
        """Create a fresh registry for each test."""
        return ModelRegistry()

    def test_tier_3_coding_upgrades_to_reasoning(self, registry: ModelRegistry) -> None:
        """Tier 3+ CODING task gets upgraded to reasoning model."""
        model, provider = registry.get_model(ModelCapability.CODING, complexity_tier=3)
        # Should get Opus (reasoning) instead of Flash (coding)
        assert model == CLAUDE_OPUS
        assert provider == "claude"

    def test_tier_1_coding_stays_default(self, registry: ModelRegistry) -> None:
        """Tier 1 CODING task stays at default."""
        model, provider = registry.get_model(ModelCapability.CODING, complexity_tier=1)
        assert model == GEMINI_FLASH
        assert provider == "gemini"


class TestCircuitBreaker:
    """Tests for circuit breaker functionality."""

    @pytest.fixture
    def registry(self) -> ModelRegistry:
        """Create a fresh registry for each test."""
        return ModelRegistry()

    def test_success_resets_failures(self, registry: ModelRegistry) -> None:
        """Successful call resets failure count."""
        registry.record_failure("claude")
        registry.record_failure("claude")
        registry.record_success("claude")

        assert registry.circuit_breakers["claude"].failures == 0
        assert registry.circuit_breakers["claude"].is_open is False

    def test_three_failures_opens_circuit(self, registry: ModelRegistry) -> None:
        """Three consecutive failures opens circuit."""
        registry.record_failure("gemini")
        registry.record_failure("gemini")
        registry.record_failure("gemini")

        assert registry.circuit_breakers["gemini"].is_open is True

    def test_open_circuit_triggers_fallback(self, registry: ModelRegistry) -> None:
        """Open circuit for one provider triggers fallback to other."""
        # Open gemini circuit
        for _ in range(3):
            registry.record_failure("gemini")

        # CODING normally returns gemini, but should fallback
        _model, provider = registry.get_model(ModelCapability.CODING)

        # Should get Claude fallback
        assert provider == "claude"

    def test_get_fallback_returns_other_provider(self, registry: ModelRegistry) -> None:
        """get_fallback returns model from other provider."""
        fallback = registry.get_fallback(ModelCapability.CODING, "gemini")

        assert fallback is not None
        _model, provider = fallback
        assert provider == "claude"

    def test_get_fallback_returns_none_if_no_alternative(self, registry: ModelRegistry) -> None:
        """get_fallback returns None if no alternative exists."""
        # WORKER only has gemini option
        fallback = registry.get_fallback(ModelCapability.WORKER, "gemini")
        assert fallback is None


class TestRegistrySingleton:
    """Tests for global registry singleton."""

    def test_get_registry_returns_same_instance(self) -> None:
        """get_registry returns the same instance."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_registry_has_all_capabilities(self) -> None:
        """Registry has models for all capabilities."""
        registry = get_registry()
        for cap in ModelCapability:
            # Should not raise
            registry.get_model(cap)


class TestInvalidCapability:
    """Tests for error handling."""

    def test_empty_capability_raises(self) -> None:
        """Empty capability models raises ValueError."""
        registry = ModelRegistry()
        registry.capability_models = {}  # Clear all

        with pytest.raises(ValueError, match="No models registered"):
            registry.get_model(ModelCapability.CODING)


class TestModelFactory:
    """Tests for ModelFactory."""

    @pytest.fixture
    def factory(self) -> ModelFactory:
        """Create a fresh factory for each test."""
        return ModelFactory(registry=ModelRegistry())

    def test_coding_task_implementation_phase(self, factory: ModelFactory) -> None:
        """Coding task in implementation phase gets coding model."""
        selection = factory.get_model(
            task_type="coding",
            phase=TaskPhase.IMPLEMENTATION,
        )
        assert selection.model_id == GEMINI_FLASH
        assert selection.capability == ModelCapability.CODING

    def test_planning_phase_overrides_task_type(self, factory: ModelFactory) -> None:
        """Planning phase gets planning model regardless of task type."""
        selection = factory.get_model(
            task_type="coding",
            phase=TaskPhase.PLANNING,
        )
        assert selection.model_id == CLAUDE_SONNET
        assert selection.capability == ModelCapability.PLANNING

    def test_review_phase_gets_review_model(self, factory: ModelFactory) -> None:
        """Review phase gets review model."""
        selection = factory.get_model(
            task_type="coding",
            phase=TaskPhase.REVIEW,
        )
        assert selection.model_id == CLAUDE_OPUS
        assert selection.capability == ModelCapability.REVIEW

    def test_fix_phase_gets_worker_model(self, factory: ModelFactory) -> None:
        """Fix phase gets worker model."""
        selection = factory.get_model(
            task_type="coding",
            phase=TaskPhase.FIX,
        )
        assert selection.model_id == GEMINI_FLASH
        assert selection.capability == ModelCapability.WORKER


class TestModelFactoryEscalation:
    """Tests for factory escalation support."""

    @pytest.fixture
    def factory(self) -> ModelFactory:
        """Create a fresh factory for each test."""
        return ModelFactory(registry=ModelRegistry())

    def test_worker_escalation(self, factory: ModelFactory) -> None:
        """WORKER escalation gets Flash."""
        selection = factory.get_model_for_escalation(level="WORKER", attempt=1)
        assert selection.model_id == GEMINI_FLASH
        assert selection.capability == ModelCapability.WORKER

    def test_supervisor_first_attempt(self, factory: ModelFactory) -> None:
        """SUPERVISOR first attempt gets Sonnet."""
        selection = factory.get_model_for_escalation(level="SUPERVISOR", attempt=1)
        assert selection.model_id == CLAUDE_SONNET
        assert selection.capability == ModelCapability.SUPERVISOR_PRIMARY

    def test_supervisor_second_attempt(self, factory: ModelFactory) -> None:
        """SUPERVISOR second attempt gets Pro."""
        selection = factory.get_model_for_escalation(level="SUPERVISOR", attempt=2)
        assert selection.model_id == GEMINI_PRO
        assert selection.capability == ModelCapability.SUPERVISOR_AUDIT


class TestModelFactoryCircuitBreaker:
    """Tests for factory circuit breaker integration."""

    @pytest.fixture
    def factory(self) -> ModelFactory:
        """Create a fresh factory for each test."""
        return ModelFactory(registry=ModelRegistry())

    def test_record_success_resets_circuit(self, factory: ModelFactory) -> None:
        """Recording success resets circuit breaker."""
        # Open circuit
        for _ in range(3):
            factory.record_result("gemini", success=False)

        # Reset with success
        factory.record_result("gemini", success=True)

        # Circuit should be closed
        assert factory.registry.circuit_breakers["gemini"].is_open is False

    def test_record_failures_opens_circuit(self, factory: ModelFactory) -> None:
        """Recording failures opens circuit breaker."""
        for _ in range(3):
            factory.record_result("claude", success=False)

        assert factory.registry.circuit_breakers["claude"].is_open is True

    def test_open_circuit_triggers_fallback(self, factory: ModelFactory) -> None:
        """Open circuit triggers fallback to other provider."""
        # Open gemini circuit
        for _ in range(3):
            factory.record_result("gemini", success=False)

        # Coding normally returns gemini, should fallback to claude
        selection = factory.get_model(
            task_type="coding",
            phase=TaskPhase.IMPLEMENTATION,
        )

        assert selection.provider == "claude"


class TestFactorySingleton:
    """Tests for factory singleton."""

    def test_get_factory_returns_same_instance(self) -> None:
        """get_factory returns the same instance."""
        f1 = get_factory()
        f2 = get_factory()
        assert f1 is f2
