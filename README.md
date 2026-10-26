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

### Guards on irreversible agent actions

A PreToolUse hook shared by Claude Code and Codex
([`publication_hook.py`](backend/app/services/publication_hook.py)) denies
direct publication (`git push` and similar) so that releases go through the
checked `st vcs publish` path, and denies a fixed set of irreversible commands:
hard resets, `git clean`, recursive deletes of workspace and backup roots, and
disk, snapshot, backup and Proxmox destruction. The hook uses only the Python
standard library, so it keeps working when the backend environment is broken.
[`destructive_path_guard.py`](backend/app/services/destructive_path_guard.py)
refuses deletes of paths that another live agent session in the same checkout
still owns. [`command_guard.py`](backend/app/services/command_guard.py) holds
the shared command classification used by `st` and the tests.

### Backup and disaster recovery

- btrbk is the only local backup: six Btrfs subvolumes go to the T7 every 4
  hours and 7 days are kept.
- One daily restic job reads those snapshots at their real paths into a Google
  Drive repository, with the PostgreSQL and Redis dumps and a few Proxmox
  sources. It checks itself, prunes itself and retries on the next run. A systemd
  user timer (`summitflow-host-backup.timer`) drives all of it; nothing is
  scheduled per project.
- `st backup status` says whether backups are current. `st backup restore
  PROJECT --to DIR` brings a project back from Drive into a new directory.
- Backup storage on the T7 is read-only outside scheduled runs.
- Runbooks: [hard-loss recovery](docs/disaster-recovery.md) and
  [host recovery](docs/native-host-recovery.md).

### Host and fleet operations

- [`host-monitor/`](host-monitor/README.md) is an unprivileged Rust collector
  that samples CPU, memory, disk, network, process and service metrics into
  SQLite. It is the only writer; `st monitor` and the API read it.
- [Fleet session control](docs/fleet-session-control.md): `st sessions start`
  launches and resumes agent sessions in a registered project checkout, with
  retained request IDs so an uncertain launch is retried instead of duplicated.
- [Admission control for heavy work](docs/transient-heavy-work.md): test
  suites, builds, installs and scans queue for a small number of shared slots,
  and a second slot opens only when memory headroom and pressure allow it.

### Extensions

Projects add their own `st` commands through versioned extensions instead of
patching SummitFlow. An extension declares its identity, version, namespace
and supported contract versions in a trusted registry, and runs as a separate
executable. [`summitflow-st-sdk`](packages/st-sdk) is the shared Python
library those executables use for project context, HTTP calls and output. See
[ST extension architecture](docs/st-extension-architecture.md).

## Current scope

The FastAPI backend, Next.js operator interface, CLI, and workflow workers are
implemented for a self-hosted development environment. Browser evidence, routed
AI completions, push notifications, and offsite backups depend on their configured
integrations. A passing check or successful screenshot records the observed
behavior; it does not establish that every project feature works.

## Getting started

For a new source installation, follow the [local Docker source-stack guide](docs/project-guide.md#quickstart-local-source-stack-with-docker-compose).
It covers PostgreSQL, Redis, Hatchet, SummitFlow, and the adjacent Agent Hub
checkout. Native development instructions are in the same guide.

`st` is SummitFlow's own command-line tool and ships in this repository
(`scripts/st`, backed by `backend/cli`). In an already configured workspace,
open SummitFlow at <http://localhost:3001> or inspect available CLI commands:

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
supports caching and coordination; Hatchet dispatches workflows. Artifact storage
has its own configuration and history. Agent Hub owns
shared agent prompts, routed completions, and memory; those records remain in
Agent Hub. Browser runtimes and push delivery are additional
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
