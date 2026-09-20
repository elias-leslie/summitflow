# ST extension and ownership migration

Task: task-5c846bb5b1a94750. Owner-approved scope, revised 2026-09-20:
execute the full ranked migration list except unslop/SlopMiner. The initial jq
proposal and web-only stopping point are superseded.

## Protected work and core responsibilities

Do not edit, test, relocate, or publish commands/unslop.py, lib/unslop_*.py, or
their pre-existing main.py registration changes. Preserve browser and prompt/API
helper compatibility. Another agent owns that prototype. No active-desktop
operations are authorized for verification.

ST retains lifecycle, claims, project resolution, VCS, checks, services,
coordination, safety controls, extension discovery and telemetry. Owners retain
domain implementations, schemas, prompts, model choices, state and migrations.
Native package projects do not need new network services or ports.

## Destinations and complete scope

Ranking measures independent usefulness and cohesion, not destination novelty.
Dependencies determine execution order; completion of a batch does not close
the overall migration.

| Rank | Capability | Destination | Kind | Extraction scope |
|---|---|---|---|---|
| 1 | browser | browser-automation | new | Runner, checks and automation; ST retains project/VM routing and safety adapters. |
| 2 | web | agent-hub | existing | Supported web-research CLI; move benchmark and preserve option/output parity. |
| 3 | ui, selection | desktop-automation | new | Platform operations and Aico protocol bridge; no active-desktop verification. |
| 4 | jobs | jobinator-4000 | existing | Domain CLI/client and tests. |
| 5 | portfolio | portfolio-ai | existing | Domain CLI/client and tests. |
| 6 | neri | neri | existing | Domain CLI, explicit Agent Hub and ST control adapters. |
| 7 | learn | learn-o-tron | existing | CLI, PTY and transcripts; public ST task-promotion interface. |
| 8 | unslop | slopminer | existing | EXCLUDED from all implementation and verification. |
| 9 | graph/search | code-intelligence | new | Reusable intelligence with existing Explorer/index storage integration. |
| 10 | wiki | vault-tools | new | Filesystem/search/lint/ingest engine; canonical vault data preserved. |
| 11 | design | design-tools | new | CLI plus reusable generation/asset behavior; preserve project asset/storage contracts. |
| 12 | pulsebrief | Retired with owner approval | legacy | Investigation found no engine, owning project, callers or schedules; remove the broken wrapper and stale discovery instead of fabricating a replacement. |
| 13 | Agent Hub administration | agent-hub | existing | Models, complete, memory, prompt, persona, agents, feedback, note and mandates; ST agent task/session orchestration remains core. |
| 14 | skills | agent-hub | existing | Distribution and harness tooling; canonical instructions remain with Agent Hub. |

## Baseline evidence (before migration)

- cli/main.py statically loads/registers commands; optional failures get stubs.
- scripts/lib/tool-registry.json already owns operator catalog/check configuration.
- cli/lib/usage.py owns UsageSpec, filters, core/task/adaptive density and drilldown.
- cli/_project_client.py, config.py, client.py, output, details, credentials and
  browser routing contain existing reusable core adapters.
- commands/web.py embeds private Agent Hub Python. Agent Hub already publishes
  web-research in backend/pyproject.toml but lacks ST backend/benchmark parity.
- Browser command/support/check total about 1,688 lines driving agent-browser/CDP.
  browser_routes/browser_targets contain ST project mapping and safety.
- UI is about 821 lines; selection 175; wiki 387; skills 820.
- Design has a 920-line CLI plus API/storage/generation code and 2,111 lines of
  domain tests. CLI relocation alone is not proof of engine extraction.
- Graph/search use Explorer indexes, local symbol parsing and graphify_tools.
  Preserve one canonical indexing/source pipeline.
- Agent Hub memory/tool_capability_context.py invokes st tools manifest and
  runtime_context.py includes it in delivery; st_usage_memory.py counts
  invocations/help, not outcomes.

## Contract and public adapters

One executable process transport. A trusted registry binding pins identity,
owner project, entrypoint and dispatch grant. Programs resolve through the
registered owner root at execution/explicit diagnostics, never from arbitrary
PATH/cwd discovery. A Python script is an executable entrypoint under an explicit
compatible runtime, not an imported plugin. Owner code is never loaded during
registration, root help or manifest generation.

Owner metadata is copied into the trusted registry through reviewed changes.
It declares identity, owner/version, supported integer ST contract versions,
namespace, static help, usage guidance and effects. Core/hidden namespaces win;
all duplicate extension identities/names are rejected. Malformed metadata,
incompatible contracts and missing dependencies are localized.

A neutral versioned st_sdk package owns shared project/HTTP/output/details and
credential primitives moved from ST; compatibility aliases preserve core callers.
It must never import app or cli: owners share the app namespace and must be able
to import their own app first. The SDK is distributed as summitflow-st-sdk 0.1.x,
with typer/httpx/PyYAML dependencies, and installed in each owner runtime.
runtime.initialize_context validates ST_EXTENSION_CONTEXT and initializes project,
endpoint and output state BEFORE command callbacks. Runtime and SDK versions are
explicit installation prerequisites; the dispatcher never imports owner code.
Owner executables remain independently maintained and versioned.

| Concern | Contract |
|---|---|
| Identity/compatibility | Required owner, id, version, namespace and supported contract versions. Strict schema; derive/bind usage surfaces beneath the registered namespace. |
| Installation | Explicit trusted binding, static metadata and owner entrypoint; no auto-install or plugin scanning. |
| Availability | Passive metadata reports unverified runtime. Explicit diagnostics may query ST's project registry and inspect file/execute prerequisites; they do not execute the extension. |
| Authorization | ST-owned dispatch grant required independently of effect declarations. Preserve existing scope, confirmation and safety gates; owner APIs retain authorization. Metadata is not a sandbox or user consent. |
| Context | Versioned JSON with project/root, caller cwd and output preferences; no credentials/content. |
| Environment/cwd | Caller cwd by default. Explicit allowlist for necessary settings; never forward arbitrary PYTHONPATH/PYTHONHOME or credentials. Approved owner/SDK credential resolvers remain responsible for secrets. |
| Streams/exits | Inherit native streams and exit codes; preserve existing web compact/detail presentation with a thin ST adapter. |
| Cancellation | Propagate signals to the executable/process group and reap it. Test actual SIGINT/SIGTERM. No invented retries/timeouts. |
| Artifacts | Preserve established paths and formats; artifact writes are declared effects, distinct from telemetry. |
| Machine output | Preserve --json/--raw and owner envelopes. Structured registration/resolution diagnostics. |
| Help | Static root/command help only, including unavailable extensions; no owner execution or service contact. |
| Errors | Missing dependency 127; executable permission/format failure 126; invalid/incompatible registration 2. Unrelated/core commands remain usable. |
| Telemetry | Reuse invocation/help aggregation and host outcome observation. No added argv, stdin, stdout, reviewed-content or environment logs. |

No second generic API transport, Python plugin autoloading, marketplace or
orchestration framework. Existing project HTTP clients sit inside supported owner
executables. Static ST adapters remain where ST policy/workflow requires them.
Public reusable owner libraries may serve existing backend consumers without
becoming another command-registration transport.

## Review resolutions

The bounded Astra xhigh review required real extraction rather than jq; namespace-
bound usage identity; effects matching actual executable behavior; precise
availability/telemetry claims; and signal tests. Those findings are incorporated.
The bounded amendment review additionally required neutral imports, context
initialization, nested help/guidance, and explicit backend dependency direction.
Resolutions: preserve browser local-target confirmation, visibility controls,
session isolation and locks in ST control adapters before owner execution; keep
design storage/provider and intelligence index/project adapters host-supplied;
never reverse-import ST backend modules from owner libraries. CLI, API and worker
consumers must use the same extracted implementation. Static help maps cover
nested commands and metadata carries multiple namespace-bound UsageSpecs; explicit
release generation/checks compare these against the owner command inventory.

## Execution and completion

1. Finalize registry/SDK interfaces, tests and complete compact ownership inventory.
2. Register native destinations and owner-scoped tasks; delegate nonoverlapping
   owner bundles. Main owns ST integration and architectural decisions.
3. Migrate independent CLI/engine bundles in parallel, preserving old commands and
   public helper compatibility. Move relevant tests with their owner.
4. Complete browser, graph/search and design backend seams; do not count a
   forwarding demonstration or command-file relocation as full extraction.
5. Verify every migrated command, fixture and core routes, canonical gates,
   managed rebuilds and actual Agent Hub capability delivery.
6. Publish coherent owner checkpoints. Keep overall task open until every
   non-excluded row is complete; retain exact blockers/unperformed scope.

Required extension evidence: registration without main.py edits; passive
help/manifest; existing filters/densities; missing dependency; malformed metadata;
incompatible version; namespace/core collisions; denied grant; exact arguments,
context and environment; stdin/stdout/stderr and nonzero exits; cancellation;
existing core routes; actual owner execution; actual extension-specific guidance
in Agent Hub delivery with provenance. Generation, delivery and model consumption
are separate facts. Web additionally requires st web benchmark --iterations 10
--raw with all semantic/output-size checks true.
