# SummitFlow

AI-assisted software development platform.

## Overview

SummitFlow provides developer tooling for any software project:
- **Features**: Track features with acceptance criteria and verification
- **Evidence**: Capture screenshots, console logs, network activity for verification
- **Vision**: Strategic goals and progress tracking
- **Sitemap**: Endpoint discovery and health monitoring
- **Files**: Codebase analysis and metrics

## Architecture

```
summitflow/
├── backend/           # FastAPI backend
│   ├── app/
│   │   ├── api/       # REST endpoints
│   │   ├── services/  # Business logic
│   │   ├── models/    # Pydantic models
│   │   ├── storage/   # Database access
│   │   └── utils/
│   └── tests/
├── frontend/          # Next.js frontend
│   ├── app/           # Pages (App Router)
│   ├── components/
│   └── lib/
└── data/              # Artifacts, evidence
```

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+

### Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Create database
createdb summitflow

# Run schema
python -m app.storage.connection

# Start server
uvicorn app.main:app --reload --port 8001
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### Register a Project

```bash
curl -X POST http://localhost:8001/api/projects \
  -H "Content-Type: application/json" \
  -d '{"id": "portfolio-ai", "name": "Portfolio AI", "base_url": "http://localhost:8000"}'
```

## First Project: Portfolio AI

Portfolio AI is the first registered project. SummitFlow extracted from portfolio-ai to be reusable across all projects.

## Status

**Phase 1: Foundation** - In Progress

See `/home/kasadis/.claude/plans/sparkling-meandering-cascade.md` for full migration plan.
