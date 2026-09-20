"""Compatibility alias for the public ST SDK configuration module."""

from __future__ import annotations

import sys

from st_sdk import config as _implementation
from st_sdk.config import (
    Config as Config,
)
from st_sdk.config import (
    get_agent_hub_url as get_agent_hub_url,
)
from st_sdk.config import (
    get_available_projects as get_available_projects,
)
from st_sdk.config import (
    get_config as get_config,
)
from st_sdk.config import (
    get_config_optional as get_config_optional,
)
from st_sdk.config import (
    get_project_override as get_project_override,
)
from st_sdk.config import (
    get_project_root_path as get_project_root_path,
)
from st_sdk.config import (
    set_project_override as set_project_override,
)

from app.config import AGENT_HUB_URL, DEFAULT_API_BASE

__all__ = [
    "Config",
    "get_agent_hub_url",
    "get_available_projects",
    "get_config",
    "get_config_optional",
    "get_project_override",
    "get_project_root_path",
    "set_project_override",
]

_implementation.configure_defaults(api_base=DEFAULT_API_BASE, agent_hub_url=AGENT_HUB_URL)
sys.modules[__name__] = _implementation
