"""Compatibility alias for the public managed-project API client."""

from __future__ import annotations

import sys

from st_sdk import project_client as _implementation
from st_sdk.project_client import ProjectApi as ProjectApi
from st_sdk.project_client import ProjectApiClient as ProjectApiClient
from st_sdk.project_client import ProjectApiConnectError as ProjectApiConnectError
from st_sdk.project_client import ResolvedURL as ResolvedURL
from st_sdk.project_client import resolve_api_url as resolve_api_url

__all__ = [
    "ProjectApi",
    "ProjectApiClient",
    "ProjectApiConnectError",
    "ResolvedURL",
    "resolve_api_url",
]

sys.modules[__name__] = _implementation
