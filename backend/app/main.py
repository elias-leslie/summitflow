"""SummitFlow FastAPI application."""

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import (
    activity,
    agent_hub,
    agent_sessions,
    auto_fix,
    autonomous,
    backups,
    checkpoints,
    console_errors,
    context,
    design_standards,
    events,
    explorer,
    git,
    mockups,
    notifications,
    pipeline,
    projects,
    quality_gate,
    refactor_sessions,
    schemas,
    system,
    tasks,
    tdd,
    ws_execution,
)
from .config import REDIS_URL, settings
from .logging_config import get_logger
from .schemas.health import ComponentHealth, DetailedHealthResponse
from .storage.connection import init_schema

logger = get_logger(__name__)

# Track application start time for uptime calculation
_app_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize database, connection pool, and services on startup."""
    import os

    from .storage.connection import close_pool, open_pool

    # Skip heavy DB init during pytest (tests mock the DB anyway)
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        open_pool()  # Initialize connection pool
        init_schema()
    yield
    # Cleanup on shutdown
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        close_pool()


app = FastAPI(
    title="SummitFlow",
    description="AI-assisted software development platform",
    version="0.1.0",
    redirect_slashes=False,  # Prevent 307 redirects that expose backend URL
    lifespan=lifespan,
)

# CORS middleware - origins loaded from settings for cross-project communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(explorer.router, prefix="/api/projects", tags=["explorer"])

app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(agent_sessions.router, prefix="/api/projects", tags=["tdd"])
app.include_router(tdd.router, prefix="/api", tags=["tdd"])
app.include_router(autonomous.router, prefix="/api/projects", tags=["autonomous"])
app.include_router(refactor_sessions.router, prefix="/api/projects", tags=["refactoring"])
app.include_router(schemas.router, prefix="/api", tags=["schemas"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(backups.router, prefix="/api", tags=["backups"])
app.include_router(design_standards.router, prefix="/api", tags=["design-standards"])
app.include_router(quality_gate.router, prefix="/api", tags=["quality-gate"])
app.include_router(auto_fix.router, prefix="/api", tags=["quality-gate"])
app.include_router(console_errors.router, prefix="/api", tags=["quality-gate"])
app.include_router(activity.router, prefix="/api", tags=["activity"])
app.include_router(mockups.router, prefix="/api", tags=["mockups"])
app.include_router(context.router, prefix="/api", tags=["context"])
app.include_router(checkpoints.router, tags=["checkpoints"])
app.include_router(agent_hub.router, prefix="/api", tags=["agent-hub"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(pipeline.router, prefix="/api", tags=["pipeline"])
app.include_router(system.router, tags=["system"])
app.include_router(ws_execution.router, tags=["execution"])


# Global exception handlers for consistent error responses
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors with consistent JSON format."""
    # Sanitize errors: ctx may contain non-serializable objects (e.g. ValueError)
    errors = []
    for error in exc.errors():
        sanitized = dict(error)
        if "ctx" in sanitized:
            sanitized["ctx"] = {k: str(v) for k, v in sanitized["ctx"].items()}
        errors.append(sanitized)
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation Error",
            "detail": errors,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with consistent JSON format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
            "detail": exc.detail,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with consistent JSON format."""
    logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": "An unexpected error occurred. Please try again later.",
        },
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "summitflow"}


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
        version="0.1.0",
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
    from .storage.connection import get_connection

    start_time = time.time()
    try:
        with get_connection() as conn, conn.cursor() as cur:
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


def _check_cache_health() -> ComponentHealth:
    """Check Redis cache connectivity and response time."""
    start_time = time.time()
    try:
        # Connect to Redis DB 1 (shared with rate limiter and pub/sub)
        r = redis.from_url(f"{REDIS_URL}/1")  # type: ignore[no-untyped-call]
        r.ping()
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
