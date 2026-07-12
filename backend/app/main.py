"""SummitFlow FastAPI application."""

import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from .access_control import access_control_middleware
from .api import (
    activity,
    agent_hub,
    agent_sessions,
    auth,
    auto_fix,
    autonomous,
    backups,
    checkpoints,
    console_errors,
    db_workbench,
    design_assets,
    design_standards,
    docker,
    events,
    explorer,
    files,
    git,
    graphify,
    mockups,
    notes,
    notifications,
    projects,
    quality_gate,
    refactor_sessions,
    schemas,
    snapshots,
    system,
    tasks,
    viewer,
    ws_execution,
)
from .config import settings
from .exception_handlers import setup_exception_handlers
from .logging_config import SyslogPrefixFormatter, configure_logging, get_logger
from .schemas.health import ComponentHealth, DetailedHealthResponse, ReadinessResponse

_APP_VERSION = "0.1.0"

# Configure structured logging (skip in test mode - tests configure their own logging)
if not os.getenv("PYTEST_CURRENT_TEST"):
    configure_logging()

    # Configure uvicorn loggers to use syslog prefixes for journald
    import logging

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger = logging.getLogger("uvicorn")

    # Apply syslog formatter to all uvicorn handlers
    for _uvicorn_log in [uvicorn_access_logger, uvicorn_error_logger, uvicorn_logger]:
        for _handler in _uvicorn_log.handlers:
            _handler.setFormatter(
                SyslogPrefixFormatter(
                    "%(levelname)s:     %(message)s"  # Match uvicorn's format
                )
            )

logger = get_logger(__name__)

# Track application start time for uptime calculation
_app_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Start connection pools and background services after external migrations."""
    from .services.runtime_metrics_sampler import (
        start_runtime_metrics_sampler,
        stop_runtime_metrics_sampler,
    )
    from .storage.connection import close_pool, open_pool

    # Skip heavy DB init during pytest (tests mock the DB anyway)
    runtime_metrics_task = None
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        open_pool()  # Initialize connection pool
        runtime_metrics_task = start_runtime_metrics_sampler()
    try:
        yield
    finally:
        # Cleanup on shutdown
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            if runtime_metrics_task is not None:
                await stop_runtime_metrics_sampler()
            close_pool()


_cors_middleware = [
    Middleware(
        cast(Any, CORSMiddleware),
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = FastAPI(
    title="SummitFlow",
    description="AI-assisted software development platform",
    version=_APP_VERSION,
    redirect_slashes=False,  # Prevent 307 redirects that expose backend URL
    lifespan=lifespan,
    middleware=_cors_middleware,
)

app.middleware("http")(access_control_middleware)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(viewer.router, prefix="/api/viewer", tags=["viewer"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(explorer.router, prefix="/api/projects", tags=["explorer"])
app.include_router(files.project_router, prefix="/api/projects", tags=["files"])
app.include_router(files.global_router, prefix="/api", tags=["files"])
app.include_router(graphify.router, prefix="/api/projects", tags=["graphify"])
app.include_router(db_workbench.router, prefix="/api/projects", tags=["db-workbench"])

app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(notes.router, prefix="/api", tags=["notes"])
app.include_router(agent_sessions.router, prefix="/api/projects", tags=["agent-sessions"])
app.include_router(autonomous.router, prefix="/api/projects", tags=["autonomous"])
app.include_router(refactor_sessions.router, prefix="/api/projects", tags=["refactoring"])
app.include_router(schemas.router, prefix="/api", tags=["schemas"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(backups.router, prefix="/api", tags=["backups"])
app.include_router(snapshots.router, prefix="/api", tags=["snapshots"])
app.include_router(design_standards.router, prefix="/api", tags=["design-standards"])
app.include_router(design_assets.router, prefix="/api", tags=["design-assets"])
app.include_router(quality_gate.router, prefix="/api", tags=["quality-gate"])
app.include_router(auto_fix.router, prefix="/api", tags=["quality-gate"])
app.include_router(console_errors.router, prefix="/api", tags=["quality-gate"])
app.include_router(activity.router, prefix="/api", tags=["activity"])
app.include_router(mockups.router, prefix="/api", tags=["mockups"])
app.include_router(checkpoints.router, tags=["checkpoints"])
app.include_router(agent_hub.router, prefix="/api", tags=["agent-hub"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(system.router, tags=["system"])
app.include_router(ws_execution.router, tags=["execution"])
app.include_router(docker.router, prefix="/api/docker", tags=["runtime"])


# Global exception handlers for consistent error responses
setup_exception_handlers(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Process liveness check with no dependency or schema I/O."""
    return {"status": "healthy", "service": "summitflow"}


@app.get("/api/health/ready", response_model=ReadinessResponse)
async def readiness_check(response: Response) -> ReadinessResponse:
    """Return fresh dependency and Alembic checks for traffic readiness."""
    import asyncio

    db_health, cache_health, schema_health = await asyncio.gather(
        asyncio.to_thread(_check_database_health),
        asyncio.to_thread(_check_cache_health),
        asyncio.to_thread(_check_schema_health),
    )
    ready = all(
        component.status != "unhealthy"
        for component in (db_health, cache_health, schema_health)
    )
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        service="summitflow",
        timestamp=datetime.now(UTC),
        database=db_health,
        cache=cache_health,
        schema=schema_health,
        version=_APP_VERSION,
    )


async def _fetch_detailed_health() -> DetailedHealthResponse:
    """
    Internal function to fetch fresh detailed health data.

    Separated from endpoint to enable caching. Runs sync checks in thread pool.
    """
    import asyncio

    # Run sync health checks in thread pool
    db_health, cache_health = await asyncio.gather(
        asyncio.to_thread(_check_database_health),
        asyncio.to_thread(_check_cache_health),
    )

    # Determine overall status
    overall_status = "healthy"
    if db_health.status == "unhealthy" or cache_health.status == "unhealthy":
        overall_status = "unhealthy"
    elif db_health.status == "degraded" or cache_health.status == "degraded":
        overall_status = "degraded"

    # Calculate uptime
    uptime_seconds = time.time() - _app_start_time

    return DetailedHealthResponse(
        status=overall_status,
        service="summitflow",
        timestamp=datetime.now(UTC),
        uptime_seconds=uptime_seconds,
        database=db_health,
        cache=cache_health,
        version=_APP_VERSION,
    )


@app.get("/api/health/detailed")
async def detailed_health_check() -> DetailedHealthResponse:
    """
    Detailed health check with database, cache, and uptime information.

    Uses caching with background refresh:
    - Returns cached response if < 60s old (fast path)
    - Triggers background refresh on every request
    - Concurrent requests share the same refresh
    """
    from .services.health_cache import get_detailed_health_cache

    cache = get_detailed_health_cache()
    result = await cache.get_or_refresh(_fetch_detailed_health)
    if result is None:
        raise HTTPException(status_code=503, detail="Health check unavailable")
    return cast(DetailedHealthResponse, result)


@app.get("/api/health/cache")
async def health_cache_info() -> dict[str, str | int | bool | None]:
    """
    Get health cache statistics.

    Returns cache state, age, and refresh status for debugging.
    """
    from .services.health_cache import get_detailed_health_cache

    cache = get_detailed_health_cache()
    return cache.stats


def _check_database_health() -> ComponentHealth:
    """Check PostgreSQL database connectivity and response time using connection pool."""
    from .storage.connection import get_cursor

    start_time = time.time()
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        response_time_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            status="healthy",
            message="Database connection successful (pooled)",
            response_time_ms=round(response_time_ms, 2),
        )
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            status="unhealthy",
            message=f"Database connection failed: {e!s}",
            response_time_ms=round(response_time_ms, 2),
        )


@lru_cache(maxsize=1)
def _expected_schema_heads() -> frozenset[str]:
    """Load the authoritative Alembic heads shipped with this application."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def _check_schema_health() -> ComponentHealth:
    """Check that the database is stamped at every authoritative Alembic head."""
    from .storage.connection import get_cursor

    start_time = time.time()
    try:
        expected = _expected_schema_heads()
        with get_cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            current = frozenset(str(row[0]) for row in cur.fetchall())
        response_time_ms = (time.time() - start_time) * 1000
        if current != expected:
            current_label = ",".join(sorted(current)) or "none"
            expected_label = ",".join(sorted(expected)) or "none"
            return ComponentHealth(
                status="unhealthy",
                message=(
                    "Database schema revision mismatch "
                    f"(current={current_label}; expected={expected_label})"
                ),
                response_time_ms=round(response_time_ms, 2),
            )
        return ComponentHealth(
            status="healthy",
            message=f"Database schema is current ({','.join(sorted(current))})",
            response_time_ms=round(response_time_ms, 2),
        )
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            status="unhealthy",
            message=f"Database schema check failed: {e!s}",
            response_time_ms=round(response_time_ms, 2),
        )


def _check_cache_health() -> ComponentHealth:
    """Check Redis cache connectivity and response time."""
    from .services.redis_pool import get_redis

    start_time = time.time()
    try:
        get_redis().ping()
        response_time_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            status="healthy",
            message="Cache connection successful",
            response_time_ms=round(response_time_ms, 2),
        )
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            status="unhealthy",
            message=f"Cache connection failed: {e!s}",
            response_time_ms=round(response_time_ms, 2),
        )


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "SummitFlow API", "docs": "/docs"}
