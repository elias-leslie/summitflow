"""SummitFlow FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    beads,
    celery_endpoints,
    evidence,
    explorer,
    features,
    hooks,
    notifications,
    observations,
    projects,
    roundtable,
    tasks,
    terminal,
    terminal_sessions,
    vision_content,
    vision_goals,
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
app.include_router(features.router, prefix="/api", tags=["features"])
app.include_router(evidence.router, prefix="/api", tags=["evidence"])
app.include_router(vision_goals.router, prefix="/api", tags=["vision"])
app.include_router(vision_content.router, prefix="/api", tags=["vision"])
app.include_router(explorer.router, prefix="/api/projects", tags=["explorer"])
app.include_router(celery_endpoints.router, tags=["celery"])
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(beads.router, prefix="/api", tags=["beads"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(roundtable.router, prefix="/api", tags=["roundtable"])
app.include_router(terminal.router, tags=["terminal"])
app.include_router(terminal_sessions.router, tags=["terminal"])
app.include_router(observations.router, prefix="/api/projects", tags=["observations"])
app.include_router(hooks.router, prefix="/api", tags=["hooks"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "summitflow"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "SummitFlow API", "docs": "/docs"}
