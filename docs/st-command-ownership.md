# ST command ownership inventory

Pre-migration evidence snapshot (base `4568b22b3`): `backend/cli/main.py` statically lists optional command
modules, subcommand groups, and forwarded root commands (`:46-156`), then adds
specific root aliases and hidden groups (`:267-397`). Optional import failure
produces an unavailable-command stub (`:162-193`). This is an inventory of the
registered public surface, not a claim that every optional module is currently
available.

There is no `st tasks` command. `tasks.py` callbacks are hoisted to root
(`create`, `list`, `ready`, `ready-all`, `context`, `export`, `cancel`, `pause`,
`reopen`, `delete`, `update`, `log`, `sync-progress`, `verify-plan`,
`autocode`, `critique`); the separate hidden group is `st task` (`main.py:200-208,
296-300`). `claim`, `done`, and `abandon` are root lifecycle commands. Hidden
`st progress` is only a migration hint (`:378-384`). Snapshot callbacks are
hoisted as root `snap`, `snaps`, `recover`, `rollback`, `prune`; hidden
`st autosnap` is timer/hook plumbing (`:273-276,392-397`). `st mandates` and
`st note` are root commands, not groups (`:304-313`).

## Approved destinations

Ranks and approved scopes are copied from `docs/st-extension-architecture.md`;
this inventory does not reorder them.

| Rank | Capability | Destination | Kind | Approved extraction scope |
|---:|---|---|---|---|
| 1 | browser | browser-automation | new | Runner, checks and automation; ST retains project/VM routing and safety adapters. |
| 2 | web | agent-hub | existing | Supported web-research CLI; move benchmark and preserve option/output parity. |
| 3 | ui, selection | desktop-automation | new | Platform operations and Aico protocol bridge; no active-desktop verification. |
| 4 | jobs | jobinator-4000 | existing | Domain CLI/client and tests. |
| 5 | portfolio | portfolio-ai | existing | Domain CLI/client and tests. |
| 6 | neri | neri | existing | Domain CLI, explicit Agent Hub and ST control adapters. |
| 7 | learn | learn-o-tron | existing | CLI, PTY and transcripts; public ST task-promotion interface. |
| 8 | graph/search | code-intelligence | new | Reusable intelligence with existing Explorer/index storage integration. |
| 9 | wiki | vault-tools | new | Filesystem/search/lint/ingest engine; canonical vault data preserved. |
| 10 | design | design-tools | new | CLI plus reusable generation/asset behavior; preserve project asset/storage contracts. |
| 11 | pulsebrief | Retired with owner approval | legacy | Missing engine with no local callers or schedules; remove broken wrapper and stale discovery. |
| 12 | Agent Hub administration | agent-hub | existing | Models, complete, memory, prompt, persona, agents, feedback, note and mandates; ST agent task/session orchestration remains core. |
| 13 | skills | agent-hub | existing | Distribution and harness tooling; canonical instructions remain with Agent Hub. |

## Root command/group ownership

Classes: **core** = ST owns orchestration/policy; **client** = ST CLI currently
calls an existing project owner; **executable wrapper** = ST invokes a local or
managed tool whose code/state is elsewhere; **mixed** = ownership/effects span
ST and another owner. “Owner” names canonical implementation/state owner, not
the current location of the Typer callback.

| Registered public surface (group boundary) | Class; implementation and actual owner/state | Dependencies, effects, callers/coupling |
|---|---|---|
| Root task callbacks listed above; `claim`, `done`, `abandon`; hidden `task`; `subtask`; `checkpoints` | **core** — callbacks in `commands/tasks.py`, `claim.py`, `done.py`, `abandon.py`, `subtask.py`, `checkpoints.py`; SummitFlow owns task/checkpoint records and lifecycle. | Uses `STClient`, output/context, DB events, and checkpoint metadata. Mutations include task lifecycle and claim/checkpoint transitions. Root hoisting and alias behavior are in `main.py:200-208,267-300,387-397`. |
| `projects`; root `pulse`, `lease`, `migrate-branches` | **core** — `commands/projects.py`, `pulse.py`, `lease.py`, `migrate_branches.py`; SummitFlow owns project registry and coordination policy. | Projects resolve registered project IDs/roots; pulse reads ST task/lane/agent state; leases use local files; migration changes VCS refs. See root registrations `main.py:307-310`. |
| `check`; root `db`; `test` (module `tests`); `dep` (module `deps`); `health` | **core** — `commands/check.py`, `db.py`, `tests.py`, `deps.py`, `health.py`; ST owns gate/DB command policy, while project manifests, external DBs, and test/package tools own execution inputs and durable data. | Runs quality, DB and dependency operations; root `check` and `db` are forwarded commands (`main.py:151-156,211-219`). Public group names are `test` and `dep`, not `tests` or `deps`. |
| `git`, `jj`, `vcs`; root `commit`, `migrate-branches` | **mixed** — ST command/coordination code in `commands/git.py`, `jj.py`, `vcs.py`, `migrate_branches.py`, `lib/commit_workflow.py`; Git/Jujutsu refs and workspaces are external state, while SummitFlow owns task-linked audit and publication workflow. | Invokes Git/JJ; commit workflow records task events and applies check/publication gates (`main.py:233-264,316-375`). Preserve safety and task linkage in ST. |
| `service`, `runtime`, `vm`, `docker`, `setup` | **core / executable wrappers** — ST owns managed-service, VM and setup policy in `commands/{service,runtime,vm,docker,setup}.py` and `lib/service_ops.py`; actual services, containers and guests own runtime state. | Executes service managers, Docker/VM adapters and setup tools; can affect live projects/hosts. These remain ST control adapters; the external tools themselves are not ST domain state. |
| `backup`; `cleanup`; `checkpoints`; root `snap`, `snaps`, `recover`, `rollback`, `prune`; hidden `autosnap` | **core / executable wrappers** — `commands/{backup,cleanup,checkpoints,snapshots,autosnapshot}.py`, `lib/{autosnapshot,quick_snapshots}.py`; ST owns policy/metadata, Btrfs/filesystems own snapshot bytes. | Backup/recovery/prune and cleanup can mutate or delete durable files/metadata; retain ST confirmation, recovery and timer/hook controls. Root snapshot and hidden autosnap registration: `main.py:158,267-276,390-397`. |
| `autonomous`, `claude`, `sessions`, `agent` | **mixed** — ST owns dispatch, task/session ownership and local control (`commands/{autonomous,claude,sessions,agent}.py`); Agent Hub/providers own model execution, and terminal tools own process/session resources. | `agent` uses `STClient` and `_session_resolver` while calling Agent Hub completion; preserve this orchestration in ST. Session events and runs cross ST/Agent Hub. |
| `complete` | **client** — `commands/complete.py`, `_complete_http.py`; Agent Hub owns completion route and result. | HTTP/auth/output helpers are ST-private; `agent.py` also imports `call_complete` and completion helpers. Extract endpoint behavior while retaining an ST adapter for `agent`; tests/coupling in `tests/cli/test_complete*.py` and `test_agent_cli.py`. |
| Root `session-events`, `exec-log`; groups `logs`, `runtime` | **mixed** — ST owns task execution/observability joins in `commands/{session_events,exec_monitor,logs,runtime}.py`; Agent Hub owns session events and systemd/services own logs/runtime. | Queries ST task/event APIs plus Agent Hub session IDs and host journals; preserve cross-system identity resolution and access policy. Root registrations: `main.py:304-311`. |
| `tools` | **mixed** — `commands/tools.py`; ST owns operator catalog/config in `scripts/lib/tool-registry.json`, Agent Hub owns usage telemetry. | Reads local registry and Agent Hub metrics/auth. Keep tool safety/registry controls in ST; move only reusable owner logic if separated. |
| `browser` group and root alias | **mixed** — `commands/browser.py`, `browser_routes.py`, `browser_targets.py`; ST owns project/VM routing and safety; browser-automation is approved owner for runner/check/automation engine. | Uses browser executable/driver and managed browser target; keep routing, grants and safety checks in ST. Root alias forwards to same group (`main.py:151-156`). |
| `web` group and root alias | **client / executable wrapper** — `commands/web.py`; Agent Hub owns `web-research` (already a project script); ST currently carries CLI/benchmark integration. | Existing `web-research` entrypoint is in Agent Hub `backend/pyproject.toml:54-56`; migrate benchmark and preserve option/output contract. Root alias forwards to group. |
| `ui`, `selection` | **mixed / executable wrapper** — `commands/ui.py`, `selection.py`; local platform operations/Aico sidecar own desktop and selection state; desktop-automation is approved destination. | UI invokes native host tools; selection talks to sidecar over loopback. Input/window changes are effects; no active-desktop verification is authorized. |
| `graph`; root `search` | **mixed** — `commands/graph.py`, `search.py`; code-intelligence owns reusable graph/search engines, while ST/Explorer owns index and project-source integration. | Uses graphify/local symbol tools and Explorer indexes. Preserve canonical indexing/storage integration; `search` is a root command, not a group (`main.py:310`). |
| `wiki` | **executable wrapper / mixed** — `commands/wiki.py`; canonical vault owns filesystem content, vault-tools is approved for engine. | Filesystem/search/lint/ingest operations against configured vault root; retain canonical data location and any ST routing/config adapter. |
| `design` | **mixed** — `commands/design.py` plus design API/storage/generation implementation; ST/project storage contracts own persisted assets, design-tools owns reusable engine. | Asset create/import/generation and AI workflows; preserve project authorization and asset/storage contracts. |
| `pulsebrief` | **executable wrapper / mixed** — `commands/pulsebrief.py`; pulse-briefing destination is to establish script/schema ownership. | Current CLI wraps script/process and JSON/schema; no destination package contract is established in this snapshot. |
| `skills` | **mixed** — `commands/skills.py`; canonical skill content belongs to Agent Hub; ST currently installs/checks harness symlinks and remains responsible for core command discovery. | Mutates symlinks/materialized files across harnesses; preserve canonical-source, adoption, and drift behavior when moving distribution tooling. |
| `jobs` | **client** — `commands/jobs.py`, `_jobs_client.py`; Jobinator owns job/evaluation/application APIs and state. | Thin HTTP client plus ST output/usage and project resolver. `_project_client.py` registry path imports private ST config/`APIError`; replace with approved public SDK/context, not a reverse import. `test_jobs_command.py` is the CLI suite to move. |
| `portfolio` | **client** — `commands/portfolio.py`, `_portfolio_client.py`; Portfolio AI owns portfolio/catalyst/retirement APIs and state. | HTTP client/resolver also reaches private ST `app.config` and `APIError`; migrate transport/config dependency with CLI. `test_portfolio_command.py` is the CLI suite to move. |
| `neri` | **client / mixed** — `commands/neri.py`; Neri owns research/evidence state; Agent Hub owns Jev/local-worker execution routes. | Project client plus Agent Hub `memory_api` calls; move domain CLI but keep explicit ST/Agent Hub adapters. `test_neri*.py` CLI suites move except `test_neri_runner_deploy.py`, which tests ST deployment/Proxmox controls. |
| `learn` | **client / mixed** — `commands/learn.py`, `learn_pty.py`; Learn-o-Tron owns learning state; local sanitized transcript spool is client state; SummitFlow owns promoted task records. | Project API, PTY/SSH and transcript handling plus private `STClient` promotion call; promotion needs public ST task interface. CLI suites: `test_learn.py`, `test_learn_predictions.py`, `test_learn_pty.py`. |
| `memory`, `models`, `prompt`, `persona`, `agents`, `feedback`; root `mandates`, `note` | **client / mixed** — Agent Hub owns model catalog, completion, memory/prompts/persona/agents/feedback data. ST implementations are `commands/{memory,memory_*,_memory_crud_helpers,models,prompt,prompt_*,persona,persona_*,agents,agents_*,preview_formatters,feedback,feedback_*,mandates,note}.py`; rank-12 Agent Hub CLI destination. | Shared `memory_api.py` currently imports private ST URL, credentials, output and HTTP-error helpers; `prompt_api`, `agents_api`, `models`, `mandates`, Neri also share it. Persona/feedback clients duplicate private URL/auth use. `note` is a memory-save alias; `mandates` is an Agent Hub fetch with SessionStart/hook-facing ST compatibility. Preserve a small ST facade for aliases. Relevant tests: `test_memory*.py`, `test_models_cli.py`, `test_prompt_cli.py`, `test_persona.py`, `test_agents_cli.py`, `test_feedback_cli.py`, `test_natural_language_authoring.py`. |
| `refactor` | **core** — `commands/refactor.py`; SummitFlow owns refactor task/plan records and task dispatch. | Uses `STClient` and task APIs; keep task creation, planning and lifecycle controls in ST. |

## Package readiness and seams at the baseline

- Agent Hub has an existing `backend/app/cli` package, `tests/cli`, and project
  scripts (`agent-hub-context`, `web-research`); destination readiness is highest
  for the rank-13 admin/client bundle. Its existing API tests remain owner tests;
  SummitFlow CLI tests move/adapt with the commands.
- Jobinator, Portfolio AI, Neri, and Learn-o-Tron have backend packages and API
  implementations but no `app/cli` or `tests/cli` package. Portfolio already
  has `portfolio-ai-mcp`; the others have no CLI script. Add owner-local CLI
  entrypoints and tests as part of extraction.
- The proposed extension contract uses executable transport and a public
  `st_sdk` facade (see `docs/st-extension-architecture.md`). Extensions must not
  import ST-private `app.config`, `cli.client`, output, credentials, command, or
  backend modules. Required public seams are: managed-project URL/context and
  JSON client; Agent Hub authenticated request; ST task promotion; and explicit
  browser/VM safety routing. Reuse existing implementations behind the facade;
  do not clone them into owner packages.
- Keep lifecycle, project resolution, VCS, quality gates, services, DB, safety,
  extension discovery, and telemetry in ST. Extract domain CLI/engines only at
  their approved destinations and retain ST compatibility aliases/adapters.

## Baseline checks and uncertainty

Read-only checks: compared static registration tables and manual registrations in
`backend/cli/main.py` with the command modules and the approved destination table
in `docs/st-extension-architecture.md`; inspected the focused owner/client
imports and package entrypoints. No tests, services, task writes, or commands
with external effects were run. Extension availability is runtime-dependent
because optional modules can become unavailable stubs. General raw-API support
in the existing `agent-hub-client` wheel and exact plug-compatibility of
Agent Hub’s progressive-context CLI with `st mandates` remain unverified.

## Implemented ownership and recommendations

The inventory above preserves baseline source locations. The executable bindings
and reviewed descriptions now live in `scripts/lib/tool-registry.json` and
`scripts/lib/extensions/`; `backend/cli/extensions.py` registers them generically.
The baseline command bodies have moved, not been duplicated.

| Capability | Current implementation owner/interface | State and remaining ST coupling |
|---|---|---|
| browser | browser-automation: `browser_automation`, `browser-st` | Browser/profile state remains local or on the managed VM. ST's `commands/browser.py` and `lib/browser_policy.py` keep routes, confirmation, session/lock and launch policy. |
| web | Agent Hub: `app.cli.web_research`, `web-research` | Agent Hub owns providers, credentials, schemas and benchmark. ST only preserves legacy details presentation. |
| ui, selection | desktop-automation: `desktop_automation`, `desktop-st-ui`, `desktop-st-selection` | Existing desktop tools/Aico sidecar and paths; no service or desktop-state migration. |
| jobs, portfolio, neri, learn | Their existing owners: `app.st_cli`, fixed owner consoles | Existing project APIs/state/auth; neutral SDK project resolution/output. Neri uses public Agent Hub helpers; Learn uses public ST manual-task promotion. |
| graph, search | code-intelligence: `code_intelligence`, `code-graph`, `code-search` | ST retains canonical Explorer DB/index scheduling and supplies host callbacks. API, workers and checkout overlays share owner analyzers/ranking/graph implementation. |
| wiki | vault-tools: `vault_tools`, `vault-st` | Existing vault paths/content unchanged. No new database or service. |
| design | design-tools: `design_tools`, `design-st` | Owner holds domain schemas, SQL, prompts, renderers and generation behavior. ST keeps authenticated routes, existing DB connections, migrations history, artifact root and provider/browser adapters. |
| Agent Hub admin/skills | Agent Hub public `agent_hub_st` package and `agent-hub-st` console | Existing Agent Hub state/instructions; lazy public-helper facades keep core callers compatible. ST task/session orchestration remains core. |
| pulsebrief | Retired with owner approval | Missing Hermes engine, no registered owner, workspace callers or schedules. Removed command and discovery; no schema or durable data changed. |

Recommended order remains the approved order: browser and web have the clearest
reusable interfaces; desktop operations are cohesive and independently useful;
the four project clients have unambiguous existing owners and low migration
risk. Intelligence and design provide substantial independent value but need
larger host seams and stronger API/worker verification. Vault tooling is small
and cohesive. Pulse was retired after confirming local orphaning. Agent Hub
administration and skills have clear ownership but broad downstream compatibility
requirements. Destination novelty does not increase or decrease these rankings.

Keep the remaining core rows in SummitFlow: extracting coordination, gates,
project resolution or safety would split authority without creating a useful
independent domain. Public owner libraries are ordinary versioned dependencies,
not Python plugins discovered or executed during CLI registration.
