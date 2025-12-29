"""Terminal Service - FastAPI Application.

Independent microservice for web terminal functionality.
Runs on port 8002, separate from main SummitFlow backend.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import sessions, terminal
from .config import CORS_ORIGINS, TERMINAL_PORT
from .logging_config import get_logger
from .services import lifecycle

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    # Startup: reconcile DB with tmux state
    logger.info("terminal_service_starting", port=TERMINAL_PORT)
    try:
        stats = lifecycle.reconcile_on_startup()
        logger.info("startup_reconciliation_complete", **stats)
    except Exception as e:
        logger.error("startup_reconciliation_failed", error=str(e))

    yield

    # Shutdown
    logger.info("terminal_service_stopping")


app = FastAPI(
    title="SummitFlow Terminal",
    description="Web terminal service for SummitFlow",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(terminal.router)
app.include_router(sessions.router)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "terminal"}


def main() -> None:
    """Run the terminal service."""
    uvicorn.run(
        "terminal.main:app",
        host="0.0.0.0",
        port=TERMINAL_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
