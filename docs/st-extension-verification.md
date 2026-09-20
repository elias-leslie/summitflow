# Ownership migration evidence

Parent task: task-5c846bb5b1a94750. Work remains open until every approved
non-unslop migration is complete. This records observed checkpoints, not a claim
that the full migration is finished.

## First integration checkpoint (2026-09-20)

- Neutral SDK: 134 focused compatibility tests passed; lint/types passed.
- Executable registry fixture: 12 tests passed, including actual SIGINT/SIGTERM
  propagation/reaping, exact argv/context/env, denied dispatch, incompatible and
  malformed metadata, collisions, missing/non-executable dependencies and exit 7.
- Integrated core/manifest/operator tests: 183 passed, 32 browser cases excluded
  while their separate owner slice is in progress. Scoped lint/types passed.
- `st web benchmark --iterations 10 --raw`: exit 0, `passed=true`, all 21 cases
  and every semantic/output-size check true through Agent Hub's public executable.
  No private Agent Hub Python imports remain in ST's web implementation.
- `st jobs ready --limit 1`: exit 0, existing schema_version=1 envelope, empty
  actionable queue and unevaluated_new=36. Owner gate: 541 passed, 16 skipped.
- `st portfolio market-status`: exit 0, existing envelope; closed, last trading
  day 2026-09-18. Owner gate: 2865 passed, 433 skipped.
- Desktop owner: 39 synthetic tests passed; no active-desktop operations used.
- Vault owner: 9 temporary-directory tests passed; no user vault writes used.
- Static release descriptions retained nested help and UsageSpecs: jobs 16/15,
  portfolio 23/8, UI 16/1, selection 4/2, wiki 6/5 (help paths/specs).

## Actual capability delivery

The HTTP delivery probe using the ordinary memory-client credentials returned
403. No permissions or access controls were changed. The existing supported
`agent-hub-context deliver --surface codex --profile agent_startup --capability
shell --project summitflow --task-type web-research --format json` route then
succeeded through the owning runtime.

- delivery_id: `787df5d2-0e8c-4f13-80db-95a913f8f163`
- artifact_id: `context-7027db111a2361d0db758b060271bb5b22091c93ec919a0939259d8a3e00e728`
- payload_hash: `7027db111a2361d0db758b060271bb5b22091c93ec919a0939259d8a3e00e728`
- status: `ok`; one tool-capabilities block, component state `included`, with
  the new `st.web` guidance present.

Only identifiers, hashes and inclusion results were inspected/reported; private
context content was not logged. This proves canonical generation and delivery
through a real consumer-facing route, not model ingestion or subsequent use.

## Integrated owner checkpoint

- All 22 migrated namespaces load through reviewed bindings in the existing tool
  registry; `st tools extensions --check` reports all prerequisites present and
  no registration diagnostics. This is not a remote-service health claim.
- Independent review caught and fixed wrapper loss of `--`, missing selected
  project roots, and help lookup with positional arguments. Real wrapper tests
  cover these seams; fixture tests cover stdio, nonzero exit and process-group
  SIGINT/SIGTERM. Grants are checked before browser policy or owner dispatch.
- Fresh-interpreter tests forbid owner imports and socket connections during
  actual root help and manifest generation. Existing filtering, density and
  on-demand guidance remain in UsageSpec, with no parallel policy store.
- Latest scoped SummitFlow gate: 3,104 passed, 2 skipped, 71 deselected; Ruff,
  types, architecture and Biome passed. Additional shared-engine identity tests
  passed (2); targeted wrapper/operator/core route tests passed (192).
- Code Intelligence owner: 144 tests; Design Tools: 36; Browser: 16; Desktop:
  39; Vault: 9. Agent Hub: 3,665 passed, 50 skipped. Owner tests mock model,
  HTTP, browser and desktop effects. Browser JavaScript receives syntax-only
  TypeScript checking plus Biome, preserving its existing untyped contract.
- Actual `st search configure_design --scope checkout --limit 2` returned the
  new host symbol. Actual `st graph status --project summitflow` used the owner
  and the existing canonical code-graph refresh pipeline successfully.
- Actual `st browser --proxmox health` exited 0 and reported both engines DOWN;
  no browser was launched or repaired. This proves owner execution, not engine
  availability. Active desktop operation remains untested intentionally.
- Actual `st design asset generate` without fallback rejected before I/O (2).
  The existing design-assets GET returned its normal envelope through the
  extracted storage engine. API/worker tests and identity assertions confirm
  one owner implementation and the unchanged durable artifact root.
- Safe actual `st neri capabilities`, `st learn capabilities`, and `st models
  list --limit 1 --json` succeeded. No offensive/paid work was used for these
  checks. Learn's accepted-only manual-task promotion behavior is retained.
- Managed rebuilds succeeded for SummitFlow, Agent Hub, Jobinator, Portfolio,
  Neri and Learn. Native packages require installation, not new services.

A second real Codex-context delivery (`--task-type frontend`) returned `ok`
with browser/search guidance and on-demand discovery:
`delivery_id=bea7ad3f-6421-4560-afe1-916b03f3a055`,
`artifact_id=context-e2c92a80fa3be99518090a77ab142cc36d31e84583499d1637b7ac5f790f73ca`.
Again, this is delivery evidence, not observed model ingestion. A telemetry
regression test confirms a previously unknown extension namespace is counted
without retaining its arguments or reviewed content in command metrics.

## Verification incident

A legacy design test still invoked the real root CLI while mocking its former
in-process module. On 2026-09-20 at 18:07 UTC it escaped those mocks after the
process migration. The run was stopped. Read-only checks found exactly one
new asset in the incident window: `the-aftertimes`, ID `524`,
`asset-90f0903ee40b` (Scout Sprite), and no new mockups. Agent Hub recorded two
failed critique requests (500), zero recorded input/output tokens; this is not
a provider billing audit. The owner approved cleanup of this exact test asset.
Before deletion, its identity was reconfirmed and derived assets, exports,
comments and ratings all had zero references. The normal API deleted the asset;
a subsequent GET returned 404 and the database count was zero. Its orphaned
69-byte SVG was moved to the local, ignored recovery directory
`.dev-tools/test-asset-524-recovery.TCImqx/asset.svg`; no other asset was removed.

The legacy domain suite now runs directly against the owner app with mocked
transports; ST retains wrapper-only tests. An autouse CLI test guard now rejects
launching installed extension programs unless dispatch is mocked, permitting
only the isolated fixture executable. Useful failure evidence remains locally
in `.dev-tools/st-owner-migration-legacy-test-failure.txt` and is not published.

## Published native owners

All repositories are private, their local and remote main SHAs match, and their
tasks are closed. Canonical local gates passed; these new repositories have no
GitHub Actions workflows, so remote CI is not claimed.

| Owner | Commit |
|---|---|
| browser-automation | `72d6ed3ce51c772d06f25ddaba22c948f0e8fd44` |
| desktop-automation | `93d0553c5b580ff2bdb3c193b91450aa7d13f12f` |
| code-intelligence | `53dea8057502a79bda2953eea93f55b9e6ab510e` |
| design-tools | `9c21ac07c9d93b6d168fc8cbfccc737bd2c7ed0d` |
| vault-tools | `69138bd5bcb8ffc144fa8ac1f89dcfd80640704e` |

## Legacy Pulse retirement

The owner authorized removal if the briefing feature was legacy. Investigation
found its sole engine path `/home/kasadis/.hermes/scripts/pulse_db.py` absent,
with no registered Pulse project, engine in repository history, workspace callers,
Hermes source reference, system/user service, timer, cron entry or process.
History showed only the wrapper's initial addition and later usage metadata;
its old tests mocked subprocess execution, not a working engine. External-host
callers cannot be disproven, but this checkout could not serve them already.

Removed the wrapper, root registration, README advertisement and stale briefing
discovery. Regression checks prove it is absent from root help and full/task
manifests (51 focused tests passed). No schema initialization, durable data or
system configuration was changed. Core `st pulse` coordination is unchanged.

## Explicit gaps

- Final managed-owner and SummitFlow publication results are recorded in the
  parent task log. Publication and final checks remain required for closeout.
- Pre-existing unslop files and registration edits remain excluded from edits,
  command execution and publication. Publication uses an isolated copy because
  path-scoped commits cannot separate two owners' changes inside main.py.
