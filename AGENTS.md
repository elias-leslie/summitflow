# SummitFlow Developer Guide

This document provides essential information for agents and developers working on the SummitFlow codebase.

## Project Structure

- **Backend:** `backend/` (Python, FastAPI, SQLAlchemy, Celery)
- **Frontend:** `frontend/` (Next.js 16, React 19, TypeScript, Tailwind CSS)

## Backend Development (`backend/`)

### Environment & Build
- **Dependency Manager:** Uses `uv` (implied by `uv.lock`) or standard pip.
- **Build System:** `hatchling` (configured in `pyproject.toml`).

### Commands
Run these commands from the `backend/` directory:

| Action | Command | Notes |
| :--- | :--- | :--- |
| **Test All** | `pytest` | Runs standard tests (skips slow/e2e) |
| **Test Full** | `pytest -m ""` | Runs ALL tests including slow/e2e |
| **Test Single** | `pytest tests/path/to/test.py` | Run specific test file |
| **Test Function** | `pytest tests/path/to/test.py::test_name` | Run specific test function |
| **Lint** | `ruff check .` | Checks for linting errors |
| **Format** | `ruff check --fix .` | Auto-fixes linting/formatting issues |
| **Type Check** | `mypy .` | Runs static type checking (strict mode) |
| **Run Dev** | `uvicorn app.main:app --reload` | Starts local dev server |

### Code Style & Conventions
- **Formatting:** Handled by `ruff` (line length 100).
- **Typing:** Strict typing required. Use `mypy` to verify. All functions must have type hints.
- **Async:** Heavy use of `asyncio` / `await`. Ensure DB and network calls are async.
- **Imports:**
  - Standard library first.
  - Third-party packages second.
  - Local application imports third (relative imports preferred within modules, e.g., `from .api import ...`).
- **Frameworks:**
  - **FastAPI:** Use `APIRouter` for endpoints.
  - **Pydantic:** Use models for all request/response schemas.
  - **SQLAlchemy:** Async session management.
- **Naming:**
  - Directories/Files: `snake_case` (e.g., `agent_sessions.py`).
  - Classes: `PascalCase`.
  - Variables/Functions: `snake_case`.

## Frontend Development (`frontend/`)

### Environment & Build
- **Package Manager:** `pnpm`
- **Framework:** Next.js 16 (App Router), React 19

### Commands
Run these commands from the `frontend/` directory:

| Action | Command | Notes |
| :--- | :--- | :--- |
| **Install** | `pnpm install` | Install dependencies |
| **Dev Server** | `pnpm dev` | Starts dev server on port 3001 |
| **Build** | `pnpm build` | Production build |
| **Lint** | `pnpm lint` | Runs `biome lint .` |
| **Format** | `pnpm format` | Runs `biome format --write .` |
| **Fix** | `pnpm lint:fix` | Runs `biome check --write .` |
| **Test** | `pnpm test` | Runs `vitest` |
| **Test Single** | `pnpm test path/to/test.test.ts` | Run specific test file |

### Code Style & Conventions
- **Tooling:** Uses **Biome** for both linting and formatting (replaces ESLint/Prettier).
- **Formatting:** 2 spaces indent, single quotes, no semicolons (where optional).
- **Imports:** Use `@/` alias for root-relative imports (e.g., `import { Button } from '@/components/ui/button'`).
- **Styling:** Tailwind CSS v4. Use utility classes.
- **Components:**
  - Functional components with TypeScript interfaces for props.
  - File naming: `kebab-case` for component files (e.g., `scroll-area.tsx`, `agent-card.tsx`).
  - Directory structure: Group by feature (e.g., `components/dashboard/`).
  - UI Library: Radix UI primitives located in `components/ui/`.
- **State:** React Query (`@tanstack/react-query`) for server state.
- **Naming:**
  - Components: `PascalCase` (in code).
  - Files: `kebab-case` (e.g., `my-component.tsx`).
  - Hooks: `useCamelCase`.

## Agent Hub Integration
The `agent-hub` service provides memory and completion capabilities.
- **Location:** `/home/kasadis/agent-hub/` (Sibling directory)
- **Role:** Handles routing (Claude/Gemini), ACE memory (Neo4j), and tool execution.
- **Client:** `backend/app/services/agent_hub_client.py` uses the Hub's REST API.

## Custom CLI Tools (`st` & `dt`)

This repository includes custom CLI tools for task management (`st`) and development standards (`dt`). **Use these whenever possible** as they are optimized for the agentic workflow.

### Task Management (`st`)
The `st` command interacts with the SummitFlow system (tasks, checkpoints, memory, etc.).

| Action | Command | Description |
| :--- | :--- | :--- |
| **Find Work** | `st ready` | List unblocked tasks ready for work |
| **Context** | `st context <id>` | Get full task context (subtasks, steps) |
| **Claim** | `st claim <id>` | **CRITICAL:** Claim task & create git/DB checkpoint |
| **Complete** | `st done <id>` | Complete task/subtask & merge changes |
| **Abandon** | `st abandon <id>` | Rollback changes & restore DB checkpoint |
| **Checkpoints** | `st checkpoints` | List active checkpoints |
| **Health** | `st health` | Show quality gate status |
| **Memory** | `st memory save "..."` | Save learnings to ACE memory system |

### Development Tools (`dt`)
The `dt` command wraps standard tools (ruff, mypy, pytest, biome) with optimized "TOON" output for agents (compact, noise-reduced).

| Action | Command | Description |
| :--- | :--- | :--- |
| **Full Check** | `dt --check` | Run ALL checks (backend+frontend tests/lint) |
| **Fast Check** | `dt --quick` | Run lint/types only (no tests) |
| **Changes Only** | `dt -q -d` | **Recommended:** Quick check on *changed files only* |
| **Fix** | `dt --fix` | Auto-fix linting issues & install deps |
| **Backend** | `dt pytest`, `dt ruff` | Run specific backend tool |
| **Frontend** | `dt biome`, `dt tsc` | Run specific frontend tool |

## General Guidelines

- **Safety:** Never push to git unless explicitly asked.
- **Secrets:** Do not commit `.env` files or secrets.
- **Paths:** Always use absolute paths when using tool definitions, but relative paths are fine for git/shell commands if you are in the correct working directory.
- **Verification:** Always run `dt --quick --changed-only` (or `dt -q -d`) after modifying code to ensure quality standards.
- **Commits:** Use `scripts/commit.sh` for streamlined commits with automated quality gates and TOON output.
