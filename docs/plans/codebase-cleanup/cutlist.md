# Consolidation cut list and Aico package layout (2026-11-03)

Inputs: plan.md Settled section (wins), owner answers on page 1, followup research (agent-hub, summitflow, nightshift, context-cost, ominull, agents table), audits. Read-only; nothing edited, stopped or deleted. Neri: line counts only, no Neri data read.
Rule applied: decide now, rebuild lean, no grace periods. Anything not listed in a cut table is dropped (the last row of each table counts what no area claimed).

## 1. Aico package layout

Stack: TypeScript on Node 22, SQLite per machine (`node:sqlite`), Rust for the tray only, Python only for root host checks and the Proxmox sender, one Go binary `aico-hook`. Plus two exceptions the sources imply: the Kotlin phone app (kept, becomes the Aico app) and a tiny Python `st-sdk` wheel (Python tools like browser, ui, neri, portfolio still import it).

### 1.1 Packages

One repo, npm workspaces. `packages/` is TypeScript; `native/` is everything else; `contracts/` is data only (JSON schemas and replay fixtures that every language tests against).

| layer | package | purpose | may import | deploy unit |
|---|---|---|---|---|
| 0 | `shared` | ids, time, HLC, Result, status/notice/ask types. Hard cap ~1.5k LOC, no I/O. | nothing | library |
| 1 | `store` | the only code that touches `node:sqlite`: open, WAL, migrations, FTS5, online backup. One DB file per owning package. | shared | library |
| 2 | `status` | Status rows (what, kind, machine/project, state, last/next run, meaning, action): store, rollup, writer, reader | shared, store | library; rows served by `web-server` |
| 2 | `notify` | notice schema, Needs-you asks, outbox, FCM sender, tray/phone data | shared, store, status | library |
| 3 | `tether-client` | public client for the Tether socket/API (today `tether/src/client`, `files`, `term` client) | shared | library |
| 3 | `fleet` | machine link, pinned-key allowlist, row sync, placement, fenced claims, signed update | shared, store, status | library, linked into `tether` and `web-server` |
| 3 | `context` | memory (FTS5), prompts, roles, models data + `route()`, launch/deny policy, context delivery, per-item inventory and cost view | shared, store, status | library, linked into `tether` |
| 3 | `usage` | pi totals, files written, per-tool counter, usage/credit plans, spend card (session rows themselves live in `tether`) | shared, store, status | library |
| 3 | `notes` | notes, lists, capture router, vision-extract, owners (today in web/server) | shared, store, status, fleet | library |
| 3 | `webtools` | `web search/fetch/batch/refocus` + call counter | shared, status | library (CLI + web route) |
| 4 | `agent` | Aico's own harness (owner 2026-11-03): thin loop on pi-agent-core; providers from pi-ai (allowed providers only, Anthropic never registered); Pi's tools and compaction imported unchanged with our lean descriptions; role policy (models, tool level, guard, egress) that fails closed; typed refusal and model-swap outcomes; in-conversation handoff; sessions written straight to SQLite; `claude -p` tools-off provider. Pi packages exact-pinned, never forked. | shared, store, status, context, usage | library: `aico agent run --role R`, Aico chat sessions, Tether-launched headless lanes |
| 4 | `tasks` | light per-project tasks, projects registry, claims, task-to-session links | shared, store, status, tether-client | library |
| 4 | `checks` | `check`, `commit`, `done` (tree receipt), nightly `publish` | shared, status, tasks | library |
| 4 | `ops` | `service` rebuild/logs, shadow-ref + btrfs snapshots, backups engine, `vm`, DR scripts | shared, store, status, fleet | library |
| 5 | `tether` | session daemon: tmux lifecycle, one adapter per tool, asks, deliveries | layers 0-3 except notes, webtools | service `tether@.service` (+ `tether-link@`) |
| 5 | `jobs` | scheduler: fenced SQLite lease table, home machine per job kind, one Status row per job | layers 0-4 | service `aico-jobs.service` (new) |
| 5 | `web-server` | HTTP/WS API, status+notice ingest (OmniNull hub pushes here), terminal, uploads, static | layers 0-4, tether-client | service `aico-web.service` |
| 5 | `cli` | `aico` (and `st` alias) bundle | layers 0-4, tether-client | file swap `~/.local/bin/aico` |
| 6 | `web-frontend` | Next static export: Status screen, sessions, notes, memory, agents/prompts, backups, repo status | `ui-kit`, `contracts` types only | static dir served by `aico-web` (no server restart) |
| 6 | `ui-kit` | today's `shared/` UI bits: tokens.css, palette, fonts, mouse shim, terminal history | nothing | library |

Native (not TypeScript, each reads `contracts/` and imports nothing from `packages/`):
| dir | language | purpose | deploy unit |
|---|---|---|---|
| `native/hook` | Go | `aico-hook`: guard, lease, coordination, context-delivery hook; deny words and rules are data files; replays the guard corpus | binary swap `~/.local/bin/aico-hook` |
| `native/tray` | Rust | Aico tray (Nightshift tray + FIDO/seal/daemon pieces) | signed update, user unit |
| `native/android` | Kotlin | Aico phone app (reskinned Nightshift app: FCM decrypt, outage alarm, updater) | APK via updater |
| `native/host-steward` | Python (root) | host checks, runner, reboot, memctl, housekeeping, drill, grant socket; writes Status rows over loopback HTTP | root units, signed installer |
| `native/pve-sender` | Python | deadman, nightwatch, `aico-push` on the Proxmox host | `install.sh` on PVE |
| `native/st-sdk` | Python | thin wheel for Python `st` tools (~0.5k) | wheel |
| `contracts/` | JSON | status row, notice, ask, fleet frames, phone API, hook payloads, guard corpus | none |

Rules that keep it small: `shared` has no I/O and a LOC cap; layer N imports only layers below it; deployables (layer 5) never import each other (HTTP/socket only, via `tether-client`); one package owns each DB file (`tether.db`, `notes.db`, `status.db`, `context.db`, `usage.db`, `tasks.db`, `jobs.db`); any other package asks the owner's API.

### 1.2 Enforcement
- `dependency-cruiser` (`.dependency-cruiser.cjs`): layer-down-only, no deep imports (only a package's `exports`), no cycles, only `store` may import `node:sqlite`, `web-frontend` may not import `node:*` or server packages. Layer is a field in each `package.json`.
- `tsc -b` with project `references` per package: a package cannot type-import what it does not reference.
- Biome `noRestrictedImports` overrides per package (editor-time feedback only).
- `scripts/boundaries.mjs` (adopted idea): exact-pinned deps, unique DB file name per package, every native dir tests `contracts/` fixtures (drift fixtures for fleet link and phone API only).
- Python: ruff + ty + pytest; Go: `go vet` + `go test`; Rust: `cargo clippy/test`; Kotlin: `gradle test` (closes X3).

### 1.3 Checks and tests only for what changed
- `scripts/affected.mjs` (~80 lines): `git diff` files to packages, add reverse dependents from `package.json`, emit the list. No Nx/Turbo.
- `.st-check.toml` stages are generated per package (`quick = true`, `quick_paths` = package globs + its dependencies' globs): biome, `tsc -b`, `vitest --project`, depcruise. A change in `shared` fans out to all; elsewhere it stays inside the cone.
- Native stages run only when `native/<dir>/**` or `contracts/**` changes; Kotlin and live smoke scripts run nightly regardless.
- Whole repo (all packages, native, `tether-lifecycle-harness.sh`, real-session smoke) runs in the nightly deep lane only.
- Today's numbers (check receipts, 11-02/03): aico ~105 s, agent-hub ~106-113 s, summitflow ~91 s, nightshift ~100-117 s. Target: any single `st check`, even a `shared` change, at or under 105 s; typical one-package change leaf packages <= 30 s, `tether` <= 60 s, `web-frontend` <= 45 s. Not measured per package yet; M0b records baselines with `st check budget`.

### 1.4 Separate deploys
- Each unit builds and releases alone: esbuild bundle per service into `~/.local/lib/aico/<unit>/releases/<version>` plus `current` and `previous` symlinks. Frontend ships as a static dir (no `aico-web` restart). Restarting `tether` is safe: tmux owns the processes.
- `aico deploy <unit>` (alias `st service rebuild aico --scope <unit>`) picks units from the affected-package graph: a `store` change rebuilds `tether`, `jobs`, `web-server`, `cli`; a `web-frontend` change rebuilds only the static dir.
- Fleet: each machine installs the same units; switches pick UI, data copy, worker.

### 1.5 Existing aico code mapped (src LOC, tests excluded)
| today | LOC | goes to |
|---|---|---|
| `tether/src/lifecycle/**`, top-level `tether/src/*.ts` (asks, deliveries, store, cli, daemon, agent-state...), `term` viewer, `integrations/pi` | ~36k | `packages/tether` (adapters per tool under `lifecycle/tui/`) |
| `tether/src/client`, `files`, `term/index` exports | ~1.9k | `packages/tether-client` |
| `tether/src/hub` + `web/server/src/sync` + `hosts.ts` | ~5.8k | `packages/fleet` |
| notes, captures, vision-extract, owners, blobs, heic, extract-worker (`web/server/src`) | ~6.1k | `packages/notes` |
| `web/server/src` rest (api, server, terminal, uploads, static, asks, shows, sessions, pane-files, guard, broker, db) | ~6.3k | `packages/web-server` |
| `web/server/src/nightshift*.ts` (pull bridge) | ~0.5k | deleted; replaced by `notify` + status ingest |
| `tether/src/agent-hub/**`, `web/server/src/{chat,agent-hub,runs}.ts`, `shared/chat`, `AgentHubChat.tsx`, `vendor/agent-hub-*.tgz`, `tether/vendor/agent-hub-sdk` | ~4.0k | deleted (gateway and workflow runs dropped); thin ask-a-model route lands in `context` |
| `web/frontend/{app,components,lib}` | ~25.1k | `packages/web-frontend` |
| `shared/*.ts(x)`, `tokens.css` (non-chat) | ~0.3k | `packages/ui-kit`; `web/server/src/hlc.ts` to `shared` |
| `tether/scripts/aico-root-watch.py` (3.2k, split as C4 says), `aico-due.py`, `scripts/pve-push/aico-push` | ~3.3k | `native/host-steward`, `native/pve-sender` |
| `tether/scripts/*harness*.sh`, `live-smoke.sh`, `scripts/install.sh`, `scripts/systemd/*`, `tether/systemd/*` | ~0.9k | `scripts/live/` (nightly), per-unit `deploy/` dirs |
| `web/a_term/` and `web/tests/` | pycache only | delete |
| `tether/scripts/qualify-codex-admin.py`, `lifecycle/native-admin.ts` | ~0.4k | delete (C1) |

## 2. Cut lists

Legend: LOC = source lines of the listed paths (code, JSON, SQL, units; tests excluded; tests are rewritten with their area, not ported: SF 117k, AH 121k, NS 37k test lines). Paths abbreviated: `b/app/svc` = `backend/app/services`, `b/app` = `backend/app`, `b/cli` = `backend/cli`, `fe/src` = `frontend/src`, `ns` = `src/nightshift`. "+N" = N more paths of the same area, all checked to exist. Actions: drop / port (move the logic, same language or near) / rebuild (new code, original as reference). Data: migrate / fresh / archive / none.

### 2.1 Agent Hub
| area | action | source paths | LOC | target package | data |
|---|---|---|---|---|---|
| ah-20 Models: catalog and routing | rebuild | `b/app/api/models*.py`, `b/app/svc/model_catalog_service.py` +4 | 1,810 | models (data file + route()) | rebuild as a data file: only models the routing policy or a carried role names |
| ah-33 Web research: st web | rebuild | `b/app/svc/tools/_executor_web*.py`, `b/app/cli/web_research.py` +1 | 1,854 | web-tools | stateless (counter starts fresh) |
| ah-36 Image generation and voice | drop | `b/app/api/image.py`, `b/app/adapters/*_image.py` +2 | 1,620 | - | none |
| ah-01 Python app foundation, Alembic, Postgres, Hatchet worker | drop | `backend/alembic`, `backend/alembic.ini` +29 | 51,351 | - | pg_dump archive (5.3 GB) |
| ah-02 Completion gateway: API, providers, tool loop | rebuild (owner 2026-11-03) | `b/app/api/complete`, `b/app/api/endpoints` +26 | 33,446 | agent (~3-5k TS on Pi's libraries; Python providers, gateway and SSE dropped; carry as reference: `llm/utils/outcomes.py`, `refusal_codes.py`, `workflow_runs/policy.py`, level data and lean prompt in `executor_defaults.json`, `services/tools/scratch_context.py`, `providers/claude_code_cli.py` + `provider_support/claude_*`, `api_key_pool.py`); the ask-a-model route uses `agent` | archive completion sessions + request logs |
| ah-30 One-shot scripts and the Claude worker | drop | `backend/scripts/run_claude_orchestrated_worker.py`, `backend/scripts/backfill_*.py` +5 | 7,556 | - (seed JSON content kept as data) | carry seed JSON for agents/models |
| ah-03 Context delivery and memory selection | rebuild | `b/app/svc/runtime_context.py`, `b/app/svc/runtime_prompt_stack.py` +16 | 9,593 | context (+ tether adapters) | fresh (4,152 deliveries); prompts via ah-38 |
| ah-17 Memory core: store, search, st memory | rebuild | `b/app/svc/memory/_repo_*.py`, `b/app/svc/memory/repository.py` +30 | 6,612 | context (memory, FTS5) | migrate the 149 active memories (latest revision) + 1 setting; the 335 archived and all revisions go to the archive dump |
| ah-04 Memory extras: episodes, summaries, analytics, agent | drop | `b/app/svc/memory/episode_*.py`, `b/app/svc/memory/capture_*.py` +36 | 9,544 | - | archive 32,056 summary segments |
| ah-05 Session ledger and event store | rebuild | `b/app/api/sessions.py`, `b/app/api/session_*.py` +12 | 9,097 | tether (slim session store, pi totals, write paths, tool counter) | fresh + one compressed dump of session_events (4.4 GB); archive |
| ah-08 Transcript ingestion and Codex sync | rebuild | `b/app/svc/session_ingestion`, `b/app/api/session_ingestion.py` +4 | 19,458 | tether adapters (one reader per tool) | fresh |
| ah-32 Launch deny table, ownership hints, budgets | port | `b/app/svc/project_permission_service.py`, `b/app/api/project_permissions.py` +7 | 3,920 | tether (launch policy) | migrate 20 permission rows exactly; hints fresh |
| ah-24 Agents registry | rebuild | `b/app/svc/agent_service.py`, `b/app/svc/agent_crud.py` +8 | 1,202 | context (role definitions) | migrate ~15 roles (current version); archive 1,351 versions + 124 prompt links |
| ah-38 Prompt store | rebuild | `b/app/svc/prompt_service.py`, `b/app/svc/prompt_catalog.py` +2 | 1,150 | context (prompts + revisions) | migrate the 143 enabled prompts (current text) and the links for carried roles; revisions and disabled prompts go to the archive dump |
| ah-27 Usage and cost accounting | rebuild | `b/app/svc/subscription_accounting`, `b/app/svc/usage_costs.py` +9 | 4,096 | usage | migrate 8 plans, 2 credit lots, 806 daily rows; archive usage_calls (529k) |
| ah-25 Fleet credentials and remote hosts | rebuild | `b/app/api/remote_hosts.py`, `b/app/api/lab_credentials.py` +9 | 1,870 | fleet (pinned keys) + secrets folder | none (owner re-enters secrets; re-enroll 14 hosts) |
| ah-19 Access control, API keys, provider credentials | drop | `b/app/middleware`, `b/app/api/access_control*.py` +10 | 3,789 | - (3 secret files in the Aico secrets folder; one `source` label) | archive 18 clients; no keys/hashes |
| ah-26 Automations scheduler | drop | `b/app/svc/automations.py`, `b/app/svc/automation_dispatch.py` +3 | 2,034 | - (jobs package is new, tiny) | archive 11 definitions, 13 profiles, 6,398 runs |
| ah-09 Workflow runs: st workflow | drop | `b/app/svc/workflow_runs`, `b/app/api/workflow_runs.py` +3 | 8,998 | - | archive 64 runs + 146 attempt sessions |
| ah-12 Context observability and change review | rebuild | `b/app/svc/context_observability`, `b/app/svc/context_changes` +7 | 7,374 | context (cost view ~2k) | migrate 4 budgets; markers fresh; archive records/judgments/items |
| ah-06 Context and runtime-context pages | drop | `fe/src/app/context`, `fe/src/app/runtime-context` +2 | 8,954 | - (editor folds into agents/prompts page; cost grid in ah-12) | overrides (65) fresh |
| ah-07 Agent Hub CLI package: st memory, prompt, complete | port | `packages/st-cli` | 9,595 | cli (memory, prompt only; complete dropped) | none |
| ah-41 Extension manifests: agents, ctx, models | rebuild | `st-extensions/agents.json`, `st-extensions/models.json` | 267 | cli | none |
| ah-29 Agent Hub TypeScript client | port | `packages/agent-hub-sdk` | 2,615 | tether (in-process; no client) | none |
| ah-23 Agent Hub Python client | drop | `packages/agent-hub-client` | 14,131 | - (3 call groups ported: session list/close, ownership, catalog) | none |
| ah-13 chat-ui | drop | `packages/chat-ui` | 6,911 | - (message renderer subset only if transcript view needs it) | none |
| ah-40 passport-client and pack-smoke | drop | `packages/passport-client`, `packages/pack-smoke.mjs` | 1,281 | - | none |
| ah-34 Notes popout and notes-ui | drop | `fe/src/app/notes`, `packages/notes-ui` | 1,988 | - (notes live in Aico) | none |
| ah-14 Agents and prompts editors | rebuild | `fe/src/app/agents`, `fe/src/app/prompts` | 6,218 | web-frontend (agents+prompts page) | via ah-24/ah-38 |
| ah-15 Sessions viewer | rebuild | `fe/src/app/sessions`, `fe/src/hooks/use-session-events.ts` | 5,652 | web-frontend (recent sessions + transcript) | archive old events |
| ah-18 Memory page | rebuild | `fe/src/app/memory`, `fe/src/components/memory` +2 | 5,655 | web-frontend (memory page) | via ah-17 |
| ah-21 Access-control pages | drop | `fe/src/app/access-control` | 3,507 | - | none |
| ah-22 Models and automations pages | drop | `fe/src/app/models`, `fe/src/app/automations` +2 | 3,380 | - | none |
| ah-16 Token share, request monitoring, workflow-runs pages | drop | `fe/src/app/token-share`, `fe/src/app/monitoring` +1 | 5,152 | - | request logs fresh; archive 151 workflow steps |
| ah-35 Chat page | drop | `fe/src/app/chat`, `fe/src/components/chat` | 1,854 | - | archive 162 chat sessions |
| ah-37 Costs page | rebuild | `fe/src/app/costs` | 1,728 | status (spend card) | plans become a config file |
| ah-39 Dashboard | rebuild | `fe/src/app/dashboard`, `fe/src/components/dashboard` +1 | 1,396 | status (home card) | none |
| ah-31 Provider logins and settings modal | rebuild | `fe/src/components/settings`, `fe/src/components/settings-modal.tsx` | 2,443 | web-frontend (logins card) | none |
| ah-11 Dashboards, analytics, health, small endpoints | drop | `b/app/api/dashboard_stats.py`, `b/app/api/admin*.py` +16 | 3,608 | - | archive 2,388 narration tags |
| ah-10 Shared API layer and types | rebuild | `fe/src/lib`, `fe/src/hooks` +1 | 6,570 | web-frontend (~1k fetchers) | none |
| ah-28 App shell, proxy, service worker, scripts | drop | `fe/src/components/layout`, `fe/src/components/providers.tsx` +7 | 1,913 | - | none |
| -- Residual constants, small pages and api glue not listed above | drop |  | 1,497 | - | none |

Totals: dropped 172,514; carried 110,175 (port 16,130, rebuild 94,045); total 282,689.

### 2.2 SummitFlow
| area | action | source paths | LOC | target package | data |
|---|---|---|---|---|---|
| sf-01 Tasks: store, create/claim/log/plan/subtasks | rebuild | `b/cli/commands/tasks.py`, `b/cli/commands/tasks_[bcehilvx]*.py` +17 | 14,370 | tasks | by hand: ~13 live tasks; archive dump of the rest |
| sf-27 Low-use task commands (critique, ready-all, exec-log, progress) | drop | `b/cli/commands/tasks_critique.py`, `b/cli/commands/tasks_ready_all.py` +2 | 1,062 | - | archive |
| sf-12 Done, abandon, acceptance proof | rebuild | `b/cli/commands/done*.py`, `b/cli/commands/abandon.py` +6 | 4,800 | tasks | fresh |
| sf-04 Tasks screens (board, table, modal, kanban) | drop | `frontend/components/tasks`, `frontend/components/kanban` +1 | 10,580 | - | none |
| sf-02 Host monitor, Runtime diagnostics, VM/GPU cards | drop | `host-monitor/src`, `backend/monitor_control` +13 | 17,699 | (tiny st monitor rebuilt in cli) | archive monitor.sqlite3 |
| sf-03 Backups: engine, CLI, Backups screen | rebuild | `b/app/tasks/backup_*.py`, `b/app/tasks/backup_offsite.excludes` +10 | 9,783 | backups | migrate config (65 sources, 2 backends, 2 external) |
| sf-40 Backup key setup and snapshot browsing screens | drop | `frontend/components/snapshots`, `frontend/components/backup/EncryptionSetup.tsx` | 818 | - | none |
| sf-05 Cleanup, retention, runtime hygiene | drop | `b/cli/commands/cleanup*.py`, `b/app/tasks/runtime_hygiene*.py` +7 | 6,682 | - | fresh |
| sf-06 Postgres schema and Alembic | drop | `backend/alembic`, `backend/alembic.ini` +4 | 8,938 | - | pg_dump archive; export kept tables once |
| sf-07 Quality gate: st check | rebuild | `b/cli/commands/check*.py`, `b/cli/lib/ci_parity.py` +10 | 6,879 | checks | fresh (clean 14 GB receipts) |
| sf-08 Session handshakes: st sessions | rebuild | `b/cli/commands/sessions.py`, `b/cli/commands/sessions_[dfhmnos]*.py` +6 | 3,999 | tether (sessions, messages) | fresh |
| sf-23 Niche session verbs, coordinators | drop | `b/cli/commands/sessions_reap.py`, `b/cli/commands/sessions_title.py` +4 | 3,829 | - | none |
| sf-09 Mockups and design store | rebuild | `b/app/api/mockups*.py`, `b/app/svc/mockup_generator` +4 | 5,834 | dev (st mockup) | archive 421 MB + tables; optionally last 9 mockups by hand |
| sf-10 Git and files browser | drop | `b/app/api/git.py`, `b/app/api/git_helpers` +7 | 6,343 | - | none |
| sf-25 Repo status screen | rebuild | `frontend/app/(app)/git`, `frontend/hooks/useGitHealth.ts` +1 | 389 | status (repo rows) | none |
| sf-11 Notes (SummitFlow copy) | drop | `b/app/api/notes*.py`, `b/app/storage/notes*.py` +2 | 3,465 | - | archive 56 versions + 6 proposals |
| sf-13 Service control: st service, st logs | rebuild | `b/cli/commands/service.py`, `b/cli/commands/setup.py` +8 | 5,727 | deploy | fresh |
| sf-14 Local snapshots and checkpoints | rebuild | `b/cli/commands/snapshots.py`, `b/cli/commands/autosnapshot.py` +9 | 4,239 | backups (snapshot backend) | none (btrfs on disk) |
| sf-15 Docker API, st docker, self-hosting kit | drop | `b/app/api/docker`, `b/cli/commands/docker.py` +1 | 2,245 | - | none |
| sf-16 App shell, auth gate, UI kit, service worker | drop | `frontend/components/layout`, `frontend/components/auth` +6 | 3,991 | - | none |
| sf-17 Agent Hub proxy and activity feeds | drop | `b/app/api/agent_hub.py`, `b/app/api/fleet_sessions.py` +12 | 3,077 | - | fresh |
| sf-18 Projects registry and project index | rebuild | `b/cli/commands/projects.py`, `b/cli/commands/_projects*.py` +8 | 4,318 | tasks (projects table) | migrate 36 projects minus retired ones, lifecycle events, agent configs |
| sf-30 Project pages: overview, settings, new project | drop | `frontend/app/(app)/projects`, `frontend/components/projects` | 2,948 | - | none |
| sf-19 Publication to GitHub and guards | port | `b/cli/commands/vcs.py`, `b/app/tasks/nightly_publication.py` +8 | 2,432 | dev (publish job) | none |
| sf-20 Tools: manifest, run, extensions, reports | rebuild | `b/cli/commands/tools*.py`, `b/cli/lib/usage.py` +2 | 3,259 | cli | none |
| sf-43 Extension dispatcher | port | `b/cli/extensions.py`, `b/cli/extension_contract.py` +2 | 3,321 | cli | none |
| sf-21 CLI plumbing: client, output, config | rebuild | `b/cli/_client*.py`, `b/cli/_formatters*.py` +18 | 3,431 | cli | none |
| sf-32 st commit | port | `b/cli/lib/commit_workflow.py` | 595 | dev (commit) | none |
| sf-28 Command guard hook | port | `b/app/svc/command_guard.py`, `b/app/svc/_command_guard_helpers.py` +4 | 2,022 | hook (Go aico-hook) | none (deny words become a data file) |
| sf-33 Claims, leases, lease hook | rebuild | `b/cli/commands/lease.py`, `b/cli/lib/leases.py` +3 | 1,140 | hook + tether coordination | fresh |
| sf-42 Live coordination view: st pulse | rebuild | `b/cli/commands/pulse*.py`, `b/app/svc/project_pulse.py` | 1,105 | status (view) + cli | none |
| sf-26 VMs and Proxmox: st vm | rebuild | `b/cli/commands/vm.py`, `b/cli/lib/proxmox*.py` +3 | 2,056 | fleet (hosts, VMs) | none |
| sf-36 Runtime screen: services | rebuild | `frontend/app/(app)/runtime`, `b/app/api/system.py` +1 | 535 | status (service rows) | none |
| sf-44 Read-only database access: st db | rebuild | `b/cli/commands/db.py` | 660 | cli | none |
| sf-35 Database workbench | drop | `b/app/api/db_workbench.py`, `b/app/svc/db_workbench*.py` +1 | 1,452 | - | none |
| sf-34 Python SDK: st-sdk | port | `packages/st-sdk`, `docker/workspace-packages` | 1,699 | sdk (see choices) | none |
| sf-45 Nightly security alert and deep lane | port | `b/app/tasks/nightly_security_alert.py`, `b/app/tasks/nightly_deep_lane.py` | 502 | jobs | none |
| sf-24 Hatchet workflows, Redis, automation dispatch | drop | `b/app/worker.py`, `b/app/hatchet_app.py` +8 | 1,993 | - | fresh |
| sf-37 Code graph: refresh job, Graph page | drop | `b/app/api/graphify.py`, `b/app/tasks/graphify_tasks.py` +3 | 293 | - | none (308 MB cache regenerable) |
| sf-38 Notifications bell | drop | `b/app/api/notifications.py`, `b/app/svc/notifications` +2 | 1,579 | - | fresh |
| sf-39 Dashboard | drop | `frontend/app/(app)/DashboardClient.tsx`, `frontend/components/dashboard` +1 | 1,152 | - | none |
| sf-41 st claude and st agent | drop | `b/cli/commands/claude.py`, `b/cli/commands/_claude_*.py` +1 | 1,039 | - | none |
| sf-29 Misc scripts and root helpers | port | `scripts/summitflow-steward-receipt`, `scripts/ci-runner` +6 | 659 | with parent areas (hook, backups, cli) | none |
| sf-31 Disaster-recovery scripts | port | `scripts/recovery-bootstrap.py`, `scripts/infra-restore-drill.sh` +4 | 1,400 | backups (plain scripts) | none |
| sf-22 Dead modules, unused scripts, experiments | drop | `b/app/utils/smb_commands.py`, `scripts/backup-cleanup-inventory.py` +4 | 925 | - | none |
| -- Residual FastAPI/Next glue not listed above (backend/app/utils, schemas, core, main.py; frontend/lib/api) | drop |  | 15,853 | - | none |

Totals: dropped 95,963; carried 85,154 (port 12,630, rebuild 72,524); total 181,117.

### 2.3 Nightshift
| area | action | source paths | LOC | target package | data |
|---|---|---|---|---|---|
| ns-01 Host checks: workstation, storage, perf, PVE, backups, ECC, thermal, journal, routing, gates | port | `ns/checks/workstation.py`, `ns/checks/storage.py` +23 | 7,969 | host-steward (Python, root) | fresh (findings, 912 daily rows, 1,700 events, 17,472 usage rows) |
| ns-12 Tripwire, sudo, security, attribution | port | `ns/checks/tripwire.py`, `ns/checks/sudo.py` +3 | 2,363 | host-steward | migrate tripwire + sudo baselines (small) |
| ns-14 Runner: rules and escalation | port | `ns/runner/run.py`, `ns/runner/escalation.py` +10 | 2,343 | host-steward | fresh decisions |
| ns-15 Reboot coordination, post-boot verify | port | `ns/executor/catalog_reboot.py`, `ns/postboot.py` +3 | 1,422 | host-steward | none |
| ns-16 Memory controller and alerts | port | `ns/memctl.py`, `ns/memalerts.py` +2 | 1,794 | host-steward | fresh (11 KB events) |
| ns-23 Assets, tiers, site config | port | `ns/assets.py`, `ns/siteconf.py` +1 | 1,471 | host-steward | migrate assets.json |
| ns-27 Telemetry and usage collector | port | `ns/telemetry.py`, `ns/usage.py` +1 | 703 | host-steward | fresh |
| ns-28 Housekeeping, space guard, scrub, NVMe timers | port | `ns/housekeeping.py`, `deploy/system` +1 | 2,351 | host-steward | none |
| ns-34 Lab use and declarations | port | `ns/labuse.py` | 463 | host-steward | fresh declare state |
| ns-35 Explain: plain text per finding | port | `ns/explain.py` | 458 | host-steward + status (code->text table) | none |
| ns-36 Floor push | port | `ns/floorpush.py` | 423 | host-steward | none |
| ns-33 Drill: purple-team simulations | port | `ns/drill.py` | 549 | host-steward (on-demand command) | none |
| ns-29 Canary tokens and honeypot hooks | rebuild | `ns/canary.py` | 675 | web-server (hook receiver) | migrate registry (6 KB); archive 32 events |
| ns-03c OmniNull file-based lock check | port | `ns/checks/ominull_lock.py` | 74 | host-steward | none |
| ns-24 Router drift check | port | `ns/checks/router.py`, `deploy/router` | 658 | host-steward (router drift check stays) | none |
| ns-24b Lab-net flow check | drop | `ns/checks/labnet.py` | 365 | - (drop unless the owner keeps it) | none |
| ns-42 Proxmox-side watchdog: deadman, nightwatch, aico-push | port | `ns/deadman.py`, `ns/nightwatch.py` +1 | 1,159 | pve-sender (Python, on PVE) | none |
| ns-25 Elevate, bypass, agent requests | port | `ns/elevate.py`, `ns/bypass.py` +2 | 564 | grants (thin: Aico CLI + root grant socket) | none |
| ns-13 Approvals: intake, store, passkeys, web passkey page | rebuild | `ns/executor/approval_*.py`, `ns/executor/approvals.py` +3 | 2,117 | grants + tray FIDO (web passkey page dropped) | archive 21 requests; migrate passkey enrollment |
| ns-05 Executor: root-run typed actions | drop | `ns/executor/core.py`, `ns/executor/catalog.py` +16 | 4,232 | - (two replacements: sudo btrfs; one sudoers line) | archive 2,047 receipts |
| ns-31 Ledger: hash chain | drop | `ns/ledger.py` | 643 | - (elevate use-log shown on Grants view) | archive chain.jsonl (2.8 MB) read-only |
| ns-03a OmniNull: release signer + host-grant/auto key | move | `ns/signer.py`, `ns/executor/signing.py` +1 | 1,459 | - (signer moves to the OmniNull repo; host-grant and auto key dropped) | keys stay where they are (owner-only) |
| ns-03b OmniNull: ingest, data map, feed v1-3, evidence replica, couriers, relay, builds, alerts | drop | `ns/ingest.py`, `ns/datamap.py` +6 | 3,098 | - (hub pushes notices and Status rows into Aico; retired-build row moves to OmniNull) | delete data/ominull.json; archive evidence index |
| ns-08 Item store: things that need the owner | rebuild | `ns/items/store.py`, `ns/items/facts.py` +10 | 2,913 | status + asks (Needs you) | fresh (431 items); migrate 1 open item + 20 docs by hand |
| ns-30 Outbox: the one deliverer | rebuild | `ns/items/outbox.py`, `deploy/runner/nightshift-outbox.service` | 659 | notify (TS) | fresh |
| ns-26 Notice contract and log | rebuild | `ns/notify/contract.py`, `ns/notify/log.py` +3 | 833 | contracts (notice schema) + notify | fresh (299 pushes) |
| ns-20 FCM push sender and token mint | rebuild | `ns/notify/fcm.py`, `ns/fcmauth.py` +2 | 1,165 | notify (TS sender); token mint stays small Python in host-steward | migrate 1 device (re-pair) |
| ns-17 Web Push: send, receive, subscriptions | drop | `ns/notify/push.py`, `ns/web/static.py` +1 | 2,009 | - | delete empty subscriptions; owner keeps VAPID key |
| ns-22 Look-into hand-off | rebuild | `ns/lookinto.py`, `ns/actions.py` | 975 | tether (session-start button) | fresh |
| ns-11 Notice pages and item actions | rebuild | `ns/web/notices.py`, `ns/web/itemact.py` +6 | 3,390 | web-server (notice page + act endpoint) | none |
| ns-39 Inbox data for the tray | rebuild | `ns/web/inbox.py`, `ns/trayinfo.py` | 436 | web-server (tray data endpoint) | none |
| ns-18 Core CLI | rebuild | `ns/cli.py`, `ns/installs.py` | 1,538 | cli (`aico host ...`, ~12 commands) | none |
| ns-02 Root installers and deploy units | rebuild | `ns/rootinstall.py`, `ns/root_installs.py` +1 | 476 | host-steward + scripts/install (signed-update installer) | none |
| ns-10 Status board, PWA page, digest, trends | drop | `ns/web/board.py`, `ns/web/page.py` +4 | 2,744 | - | archive history.sqlite3 |
| ns-19 Import, shadow, diff scaffolding | drop | `ns/items/importer.py`, `ns/items/shadow.py` +1 | 1,263 | - | delete diffs table |
| ns-21 Decision layer (decide/) | drop | `ns/decide` | 1,117 | - | archive decide.sqlite3 (8.4 MB), then delete |
| ns-32 Daily pass and work classes | drop | `ns/dailypass.py`, `ns/workclass.py` +1 | 681 | - | fresh |
| ns-37 Stack: SummitFlow Postgres and Redis compose | drop | `ns/stack.py`, `deploy/stack` | 557 | - | none |
| ns-40 Tether asks bridge | drop | `ns/tetherasks.py` | 301 | - | none |
| ns-41 LLM planner and reviewer plumbing | drop | `ns/runner/coord.py`, `deploy/st` | 681 | - | delete planner response files |
| ns-09 Docs, ADRs, OSS export, showcase | drop | `docs/adr`, `docs/showcase` +12 | 507 | - | ADRs stay in git history |
| ns-04 Desktop tray: panel, notices, items, toasts | port | `desktop/src/panel.rs`, `desktop/src/notice.rs` +9 | 4,532 | tray (Rust) | none |
| ns-07 Approve popup, FIDO, seal, daemon | port | `desktop/src/fido.rs`, `desktop/src/seal.rs` +9 | 2,886 | tray (Rust) | keep passkey/credential material |
| ns-06 Phone app (Kotlin) | port | `android/app/src` | 3,628 | android (Kotlin; becomes the Aico phone app) | re-pair the one device |
| ns-38 GNOME shell extension | drop | `desktop/shell-extension` | 417 | - (after the desktop-bridge work covers it) | none |
| -- Residual (biome.json, package init) | drop |  | 28 | - | none |

Totals: dropped 18,643; carried 50,987 (port 35,810, rebuild 15,177); moved to the OmniNull repo 1,459; total 71,089.

## 3. Data plan

Method key: script = rerunnable export (SQL/psql to JSONL) plus a TS import with a row-count and hash check; hand = typed in by the owner or an agent from a short list. Secrets are never copied: the owner re-enters them (one ask when the milestone starts).

### 3.1 Carried
| data set | source | target | method |
|---|---|---|---|
| 149 active memories (latest revision), 1 setting | agent-hub PG `memories`, `memory_settings` | `context.db` memories + FTS5 | script (M6) |
| 143 enabled prompts (current text), links for carried roles | PG `prompts`, `agent_prompts` | `context.db` prompts | script (M6) |
| ~15 role definitions (current version) | PG `agents` (list in `followup/agents_table.md`, `agents.tsv`), seed JSON `b/scripts/seed_agents_data` | `context.db` roles + launch-policy rows | hand: curated list, others dropped |
| models the routing policy or a carried role names | PG `models`, `model_aliases`, `b/app/routing/model_selection_policy.json` | `models` data file in `context` | hand-curated data file; enrichments re-derived |
| 20 project permission rows (launch deny table) | PG `project_permissions` | tether launch policy | script, copied verbatim, hash-compared; Neri rows stay exactly as they are, never opened |
| 4 context budgets | PG `context_budgets` | `context.db` | hand |
| 8 plans, 2 credit lots (current) | PG `subscription_plans`, `credit_lots` | `usage` config file | hand (M8); daily usage history starts fresh, old rows in the archive dump |
| 36 projects minus the 14 retired (6 on 11-03, 8 earlier), 17 lifecycle events, 8 retirement decisions, agent configs | SF PG `projects`, `agent_configs` | `tasks.db` | script + keep-list file |
| ~13 live tasks | SF PG `tasks` | `tasks.db` | hand (rest closed, dumped) |
| backup config: 65 sources, 2 storage backends, 2 external sources | SF PG `backup_sources`, backend tables (`b/app/storage/backups/`) | `ops` config file in the repo | script; key material stays where it is |
| last 9 mockups (optional) | `data/design-studio` | `st mockup add` HTML files | hand, optional |
| tripwire + sudo baselines, `assets.json`, `deploy/system/site.json` | `/var/lib/nightshift/*`, repo | `host-steward` state | copy by hand |
| canary registry (6 KB) | nightshift canary state | `web-server` hook receiver data | script |
| passkey enrollment | nightshift approvals files | tray FIDO store | hand, root-only copy |
| 1 open item + 20 docs | `items.sqlite3` | Aico asks / notes | hand |
| phone device | FCM token | re-pair | hand (owner) |
| 36 SummitFlow notes | already imported (59 notes in Aico) | `notes.db` | done |
| secrets: OpenCode Go key, host tool logins (`_host_tool_*`), 12 `_lab_*` logins | PG `credentials` | Aico secrets folder, 0600 files per machine | owner re-enters; not migrated. VAPID key stays with the owner |

### 3.2 One archive dump each (read-only, owner decides when to delete; location proposed: `/srv/workspaces/archive/pre-aico/`, confirm it is in a backed-up set)
| archive | contents | method |
|---|---|---|
| agent-hub `pg_dump` (5.3 GB) | everything not carried; `session_events` as its own compressed dump (3.0M rows, 4.4 GB). The 7-day transcript deletion (`local_history_retention_days = 7`) stops until the dump is verified | script |
| agent-hub file dump | agents + agent_versions (1,351) as JSON; 10-22 and 10-27 evaluation READMEs; 3 workflow example JSONs | script |
| summitflow `pg_dump` | tasks, 17,331 log rows, 15,186 deletion snapshots, notes versions (56) + proposals (6), notifications (1,680), maintenance runs (5,727), old `backups` table (3,019), automation receipts | script |
| `monitor.sqlite3` (283 MB), design-studio (421 MB + mockup tables) | as-is | copy |
| nightshift ledger | `chain.jsonl` (2.8 MB) + PVE anchor, read-only | copy |
| nightshift stores | `history.sqlite3`, `decide.sqlite3` (8.4 MB), `items.sqlite3` (431 items, 640 events), 2,047 exec receipts, 21 approval requests, 32 canary events | copy |
| ominull evidence replica | stays on disk as is; CT 150 gets a normal backup | none |
Not archived (regenerable): 14 GB `.git/st` receipts, 308 MB graph cache, 6.0 GB isolated observations, 8.7 GB old release builds.

## 4. Build order

One agent per milestone, from a brief of <= 60 lines. Sizing rule: <= ~8k new lines and <= ~25k lines of reference reading. S = small, M = medium, L = large (several agent-hours). "Stop" = the old service becomes stoppable once the milestone is verified live; stopping and deleting are separate steps, not here.

| # | milestone | scope | needs | size | old service stoppable after |
|---|---|---|---|---|---|
| M0a | Restructure | move this plan and cut list into `aico/docs/plans/`; move to `packages/` + `native/`, `tsc -b` references, vitest projects, delete dead aico code (C1, a_term, pycache), no behavior change | - | M | - |
| M0b | Boundaries and fast checks | dependency-cruiser, `boundaries.mjs`, `affected.mjs`, generated `st-check` stages, per-package baselines, nightly deep lane | M0a | S | - |
| M1 | Status rows (early, others report into it) | `contracts/status-row.schema.json`, `status` package, loopback HTTP write API, `aico status` / `st status`, Python and Go writer helpers, late and unknown rules | M0b | M | - |
| M2 | Status screen | mockup review with owner first, then screen + tray badge + phone read the same rows; project page = filtered list | M1 | M | SF dashboard, notifications bell, Alerts-history pages (sf-39, sf-38) once M3 and M4 also feed it |
| M3 | Jobs and notify | `jobs` (fenced leases, home machine per kind), `notify` (notice schema, Needs-you, outbox, FCM sender), OmniNull push endpoint (notice + Status rows) | M1 | M | Nightshift web board/PWA, digest, Web Push, notify-critical, web unit (ns-10, ns-17, ns-11, ns-30, ns-26) after M4 |
| M4 | Tray and phone | Rust tray + Kotlin app repointed to Aico API; unread rule (ended alerts leave the tray) | M2, M3 | M | Nightshift desktop pieces and app backend |
| M5a | host-steward checks | port host checks, tripwire, sudo, router drift, file lock check, memctl, housekeeping, assets, explain, floor push, usage collector; rows over loopback HTTP; replace the two executor callers (`sudo btrfs` list, one sudoers line) | M1 | L (split in two if needed) | Nightshift check/collect timers |
| M5b | host-steward root side + PVE | runner and rules, thin grants (CLI + tray tap + use-log on Grants view), signed installer, drill on demand, canary hook, `pve-sender` (deadman, nightwatch, `aico-push`) | M5a, M3 | M | the whole Nightshift install (executor, approvals, ledger, runner, deadman). OmniNull-repo work (signer, hub push, retired-build row) must land first: outside this file |
| M6 | context core | `context`: memory FTS5, prompts, roles, models data + `route()`, deny table; migration scripts; `aico memory/prompt/models` CLI; agents/prompts/memory pages | M0b | M | - |
| M6b | agent slice (gate) | `agent` with Codex, Pi's read/bash/edit/write under our lean descriptions, role policy, typed outcomes with refusal handoff, SQLite transcript, `aico agent run`. Pass: on the 16-check task (`agent-hub/docs/evaluations/multi-model-workflow-20261027/`) and one longer real task, tokens at or below Pi with the same context, same checks passed, an injected refusal hands off with context kept, a blocked model is refused when the role rules can't be read. Fail: Pi's terminal app plus extensions becomes the main harness | M6 | M | - |
| M7 | Go hook + delivery | `aico-hook` (guard corpus replayed, lease, coordination, context delivery), tether adapters per tool with conformance suite, in-process delivery, byte budget | M6 | L | Agent Hub context-delivery and memory endpoints; SF guard/lease hooks |
| M8 | sessions, usage and transcripts | slim session store, per-tool transcript readers, pi totals, files written, tool counter, usage/credit plans, spend card, session-events dump | M7, M1 | M | Agent Hub sessions, ingestion, accounting |
| M8b | agent full | resume and branching on SQLite, Pi compaction wired in, Aico chat sessions (web and phone) on `agent`, headless role lanes under Tether, hunting role (no Claude, egress profile), turn-level fallback chains from `route()` | M6b, M8 | M | Agent Hub harness paths and Aico's unfinished Agent Hub chat (`web/server/src/agent-hub.ts`, `chat.ts`, `AgentHubChat.tsx`) |
| M9 | web, ask-a-model, context cost | `webtools` + counter, ask-a-model route on `agent` (agy/Codex/Claude headless, schema in), context cost view (~2k) with loaded-but-unused flag; VM 180 apps move to an Aico service token (their repos) | M6, M8 | M | Agent Hub gateway, workers, UI. Needs M11 (fleet logins) |
| M10a | tasks and coordination | `tasks`, projects registry, claims, sessions handshakes, pulse view, many-to-many task-session links | M7, M1 | M | SF tasks API/UI, sessions, leases |
| M10b | checks and commit | `checks` (check, commit, done with tree receipt, nightly publish); delete the 3 Actions workflows | M10a | L | SF `st check/commit/done/vcs` paths |
| M10c | ops | `service` rebuild/logs, shadow-ref + btrfs snapshots, backups engine and screen (freshness by data age), `vm`, DR scripts; restore drill before cutover | M5a, M10a | L | SF backup engine, worker, host-monitor (also `st monitor` on /proc in cli) |
| M10d | CLI shell and leftovers | `cli` plumbing, tools manifest/extensions, `db`, `mockup add`, `st-sdk` wheel, `st` alias cutover | M10a-c | M | SF backend, frontend, worker; with Postgres/Redis/Hatchet once no other project uses them (check the Neri backend first) |
| M11 | fleet link and secrets | pinned-key allowlist, fleet link, secrets folder, tool logins over the link, re-enroll 14 hosts, signed updates | M0b | L | Agent Hub remote-hosts and credential API (needed before M9 stop) |
| M12 | final | one-time archive dumps verified, pending re-entries done, leftover aico dead code removed | all | S | the shared Postgres, Redis, Hatchet |

Order for parallel agents: M0a, M0b, then {M1, M6, M11} in parallel; M2/M3/M5a follow M1; M7 follows M6.

### 4.1 Models and effort per piece

From `st models route --role R` (policy v5, read 2026-11-03); re-check it when starting each milestone, since usage and routes change. Builders, reviewers and testers run as native Claude Code subagents of the coordinating session (Agent tool with `model`); an Aico lane (`st aico create`) only for another harness, for example Codex.

| who | model, effort | used for |
|---|---|---|
| Coordinator (one fresh session per run of milestones) | Opus 5.5, xhigh | briefs, deciding, checking every result live, commits of plan changes; delegates the building |
| Builder, default | Sonnet 5.5, high (subagent `model: sonnet`) | mechanical or well-specified work: M0a, M0b, M4, M5a, M8, M9, M10a, M10d, M12, migration scripts. A Sonnet builder that is stuck, or finds the work needs a design call, stops and reports; the coordinator reruns that part on Opus |
| Builder, Opus | Opus 5.5, high | design, contracts others build on, hard debugging, security, root or deleting code: M1 (Status contract everything reports into), M3 (jobs and owner alerts), M6 (memory, prompts, routing, deny table), M2 (screen design, after the owner reviews the mockup), M5b (root side, PVE sender), M6b and M8b (agent harness), M7 (Go hook and guard corpus), M10b (check/commit/done), M10c (ops: backups, snapshots, restore drill), M11 (fleet link and secrets) |
| Reviewer | `code-reviewer` subagent (Opus, read-only) | one required review per milestone before its verified commit; no optional repeat reviews |
| Tester | `user-tester` subagent (Haiku 5.5, high); Sonnet only if Haiku can't, Opus only when truly needed (say why) | user journeys with only what a real user has: Status screen, tray, phone, notes, `aico` CLI help; the coordinator checks each finding live before anything is fixed |
| Search and fact gathering | `Explore` subagent, or Sonnet 5.5 high | broad sweeps and inventories that need only the conclusion |
| Other harness | Codex gpt-6.1-sol, xhigh (Aico lane) | a builder when Claude's weekly usage is low (16% left on 2026-11-03, resets 11-06; Codex weekly resets 11-04 05:28, 12.6K credits left); the M6b slice is also measured against Pi on gpt-6.1-sol |

Result rule (owner 2026-11-03): the cheaper model is used only where it gives the same result; when in doubt, use the stronger one. Every milestone ends with the coordinator checking it against the vision before it counts as done: it matches the decisions log and settled choices; it stays lean (no added ceremony, gates or unused layers; LOC near the cut list's estimate); dev speed doesn't get worse (`st check budget`, commit time); owner-facing screens and copy follow the product UI rules, with mockups reviewed by the owner first; and live behavior is checked, not just tests. The reviewer gets the milestone's goal and the relevant plan sections, not the builder's summary.

Usage rule: keep coordinator turns short and put file reading and building in subagents. One builder per milestone (split an L milestone into two briefs up front), ended once verified.

## 5. Choices the sources did not settle
- Package set, names and the `packages/` + `native/` + `contracts/` split; dependency-cruiser as the gate; one SQLite file per owning package; Status writers outside TypeScript post to loopback HTTP.
- `chat-ui` (ah-13): dropped, although page 1 said agree. The gateway and chat page are gone, so nothing feeds it; only a message-renderer subset is kept if the transcript view needs it.
- Python `st-sdk` kept as a ~0.5k wheel (neri, browser, ui, portfolio, wiki import it): the only Python besides root checks and the PVE sender. The Kotlin app is also outside the stack list.
- Router drift check stays (ns-24); the lab-net flow check is "drop unless the owner keeps it".
- Archive location `/srv/workspaces/archive/pre-aico/` and 14-project keep-list rule for the registry.
- Postgres, Redis and Hatchet stop only after confirming no other project (e.g. Neri backend) still uses them.
- LOC counts include JSON/SQL/unit files (e.g. AH codex protocol JSON copies), first-claim-wins when areas overlap. New-code guess: SF ~35k, AH ~30k, NS ~42k lines.
