"""Locating the Jobinator-4000 backend for ``st jobs …``.

Jobinator serves its endpoints at the application root (``/api/postings``,
``/api/applications``, …), so this uses :mod:`cli._project_client` rather than
the project-scoped base client. Everything here is configuration; the resolution
stack and transport live there.
"""

from __future__ import annotations

from pathlib import Path

from ._project_client import (
    ProjectApi,
    ProjectApiClient,
    ProjectApiConnectError,
    ResolvedURL,
    resolve_api_url,
)

JOBS_API = ProjectApi(
    project_id="jobinator-4000",
    env_var="ST_JOBS_API_URL",
    default_url="http://localhost:8014",
)

#: Agent-backed commands (evaluate, tailor) and a synchronous scan run for
#: minutes, not seconds. A 30s default would time out the client while the work
#: it started keeps running server-side and lands in the database anyway — a
#: failure report for a success.
AGENT_TIMEOUT = 600.0

JobsConnectError = ProjectApiConnectError
JobsClient = ProjectApiClient


def resolve_jobs_api_url(*, remote: bool = False, cwd: Path | None = None) -> ResolvedURL:
    return resolve_api_url(JOBS_API, remote=remote, cwd=cwd)


__all__ = [
    "AGENT_TIMEOUT",
    "JOBS_API",
    "JobsClient",
    "JobsConnectError",
    "ResolvedURL",
    "resolve_jobs_api_url",
]
