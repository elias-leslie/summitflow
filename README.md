# SummitFlow

SummitFlow is a self-hosted project operations control plane for developers
working with AI agents. It brings tasks, automation, source inspection, runtime
operations, and verification evidence into one operator interface and the `st`
CLI.

## What it does

- Tracks tasks, subtasks, dependencies, delivery status, and verification evidence.
- Registers projects and provides their overview, execution board, files, Git,
  backups, and settings.
- Runs scheduled and event-driven development workflows through Hatchet.
- Coordinates agent work with project ownership, quality gates, checkpoints,
  and task history.
- Provides managed browser checks, service rebuilds, database inspection, and
  recovery tools through `st`.

## Current scope

The FastAPI backend, Next.js operator interface, CLI, and workflow workers are
implemented for a self-hosted development environment. Browser evidence, routed
AI completions, push notifications, and remote backups depend on their configured
integrations. A passing check or successful screenshot records the observed
behavior; it does not establish that every project feature works.

## Getting started

For a new source installation, follow the [local Docker source-stack guide](docs/project-guide.md#quickstart-local-source-stack-with-docker-compose).
It covers PostgreSQL, Redis, Hatchet, SummitFlow, and the adjacent Agent Hub
checkout. Native development instructions are in the same guide.

In an already configured managed workspace, open SummitFlow at
<http://localhost:3001> or inspect available CLI commands:

```bash
st --help
st projects list
```

Native development uses Python 3.13+, Node.js 20+, pnpm 10+, PostgreSQL, and
Redis. Workflow execution also needs Hatchet. The source-stack guide distinguishes
native prerequisites from container build prerequisites.

## Runtime, data, and integrations

The managed frontend uses port 3001 and the backend port 8001, with `/health` on
the backend. `project.identity.json` declares both services, the Hatchet worker,
the host monitor, and the optional Codex session-sync worker.

PostgreSQL stores project and task state, schedules, and evidence records. Redis
supports caching and coordination; Hatchet dispatches workflows. Backup sources
and artifact storage have their own configuration and history. Agent Hub owns
shared agent prompts, routed completions, and memory; those records remain in
Agent Hub. Browser runtimes, SMB backup targets, and push delivery are additional
configured capabilities.

## Development and verification

`backend/` contains the API, CLI, workers, migrations, and Python tests.
`frontend/` contains the operator UI and its tests. `packages/` holds shared
workspace components; `docker/` and `scripts/` contain setup and runtime support.

In a managed checkout, run `st check --quick --changed-only`. Use targeted
`st check` commands for changed behavior, and `st browser` for rendered routes
and interactions. Deployed code changes use `st service rebuild summitflow
--detach`. These checks verify the exercised code and runtime; external
integrations require their own configured evidence.

## Documentation

- [Technical guide and source-stack setup](docs/project-guide.md)
- [Project catalog and lifecycle rules](docs/project-catalog.md)
- [Registered project README template](docs/project-readme-template.md)
- [ST extension architecture](docs/st-extension-architecture.md)
- [Local workflow checklist](docs/lean-local-workflow-checklist.md)
- [Disaster recovery](docs/disaster-recovery.md)
- [Security reporting](SECURITY.md)
- [Apache 2.0 license](LICENSE) and [notice](NOTICE)
