"""Contract tests for Agent Hub API integration.

These tests verify that SummitFlow's usage of Agent Hub conforms to
the expected API contracts. They can run in two modes:

1. Mock mode (default): Uses mocked responses to verify SummitFlow handles
   responses correctly. Fast, runs in CI without dependencies.

2. Live mode (--run-live-agent-hub): Actually calls Agent Hub to verify
   both request and response contracts. Requires Agent Hub running.

Usage:
    pytest tests/integration/test_agent_hub_contract.py  # mock mode
    pytest tests/integration/test_agent_hub_contract.py --run-live-agent-hub  # live mode
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, ClassVar, cast
from unittest.mock import MagicMock, patch

import pytest
from agent_hub.exceptions import (
    AgentHubError,
    AuthenticationError,
    ClientDisabledError,
    RateLimitError,
    ServerError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Contract Schemas - Define expected API shapes
# ---------------------------------------------------------------------------


@dataclass
class CompletionRequestContract:
    """Expected shape of completion request to Agent Hub."""

    required_fields: ClassVar[set[str]] = {"messages", "project_id"}
    optional_fields: ClassVar[set[str]] = {
        "model",
        "agent_slug",
        "temperature",
        "session_id",
        "purpose",
        "external_id",
        "enable_caching",
        "routing_config",
        "tools",
        "enable_programmatic_tools",
        "container_id",
    }

    @classmethod
    def validate_request(cls, request: dict[str, Any]) -> list[str]:
        """Validate request conforms to contract. Returns list of violations."""
        violations = []

        # Check required fields
        for field in cls.required_fields:
            if field not in request:
                violations.append(f"Missing required field: {field}")

        # Validate messages format
        if "messages" in request:
            messages = request["messages"]
            if not isinstance(messages, list):
                violations.append("messages must be a list")
            else:
                for i, msg in enumerate(messages):
                    if not isinstance(msg, dict):
                        violations.append(f"messages[{i}] must be a dict")
                        continue

                    msg_dict = cast(dict[str, Any], msg)
                    if "role" not in msg_dict or "content" not in msg_dict:
                        violations.append(f"messages[{i}] must have 'role' and 'content'")
                    elif msg_dict["role"] not in ("user", "assistant", "system"):
                        violations.append(f"messages[{i}].role must be user/assistant/system")

        return violations


@dataclass
class CompletionResponseContract:
    """Expected shape of completion response from Agent Hub."""

    required_fields: ClassVar[set[str]] = {"content", "model", "provider", "usage", "session_id"}
    usage_required_fields: ClassVar[set[str]] = {"input_tokens", "output_tokens", "total_tokens"}

    @classmethod
    def validate_response(cls, response: Any) -> list[str]:
        """Validate response conforms to contract. Returns list of violations."""
        violations = []

        # Check required fields
        for field in cls.required_fields:
            if not hasattr(response, field):
                violations.append(f"Missing required field: {field}")

        # Validate usage structure
        if hasattr(response, "usage"):
            usage = response.usage
            for field in cls.usage_required_fields:
                if not hasattr(usage, field):
                    violations.append(f"usage missing field: {field}")

        # Validate types
        if hasattr(response, "content") and not isinstance(response.content, str):
            violations.append("content must be a string")
        if hasattr(response, "session_id") and not isinstance(response.session_id, str):
            violations.append("session_id must be a string")
        if hasattr(response, "from_cache") and not isinstance(response.from_cache, bool):
            violations.append("from_cache must be a boolean")

        return violations


@dataclass
class SessionResponseContract:
    """Expected shape of session response from Agent Hub."""

    required_fields: ClassVar[set[str]] = {"id", "status"}

    @classmethod
    def validate_response(cls, response: Any) -> list[str]:
        """Validate response conforms to contract."""
        violations = []
        for field in cls.required_fields:
            if not hasattr(response, field):
                violations.append(f"Missing required field: {field}")
        return violations


# ---------------------------------------------------------------------------
# Mock Factories - Create valid mock responses
# ---------------------------------------------------------------------------


def create_mock_usage() -> MagicMock:
    """Create mock usage object matching Agent Hub schema."""
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.total_tokens = 150
    usage.cache_creation_input_tokens = 0
    usage.cache_read_input_tokens = 0
    return usage


def create_mock_completion_response(
    content: str = "Test response",
    model: str = "claude-sonnet-4-5",
    provider: str = "claude",
    session_id: str = "session-123",
    from_cache: bool = False,
    finish_reason: str = "end_turn",
) -> MagicMock:
    """Create mock completion response matching Agent Hub schema."""
    response = MagicMock()
    response.content = content
    response.model = model
    response.provider = provider
    response.session_id = session_id
    response.from_cache = from_cache
    response.finish_reason = finish_reason
    response.usage = create_mock_usage()
    response.tool_calls = None
    response.container = None
    return response


def create_mock_session_response(
    session_id: str = "session-123",
    status: str = "active",
) -> MagicMock:
    """Create mock session response matching Agent Hub schema."""
    response = MagicMock()
    response.id = session_id
    response.status = status
    response.messages = []
    response.project_id = "test-project"
    return response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_agent_hub_client() -> MagicMock:
    """Create a mock Agent Hub client for tests that patch get_sync_client."""
    return MagicMock()


@pytest.fixture
def live_agent_hub_available(request: pytest.FixtureRequest) -> None:
    """Check if live Agent Hub is available for testing."""
    if not request.config.getoption("--run-live-agent-hub", default=False):
        pytest.skip("Live Agent Hub tests require --run-live-agent-hub flag")

    # Check if Agent Hub is actually running
    import urllib.request

    url = os.getenv("AGENT_HUB_URL", "http://localhost:8003")
    try:
        urllib.request.urlopen(f"{url}/health", timeout=2)
    except Exception:
        pytest.skip(f"Agent Hub not running at {url}")


# ---------------------------------------------------------------------------
# Contract Tests - Mock Mode
# ---------------------------------------------------------------------------


class TestCompletionContract:
    """Tests for the /api/complete endpoint contract."""

    def test_rejects_system_prompt_override(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify Agent Hub wrapper rejects local system prompt overrides."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.return_value = create_mock_completion_response()

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            with pytest.raises(ValueError, match="system overrides are not supported"):
                client.generate(
                    prompt="Hello",
                    system="You are a helpful assistant",
                    temperature=0.7,
                    purpose="test",
                )

        mock_agent_hub_client.complete.assert_not_called()

    def test_request_format_without_system_prompt(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify request format when no system prompt is provided."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.return_value = create_mock_completion_response()

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            client.generate(prompt="Hello")

        call_kwargs = mock_agent_hub_client.complete.call_args.kwargs
        messages = call_kwargs["messages"]

        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "Hello"}

    def test_response_parsing(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify SummitFlow correctly parses completion response."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_response = create_mock_completion_response(
            content="Test output",
            model="claude-sonnet-4-5",
            provider="claude",
            session_id="sess-abc",
            from_cache=True,
        )
        mock_agent_hub_client.complete.return_value = mock_response

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            result = client.generate(prompt="Hello")

        # Verify LLMResponse fields are correctly populated
        assert result.content == "Test output"
        assert result.model == "claude-sonnet-4-5"
        assert result.provider == "claude"
        assert result.usage["input_tokens"] == 100
        assert result.usage["output_tokens"] == 50
        assert result.usage["total_tokens"] == 150
        assert result.raw_response["session_id"] == "sess-abc"
        assert result.raw_response["from_cache"]

    def test_response_contract_validation(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify response conforms to expected contract."""
        mock_response = create_mock_completion_response()

        violations = CompletionResponseContract.validate_response(mock_response)
        assert violations == [], f"Response contract violations: {violations}"

    def test_external_id_passed_for_task_linkage(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify task_id is passed as external_id for session linkage."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.return_value = create_mock_completion_response()

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            client.generate(prompt="Hello", task_id="task-12345678")

        call_kwargs = mock_agent_hub_client.complete.call_args.kwargs
        assert call_kwargs.get("external_id") == "task-12345678"

    def test_caching_enabled_by_default(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify caching is enabled by default."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.return_value = create_mock_completion_response()

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            client.generate(prompt="Hello")

        call_kwargs = mock_agent_hub_client.complete.call_args.kwargs
        assert call_kwargs.get("enable_caching")


class TestErrorHandlingContract:
    """Tests for error handling contracts."""

    def test_authentication_error_handling(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify AuthenticationError (401) is handled correctly."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.side_effect = AuthenticationError("Invalid credentials")

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            with pytest.raises(RuntimeError, match="Agent Hub request failed"):
                client.generate(prompt="Hello")

    def test_rate_limit_error_handling(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify RateLimitError (429) is handled correctly."""
        from app.services.agent_hub_client import AgentHubLLMClient

        error = RateLimitError("Rate limit exceeded")
        error.retry_after = 30.0
        mock_agent_hub_client.complete.side_effect = error

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            with pytest.raises(RuntimeError, match="Agent Hub request failed"):
                client.generate(prompt="Hello")

    def test_validation_error_handling(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify ValidationError (422) is handled correctly."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.side_effect = ValidationError("Invalid request format")

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            with pytest.raises(RuntimeError, match="Agent Hub request failed"):
                client.generate(prompt="Hello")

    def test_server_error_handling(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify ServerError (5xx) is handled correctly."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.side_effect = ServerError("Internal server error")

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            with pytest.raises(RuntimeError, match="Agent Hub request failed"):
                client.generate(prompt="Hello")

    def test_client_disabled_error_handling(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify ClientDisabledError (dormant mode) is handled correctly."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.side_effect = ClientDisabledError(
            "Client disabled by kill switch"
        )

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            with pytest.raises(RuntimeError, match="Agent Hub request failed"):
                client.generate(prompt="Hello")

    def test_generic_agent_hub_error_handling(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify generic AgentHubError is handled correctly."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.complete.side_effect = AgentHubError("Unknown error")

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            with pytest.raises(RuntimeError, match="Agent Hub request failed"):
                client.generate(prompt="Hello")

    def test_wrapper_uses_shared_sync_client_configuration(self) -> None:
        """Verify AgentHubLLMClient delegates transport creation to get_sync_client."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_client = MagicMock()

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_client,
        ) as mock_factory:
            client = AgentHubLLMClient(
                agent_slug="claude-sonnet-4-5",
                base_url="http://test:8003",
                api_key="test-key",
            )
            assert client._get_client() is mock_client

        mock_factory.assert_called_once_with(
            base_url="http://test:8003",
            api_key="test-key",
            timeout=600.0,
            client_name="summitflow",
        )


class TestClientConfigurationContract:
    """Tests for client configuration contracts."""

    def test_sync_client_configuration(self) -> None:
        """Verify get_sync_client passes correct configuration."""
        with patch("app.services._agent_hub_config.AgentHubClient") as mock_class:
            from app.services.agent_hub_client import get_sync_client

            get_sync_client(
                base_url="http://test:8003",
                api_key="test-key",
                timeout=120.0,
                client_name="test-client",
            )

            mock_class.assert_called_once()
            call_kwargs = mock_class.call_args.kwargs
            assert call_kwargs["base_url"] == "http://test:8003"
            assert call_kwargs["api_key"] == "test-key"
            assert call_kwargs["timeout"] == 120.0
            assert call_kwargs["client_name"] == "test-client"

    def test_async_client_configuration(self) -> None:
        """Verify get_async_client passes correct configuration."""
        with patch("app.services._agent_hub_config.AsyncAgentHubClient") as mock_class:
            from app.services.agent_hub_client import get_async_client

            get_async_client(
                base_url="http://test:8003",
                api_key="test-key",
                timeout=120.0,
                client_name="test-client",
            )

            mock_class.assert_called_once()
            call_kwargs = mock_class.call_args.kwargs
            assert call_kwargs["base_url"] == "http://test:8003"
            assert call_kwargs["api_key"] == "test-key"
            assert call_kwargs["timeout"] == 120.0
            assert call_kwargs["client_name"] == "test-client"

    def test_client_credentials_injected(self) -> None:
        """Verify client credentials are injected from environment."""
        with (
            patch("app.services._agent_hub_config.AgentHubClient") as mock_class,
            patch("app.services._agent_hub_config.SUMMITFLOW_CLIENT_ID", "test-client-id"),
            patch("app.services._agent_hub_config.SUMMITFLOW_REQUEST_SOURCE", "test-source"),
        ):
            from app.services.agent_hub_client import get_sync_client

            get_sync_client()

            call_kwargs = mock_class.call_args.kwargs
            assert call_kwargs["client_id"] == "test-client-id"
            assert call_kwargs["request_source"] == "test-source"


class TestSessionContract:
    """Tests for session management contract."""

    def test_availability_check_uses_list_sessions(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify is_available() uses list_sessions for health check."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.list_sessions.return_value = MagicMock()

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            result = client.is_available()

        assert result
        mock_agent_hub_client.list_sessions.assert_called_once_with(page_size=1)

    def test_availability_check_returns_false_on_error(self, mock_agent_hub_client: MagicMock) -> None:
        """Verify is_available() returns False when Agent Hub is down."""
        from app.services.agent_hub_client import AgentHubLLMClient

        mock_agent_hub_client.list_sessions.side_effect = Exception("Connection refused")

        with patch(
            "app.services.agent_hub_client.get_sync_client",
            return_value=mock_agent_hub_client,
        ):
            client = AgentHubLLMClient(agent_slug="claude-sonnet-4-5")
            result = client.is_available()

        assert not result


# ---------------------------------------------------------------------------
# Live Integration Tests (require --run-live-agent-hub flag)
# ---------------------------------------------------------------------------

# Use dedicated test project to avoid polluting production data
CONTRACT_TEST_PROJECT_ID = "summitflow-contract-test"


@pytest.fixture
def live_client_with_cleanup(live_agent_hub_available: None) -> Any:
    """Provides a live client and cleans up created sessions after test."""
    from app.services.agent_hub_client import get_sync_client

    client = get_sync_client()
    created_sessions: list[str] = []

    class TrackedClient:
        """Wrapper that tracks created sessions for cleanup."""

        def complete(self, **kwargs: Any) -> Any:
            # Force test project ID to avoid production pollution
            kwargs["project_id"] = CONTRACT_TEST_PROJECT_ID
            kwargs.setdefault("purpose", "contract_test")
            response = client.complete(**kwargs)
            if response.session_id:
                created_sessions.append(response.session_id)
            return response

        def get_session(self, session_id: str) -> Any:
            return client.get_session(session_id)

        def delete_session(self, session_id: str) -> Any:
            return client.delete_session(session_id)

    yield TrackedClient()

    # Cleanup: delete all created sessions
    for session_id in created_sessions:
        try:
            client.delete_session(session_id)
        except Exception:
            pass  # Best effort cleanup


@pytest.mark.integration
class TestLiveAgentHubContract:
    """Live integration tests against running Agent Hub.

    These tests verify actual API behavior and are skipped by default.
    Run with: pytest --run-live-agent-hub -m integration

    IMPORTANT:
    - Tests use a dedicated project ID (summitflow-contract-test)
    - All created sessions are cleaned up after tests
    - Requires explicit opt-in via --run-live-agent-hub flag
    """

    def test_live_completion_request(self, live_agent_hub_available: None) -> None:
        """Test actual completion request against Agent Hub."""
        from app.services.agent_hub_client import AgentHubLLMClient

        # Use test project ID to avoid production pollution
        client = AgentHubLLMClient(
            agent_slug="claude-sonnet-4-5",
            project_id=CONTRACT_TEST_PROJECT_ID,
        )
        response = client.generate(
            prompt="Say 'hello' and nothing else.",
            temperature=0.0,
            purpose="contract_test",
        )

        # Validate response structure
        assert response.content is not None
        assert isinstance(response.content, str)
        assert len(response.content) > 0
        assert response.model is not None
        assert response.provider == "claude"
        assert response.usage["total_tokens"] > 0
        assert response.raw_response["session_id"] is not None

        # Cleanup: delete the session
        from app.services.agent_hub_client import get_sync_client

        try:
            cleanup_client = get_sync_client()
            cleanup_client.delete_session(response.raw_response["session_id"])
        except Exception:
            pass  # Best effort cleanup

    def test_live_session_created(self, live_client_with_cleanup: Any) -> None:
        """Test that completion creates a session."""
        client = live_client_with_cleanup
        response = client.complete(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hi"}],
        )

        # Verify session was created
        assert response.session_id is not None

        # Verify session can be retrieved
        session = client.get_session(response.session_id)
        assert session.id == response.session_id
        assert session.status is not None
        # Session cleanup handled by fixture

    def test_live_error_on_invalid_model(self, live_agent_hub_available: None) -> None:
        """Test that invalid model triggers appropriate error."""
        from app.services.agent_hub_client import get_sync_client

        client = get_sync_client()

        # This should fail before creating a session, so no cleanup needed
        with pytest.raises(AgentHubError):
            client.complete(
                model="nonexistent-model-xyz",
                messages=[{"role": "user", "content": "Hi"}],
                project_id=CONTRACT_TEST_PROJECT_ID,
            )


# Note: --run-live-agent-hub option is defined in conftest.py
