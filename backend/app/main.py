"""SummitFlow FastAPI application."""

import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    agent_sessions,
    autonomous,
    backups,
    celery_endpoints,
    checkpoints,
    context,
    design_standards,
    diary,
    evidence,
    explorer,
    git,
    hooks,
    implementation,
    memory,
    notifications,
    observations,
    patterns,
    projects,
    prompts,
    refactor_sessions,
    schemas,
    tasks,
    tdd,
    tdd_tests,
)
from .config import REDIS_URL
from .schemas.health import ComponentHealth, DetailedHealthResponse
from .storage.connection import init_schema

# Track application start time for uptime calculation
_app_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001",
        "http://192.168.8.233:3001",
        "https://dev.summitflow.dev",
        "http://localhost:4001",
        "https://test1.summitflow.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(evidence.router, prefix="/api", tags=["evidence"])
app.include_router(explorer.router, prefix="/api/projects", tags=["explorer"])
app.include_router(celery_endpoints.router, tags=["celery"])
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(observations.router, prefix="/api/projects", tags=["observations"])
app.include_router(context.router, prefix="/api/projects", tags=["context"])
app.include_router(checkpoints.router, prefix="/api/projects", tags=["checkpoints"])
app.include_router(hooks.router, prefix="/api", tags=["hooks"])
app.include_router(diary.router, prefix="/api/projects", tags=["learning"])
app.include_router(patterns.router, prefix="/api/projects", tags=["learning"])
app.include_router(memory.router, prefix="/api", tags=["memory"])
app.include_router(tdd_tests.router, prefix="/api/projects", tags=["tdd"])
app.include_router(agent_sessions.router, prefix="/api/projects", tags=["tdd"])
app.include_router(prompts.router, prefix="/api", tags=["prompts"])
app.include_router(tdd.router, prefix="/api", tags=["tdd"])
app.include_router(implementation.router, prefix="/api/projects", tags=["implementation"])
app.include_router(autonomous.router, prefix="/api/projects", tags=["autonomous"])
app.include_router(refactor_sessions.router, prefix="/api/projects", tags=["refactoring"])
app.include_router(schemas.router, prefix="/api", tags=["schemas"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(backups.router, prefix="/api", tags=["backups"])
app.include_router(design_standards.router, prefix="/api", tags=["design-standards"])

from .api import ideas, ws_execution  # noqa: E402

app.include_router(ideas.router, prefix="/api", tags=["ideas"])
app.include_router(ws_execution.router, tags=["execution"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "summitflow"}


@app.get("/api/health/detailed")
async def detailed_health_check() -> DetailedHealthResponse:
    """Detailed health check endpoint with database, cache, and uptime information."""
    # Check database health
    db_health = _check_database_health()

    # Check Redis cache health
    cache_health = _check_cache_health()

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
        # Connect to Redis DB 1 (same as used by Celery and rate limiter)
        r = redis.from_url(f"{REDIS_URL}/1")
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
