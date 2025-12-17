"""SummitFlow FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import features, projects, sitemap

app = FastAPI(
    title="SummitFlow",
    description="AI-assisted software development platform",
    version="0.1.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://192.168.8.233:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(sitemap.router, prefix="/api/projects", tags=["sitemap"])
app.include_router(features.router, prefix="/api", tags=["features"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "summitflow"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "SummitFlow API", "docs": "/docs"}
