"""Agent Hub client wrapper providing LLMClient-compatible interface.

Re-exports LLMResponse, LLMClient, AgentHubLLMClient, get_agent,
get_sync_client, get_async_client, and Agent Hub config constants."""

from __future__ import annotations

from agent_hub import AgentHubClient
from agent_hub.models import MessageInput, ToolResultMessage

from ..logging_config import get_logger
from ._agent_hub_config import (
    AGENT_HUB_API_KEY,
    AGENT_HUB_URL,
    get_async_client,
    get_sync_client,
    response_to_llm_response,
)
from ._agent_hub_types import LLMClient, LLMResponse

logger = get_logger(__name__)

# Module-level constants
DEFAULT_TIMEOUT: float | None = None
DEFAULT_CLIENT_NAME: str = "summitflow"
DEFAULT_PROJECT_ID: str = "summitflow"
MODEL_NAME_PREFIX: str = "agent"


class AgentHubLLMClient(LLMClient):
    """LLM client that routes all requests through Agent Hub."""

    def __init__(
        self,
        agent_slug: str,
        project_id: str = DEFAULT_PROJECT_ID,
        use_memory: bool = True,
        memory_group_id: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize with agent_slug (required) and optional overrides."""
        if not agent_slug:
            raise ValueError(
                "agent_slug is required. See Agent Hub /api/agents for available agents."
            )
        self.agent_slug = agent_slug
        self.base_url = base_url or AGENT_HUB_URL
        self.api_key = api_key or AGENT_HUB_API_KEY
        self.project_id = project_id
        self.use_memory = use_memory
        self.memory_group_id = memory_group_id
        self._client: AgentHubClient | None = None

    def _get_client(self) -> AgentHubClient:
        """Get or create Agent Hub client."""
        if self._client is None:
            self._client = get_sync_client(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=DEFAULT_TIMEOUT,
                client_name=DEFAULT_CLIENT_NAME,
            )
        return self._client

    def is_available(self) -> bool:
        """Check if Agent Hub is available."""
        try:
            self._get_client().list_sessions(page_size=1)
            return True
        except Exception as e:
            logger.warning("Agent Hub not available: %s", e)
            return False

    def get_model_name(self) -> str:
        """Get the model/agent identifier."""
        return f"{MODEL_NAME_PREFIX}:{self.agent_slug}"

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 1.0,
        purpose: str | None = None,
        task_id: str | None = None,
        use_memory: bool | None = None,
        memory_group_id: str | None = None,
        session_id: str | None = None,
        enable_caching: bool = True,
        **_kwargs: object,
    ) -> LLMResponse:
        """Generate completion via Agent Hub; raises RuntimeError on failure."""
        effective_use_memory = use_memory if use_memory is not None else self.use_memory
        effective_memory_group = memory_group_id or self.memory_group_id
        msgs: list[dict[str, str] | MessageInput | ToolResultMessage] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        try:
            response = self._get_client().complete(
                agent_slug=self.agent_slug,
                messages=msgs,
                temperature=temperature,
                project_id=self.project_id,
                session_id=session_id,
                purpose=purpose,
                external_id=task_id,
                enable_caching=enable_caching,
                use_memory=effective_use_memory,
                memory_group_id=effective_memory_group,
            )
            return response_to_llm_response(response)
        except Exception as e:
            logger.error("Agent Hub request failed: %s", e)
            raise RuntimeError(f"Agent Hub request failed: {e}") from e

    def close(self) -> None:
        """Close the client connection."""
        if self._client:
            self._client.close()
            self._client = None


def get_agent(agent_slug: str) -> AgentHubLLMClient:
    """Get a configured AgentHubLLMClient for the given agent slug."""
    return AgentHubLLMClient(agent_slug=agent_slug)


__all__ = [
    "AGENT_HUB_API_KEY",
    "AGENT_HUB_URL",
    "AgentHubLLMClient",
    "LLMClient",
    "LLMResponse",
    "get_agent",
    "get_async_client",
    "get_sync_client",
]
