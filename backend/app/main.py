"""SummitFlow FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    accepted_specs,
    agent_sessions,
    build,
    capabilities,
    celery_endpoints,
    checkpoints,
    components,
    context,
    diary,
    evidence,
    explorer,
    hooks,
    memory,
    notifications,
    observations,
    patterns,
    projects,
    prompts,
    roundtable,
    tasks,
    tdd_tests,
    terminal,
    terminal_sessions,
)
from .services import terminal_lifecycle
from .storage.connection import init_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and services on startup."""
    init_schema()
    # Reconcile terminal sessions DB with tmux state
    terminal_lifecycle.reconcile_on_startup()
    yield


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
app.include_router(roundtable.router, prefix="/api", tags=["roundtable"])
app.include_router(terminal.router, tags=["terminal"])
app.include_router(terminal_sessions.router, tags=["terminal"])
app.include_router(observations.router, prefix="/api/projects", tags=["observations"])
app.include_router(context.router, prefix="/api/projects", tags=["context"])
app.include_router(checkpoints.router, prefix="/api/projects", tags=["checkpoints"])
app.include_router(hooks.router, prefix="/api", tags=["hooks"])
app.include_router(diary.router, prefix="/api/projects", tags=["learning"])
app.include_router(patterns.router, prefix="/api/projects", tags=["learning"])
app.include_router(memory.router, prefix="/api", tags=["memory"])
app.include_router(components.router, prefix="/api/projects", tags=["tdd"])
app.include_router(capabilities.router, prefix="/api/projects", tags=["tdd"])
app.include_router(tdd_tests.router, prefix="/api/projects", tags=["tdd"])
app.include_router(agent_sessions.router, prefix="/api/projects", tags=["tdd"])
app.include_router(accepted_specs.router, prefix="/api/projects", tags=["tdd"])
app.include_router(build.router, prefix="/api", tags=["build"])
app.include_router(prompts.router, prefix="/api", tags=["prompts"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "summitflow"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "SummitFlow API", "docs": "/docs"}
