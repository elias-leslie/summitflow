# CLAUDE.md

SummitFlow - AI-assisted software development platform.

## Quick Reference

| Action | Command |
|--------|---------|
| Start backend | `cd backend && uvicorn app.main:app --reload --port 8001` |
| Start frontend | `cd frontend && npm run dev` |
| Run tests | `cd backend && pytest` |
| Create schema | `cd backend && python -m app.storage.connection` |

## Project Structure

- `backend/app/api/` - FastAPI routers
- `backend/app/services/` - Business logic
- `backend/app/storage/` - Database access
- `frontend/app/` - Next.js pages
- `frontend/components/` - React components

## Database

PostgreSQL database: `summitflow`

Core tables:
- `projects` - Registered target applications
- `features` - Feature tracking per project
- `acceptance_criteria` - Feature verification criteria
- `artifacts` - Evidence (screenshots, logs)
- `sitemap_entries` - Discovered endpoints

## API Conventions

- All endpoints scoped by `project_id`
- Timestamps in UTC (ISO 8601)
- IDs are prefixed (e.g., `FEAT-001`, `AC-001`)

## Migration Plan

Extracted from portfolio-ai. See:
- Plan: `/home/kasadis/.claude/plans/sparkling-meandering-cascade.md`
- Epic: `portfolio-ai-43g`
- Phase 1: `portfolio-ai-2kp`
