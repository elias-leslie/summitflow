# agent-hub audit (read-only) - 2026-11-02

Repo: /srv/workspaces/projects/agent-hub. 3710 commits total, 844 in the last 90 days, 85 of those mention fix/repair/regression (10%). The history is feature-heavy, not fix-heavy.
Helper scripts (mine, in scratchpad): ah_loc.py (LOC by path), ah_dead.py (backend modules with no non-test reference), plus inline python for frontend reachability.

## 0. Baseline verified

- `python3 -I loc.py <repo> 2`: src=244,347 test=119,037 ratio 0.49. Matches the baseline you gave.
- `st check budget` (the tool counts differently, excludes some paths): src=193-194k tests=100k ratio 0.52 (ceiling 0.80). Two runs, minutes apart:
  - run 1: state=ok gate=113s/116s, slow>3s=0
  - run 2: state=over gate=125s/116s over=gate_duration, worsened test_loc +6460 (94.0k -> 100.5k), gate median 112s -> 125s. A later run showed slow>3s=0 slowest10=1s, so the 30s outlier in the first JSON run was one-off noise.
  - So: the gate is at its budget (~2 min) and the test LOC added since the baseline is what tipped it over. There is no slow-test problem; the cost is spread over many tests.
- `.st-check.toml` only sets `[pytest] workers = 4`; no custom stages.
- Test DB build runs `alembic upgrade head` through all 270 migrations (backend/tests/conftest.py:131, ci.yml:67). Inference: that is a fixed per-gate cost, not measured (I did not run the gate).
- Non-code weight: `docs/` is 57k lines (docs/audits 39.4k lines in 79 files, docs/evaluations 10.9k lines in 62 files), nothing in code references them (`rg 'docs/(audits|evaluations)'` outside docs = 0 hits). `.dev-tools` is 548 MB, git-ignored scratch (not in the repo, but it is on disk).

## 1. Biggest areas

Columns: src LOC / test LOC (tests that live in the area's own dir, or mapped by name; see caveat) / commits touching in 90d / last touch / fix-ish commits in 90d (`-i -E --grep='(fix|fixes|fixed|repair|regression)'`) / live callers.
Test mapping caveat: backend tests live in a separate tree; the "test" numbers below are by dedicated test dirs, so treat as approximate.

| # | Area | src | test | 90d | last | fix | live callers |
|---|------|-----|------|-----|------|-----|--------------|
| 1 | backend/app/services/memory | 20.8k (+4.1k api/memory*, 3.2k st-cli memory*, 6.9k frontend) | 13.8k (tests/services/memory); 18.3k all memory-named tests | 45 | 11-01 | 7 | api/memory*, st-cli, frontend /memory, context injection. DB: 483 memories, 3,495 injection metrics |
| 2 | backend/app/services (top-level, 100+ files) | 27.0k | 18.9k (tests/services top) | 321 | 11-02 | 39 | everything |
| 3 | backend/app/api top-level (+complete) | 14.7k (+9.3k complete) | 15.8k api, 6.1k complete | 181 / 60 | 11-02 | 23 / 7 | FastAPI routers, all registered in api/__init__.py:51-92 |
| 4 | backend/app/services/tools | 9.2k | 4.8k (tests/tools) | 33 | 10-30 | 2 | direct tool executor for api/complete tool loop |
| 5 | backend/app/services/workflow_runs | 8.3k (engine.py 2,509 lines, 93 functions) | 7.1k (test_engine_pg.py alone is 3,303) | 47 | 11-01 | 4 | st workflow (st-extensions/workflow.json), aico tether (runs-api.ts, daemon.ts), frontend /workflow-runs 2.1k |
| 6 | backend/app/llm (+providers) | 10.1k (providers 4.9k) | 4.2k (tests/llm) | 47 | 10-29 | 9 | api/complete, workflow executors |
| 7 | backend/app/services/session_ingestion | 5.2k (+2 codex protocol JSONs, 10.7k lines) | 4.6k | 49 | 10-30 | 10 | host_sessions/session_ingestion API, scripts/codex-session-sync (timer) |
| 8 | backend/alembic | 22.9k (270 migrations) | 0.1k | 114 | 11-01 | 11 | every deploy and every test DB |
| 9 | frontend/src (app 31.9k, components 17.5k, lib 6.9k) | 57.6k | 14.8k (13.5k flat in __tests__) | ~190 | 11-02 | ~27 | the dashboard; every route is in sidebar-nav.tsx:44-140 |
| 10 | packages/st-cli (agent-hub-st) | 9.6k | 1.2k own + 5.1k in backend/tests/st_cli | 79 | 11-02 | 4 | summitflow imports it (10 files in summitflow), design-tools (2), code-intelligence (188 files, mostly eval run fixtures) |
| 11 | packages/chat-ui | 6.7k | 0 in package, but 16 frontend/src/__tests__/*chat* files cover it | 21 | 10-30 | 2 | agent-hub frontend (11 files), summitflow (7), aico (7) |
| 12 | packages/agent-hub-client (py) | 3.4k (+10.7k JSON) | 2.0k | 19 | 10-30 | 3 | summitflow 19 files, jobinator-4000 9, portfolio-ai 12, design-tools 3, a-loom 1 |
| 13 | packages/agent-hub-sdk (ts) | 2.5k | 1.6k | 11 | 10-30 | 0 | aico 13 files, summitflow 3, agent-hub frontend 3 |
| 14 | scripts/lib + codex-session-sync | 3.9k | 1.1k (test_codex_sync_runner) | 47 (scripts/) | 10-25 | 1 | systemd timers codex-session-sync, codex-session-close-inactive (scripts/systemd) |
| 15 | backend/scripts | 2.4k | 2.0k+ | 82 | 11-01 | 13 | seed/export used by app; 1.5k is run_claude_orchestrated_worker.py |
| 16 | packages/notes-ui | 1.9k | 0 | 0 | 06-05 | 0 | agent-hub frontend/app/notes + sidebar-footer |
| 17 | packages/passport-client | 1.1k | 0 | 1 | 09-09 | 0 | aico/web/frontend (next.config.ts), agent-hub frontend (2 files) |
| 18 | integrations/context-delivery | 0.9k (+0.4k pi/claude installers) | 2.1k in one file | 34 | 11-02 | 6 | installed into agent harnesses |

Sub-areas inside the big buckets (depth 3-4, backend/app):
- services/(files) 26,973; services/memory 20,819; api/(files) 14,716; api/complete 9,318; services/tools 9,182; services/workflow_runs 8,309; session_ingestion 5,249; llm/providers 4,857; context_observability 3,657; llm/(files) 3,241; models 2,980; subscription_accounting 1,891; cli 1,613; context_changes 1,600; workflows 1,547; middleware 1,191.
- Largest single files: workflow_runs/engine.py 2,509; services/runtime_context.py 2,131; openai_completions.py 1,322; session_queries.py 1,132; subscription_accounting/collector.py 1,080; anthropic.py 1,043.
- Most-touched source files in 90d: config.py 37 commits, workflow_runs/engine.py 24, api/complete/streaming.py 24, models/__init__.py 24, subscription_accounting/collector.py 19, admin_activity_cost.py 19. Model catalog files (constants/models.py, catalog_entries.py, api/models.py) 17 each.
- Live DB row counts (st db query, read-only, exact count(*)): every table I checked that has code behind it has rows (memory_review_runs 276, tier_change_log 11,260, native_continuation_turns 119, native_observation_receipts 445, context_judgments 60, context_maintenance_items 102, task_narration_tags 2,388, api_keys 127, project_permissions 20). Only `user_preferences` is empty (api/preferences.py, 94 lines, still called by chat-panel and the providers tab). So the backend is not full of dead feature code. Note pg_stat n_live_tup showed 0 for many of these (stale stats); only count(*) is trustworthy.

### Cross-project use of the packages (bounded rg, excluding node_modules/dist/lock/md)

- `@agent-hub/sdk`: aico 13 files, summitflow 3.
- `@agent-hub/chat-ui`: summitflow 7, aico 7.
- `@agent-hub/passport-client`: aico 2 (web/frontend/next.config.ts and one more).
- `agent_hub` python client: summitflow 19, portfolio-ai 12, jobinator-4000 9, design-tools 3, a-loom 1.
- `agent_hub_st`: summitflow 10, design-tools 2, aico 1.
- nightshift, neri, vault, blackbox: none of these packages.
- `@summitflow/notes-ui` is a DUPLICATE: agent-hub/packages/notes-ui/src and summitflow/packages/notes-ui/src are the same 20 files; `diff -r` shows 9 differ (369 diff lines) and summitflow's has one extra file (pasteFormat.ts). Package name and version are identical (@summitflow/notes-ui 0.1.0). The agent-hub copy has not changed since 2026-06-05 (1 commit ever); summitflow's carries the paste-format and editor-save fixes (tests in summitflow/frontend/lib/notes-*.test.tsx). Agent-hub copy is the stale fork. Also 4 built `dist/` files are tracked in agent-hub git (packages/notes-ui/dist, 3.3k lines).
- Codex protocol JSON schemas duplicated byte-for-byte: backend/app/services/session_ingestion/codex_protocol/0.159.3/{ServerNotification,ServerRequest}.json and packages/agent-hub-client/agent_hub/codex_protocol/0.159.3/* (`diff -rq` shows only __init__.py differs). 10,679 lines x2. The backend reads its own copy (app_server_observations.py:15); the client's copy is referenced only by its own __init__.py. No other repo imports it (rg over summitflow/backend, aico, neri, nightshift = 0).

## 1b. Not worth it (ranked by LOC removed per effort)

| Area | LOC | Why | Do |
|------|-----|-----|----|
| Alembic history, 270 files | 22.9k (94 data-only migrations = 10.7k lines; 176 schema = 12.1k) | Seeds/retirements/catalog bumps replayed on every fresh DB and every test DB. 24 "drop", 10 "retire", 8 "remove", 10 "seed" by filename. Includes other projects' seed data (seed_jobinator_agents 367 lines, second_opinion agents 306, retire_portfolio_* ). 108 migration files were added in the last 90 days; 29 of the commits that added them mention model/catalog/gpt/gemini/claude/opus/route in the subject, i.e. a model catalog bump is a hand-written migration. | Squash to one baseline schema (pg_dump of current head) plus a short tail; delete data-only migrations whose effect is already in the live DB; move model catalog bumps to the existing seed_agents_data/model_catalog.json sync path (model_catalog_service already reads it). Prod needs `alembic stamp` to the baseline. |
| docs/audits + docs/evaluations | 50.3k lines (non-code) | 141 files of dated evidence dumps (json, run outputs, ah_mcp_server.py + run.py experiments, 1,289 lines of eval python). No code reads them; last touch 10-22 / 10-27. | Move to Vault/archive or delete from main; keep the 2-3 conclusions in docs/architecture. |
| Duplicate codex_protocol JSON | 10.7k (in git) | Two identical copies (above). | Delete the client's copy (and codex_protocol/__init__.py) unless something imports it; or generate from one source at build time. |
| Dead frontend cluster | 2,640 | Import-graph reachability from every page/layout/route (python, resolves @/ and relative): 16 non-test files unreachable. runtime-context: useRuntimeContext.ts 475, BlockRow.tsx 422, resolver.ts 287, LibraryPane 256, RenderedPane 253, EditPromptModal 181, RenderedPreviewModal 158, BootReactorTopbar 110, ComputedRow 78, TypeChip 52, RenderModeMenu 43, TokenGauge 35, PolicySettingsPanel 32. Also components/output/code-block.tsx 244 (only its own test imports it; prismjs dep + 106-line prism-theme.css imported by globals.css) and charts/ChartCard.tsx 13. LibraryPane last touched 2026-05-10. Only test hit: __tests__/runtime-context-resolver.test.ts and output-presentation.test.tsx (103 lines) test dead code. Inference: possible dynamic import misses, check with `st` unused-export tool before deleting. | Delete cluster, its two tests and the unused CSS module rules (runtime-context.module.css is 866 lines, probably mostly dead). |
| agent-hub/packages/notes-ui | 1.9k + 3.3k tracked dist | Stale fork of summitflow's package (see above). | Consume summitflow's published package (or move one canonical copy to a shared place) and delete this one. Medium: agent-hub frontend/src/app/notes/page.tsx and sidebar-footer need to point at it. |
| backend dead/near-dead modules | ~930 | ah_dead.py: backend/app modules whose basename appears nowhere outside tests: services/tools/gemini_tools.py 224, error_tracking.py 120, git_status_summary.py 112, api/complete/cache_handler.py 110, delivery_only.py 68, model_mapping.py 60, review_agent.py 52, pkce.py 47, agent_output_ingest.py 33, _executor_memory_review.py 28, _health_prober_models.py 62, mcp_constants.py 13. Basename matching can miss string-based registration, so verify each. | Delete after a per-file check; small. |
| backend/scripts one-shot repairs | 306 + tests | backfill_workflow_transcripts.py 76, compact_child_session_updates.py 66, repair_backfilled_transcript_activity.py 164 (all touched 10-29/10-30, no references anywhere), evaluate_context_runtime.py 125 (last 09-19, no references). | Delete after the backfills have run; keep nothing "just in case" (git has them). |
| run_claude_orchestrated_worker.py | 1,470 + 1,107 test lines | Referenced only by its own test here; its real caller is summitflow (backend/cli/commands/_claude_dispatch.py:84 shells into agent-hub's checkout). Last touch 2026-10-09. A SummitFlow CLI worker living in agent-hub. | Move to summitflow (the owner of `st claude task`), take the test with it. Net -2.6k here. |
| Memory subsystem size | ~35.8k src across api/services/st-cli/frontend (+ ~18k memory-named tests) | 483 live memories and 3.5k injection metrics drive 21k lines of services: separate review agent (_review_agent_*, 1.2k), promotion, governance, redundancy, lifecycle_score, usage_tracker, applicability, analytics (3 files, ~0.8k), tier history, 6.9k frontend, 3.2k CLI. It is active (45 commits in 90d, 7 fix-ish), so it is not dead; the skepticism is proportional size. Inference: the live data is small enough that much of the scoring/analytics layer cannot be statistically meaningful. | Medium-large: audit the sub-features by usage (injection_metrics, review_runs=276, tier_change_log=11,260 are used), cut analytics/lifecycle/redundancy layers that have no consumer in injection or UI. Needs an owner decision on which memory features matter. |
| Frontend memory UI | 6.9k, 4 commits in 90d, app/memory untouched since 05-04 | Big UI for a 483-row table, rarely edited. | Keep, but it is the first candidate to shrink if memory is trimmed. |
| packages/passport-client | 1.1k, 1 commit in 90d | Used by aico web only (agent-hub's chat is explicitly tested to work without it: __tests__/chat-ui-no-voice.test.tsx:7-9). | Move to aico, or leave; small. |
| scripts/codex-session-sync + lib | 3.9k + 1.1k test | Live (systemd timers) and recently fixed for a real disk-write problem (commit 0492895a6), so keep. Overlap check: summitflow/backend/cli/lib/agent_hub_codex.py and native_session_delivery.py reference the same flow. Inference only. | Not a delete; compare with the SummitFlow side if consolidating session sync. |
| frontend/src/app/{token-share 2.0k, prompts 1.2k, chat 1.4k} | 4.6k | token-share and prompts: 2 commits each in 90d, nothing broken, nav-linked. Cannot tell if used (request_logs only holds 2 weeks and only completion traffic). | Ask owner; no evidence to cut. |

Things I checked and found NOT worth cutting: llm/providers (all six are wired, providers/__init__.py:16-26; faux.py 592 lines is used by workflow_runs executors and 3 test files, so it is production-reachable test double - keep but note it), subscription_accounting (live tables, 24 commits), workflow_runs (new, actively used by aico), session_ingestion, access-control UI, st-cli.

## 2. Tests

Totals (my regex count over backend/tests, packages/*/tests, frontend/src/__tests__): 566 test files, 120,356 lines, ~4,836 test functions (frontend: 902 it/test blocks in 84 files), average 25 lines per test, ~14,400 assert/expect, ~6,100 mock/patch tokens (about 1.3 per test). 38 files exceed 600 lines and hold 35.9k lines (30% of test code). 17 `*_pg.py` real-DB test files total 8.2k lines.

Per-area ratio (src : dedicated test lines): memory 20.8k : 13.8k (0.66); workflow_runs 8.3k : 7.1k (0.86); session_ingestion 5.2k : 4.6k (0.89); api/complete 9.3k : 6.1k (0.65); llm 10.1k : 4.2k (0.42); tools 9.2k : 4.8k (0.52); st-cli 9.6k : 6.3k (0.66); agent-hub-client 3.4k : 2.0k (0.58); sdk 2.5k : 1.6k (0.63); frontend 57.6k : 14.8k (0.26); chat-ui 6.7k : 0 own (covered from frontend/__tests__); alembic 22.9k : 0.1k; backend/scripts+scripts 6.3k : 5.4k (0.86). By-mention ratios are higher (e.g. subscription_accounting 7.2k test lines mention it vs 1.9k src), but dedicated tests are only tests/unit/test_subscription_accounting.py 582 + test_runtime_accounting.py 456.

Over-testing signs (examples):
1. backend/tests/integrations/test_context_delivery_adapters.py: 2,103 lines, 42 tests, 271 asserts, 1 mock - one file testing integrations/context-delivery (~2.3k lines total of installers/hooks). 18 commits in 90d; test is ~1:1 with the code it covers and the single biggest integration test file. Split or trim to the install/uninstall contract (e.g. :850, :879, :908, :1375 are four near-variants of "adapter X preserves native prompt").
2. backend/tests/services/workflow_runs/test_engine_pg.py: 3,303 lines, most-touched test file (26 commits in 90d) mirroring engine.py (2,509 lines, 24 commits). Test is bigger than the code and churns with it every time the engine changes; sign of testing internals. Split by behavior (create/steps/attempts/cancel) and drop tests that assert intermediate scratch fields.
3. backend/tests/services/test_codex_credentials.py: 390 lines, 10 tests, 111 mock tokens, 10 asserts; most of the file is MagicMock session factories (see :43-55 `_session_factory`) and 10 near-identical rotation/commit-ordering scenarios (:76-343). Mock-only, brittle to refactor.
4. backend/tests/services/session_ingestion/test_service.py: 1,364 lines, 25 tests, 186 mock tokens vs 81 asserts. Same repeated MagicMock db setup per test (:38-520); worth a shared fixture or moving the cases to the existing PG tests.
5. frontend/src/__tests__/output-presentation.test.tsx (103 lines) and runtime-context-resolver.test.ts test code no page reaches (see dead cluster).
6. backend/tests/api/test_sessions.py: 845 lines, 29 tests, 119 mocks. backend/tests/st_cli/test_memory_cli.py 1,155 lines + test_memory_seed.py 823 (46 tests, 121 mocks): CLI tests patching `agent_hub_st.*.prompt_api` at module level (test_prompt_cli.py:29-122) assert call plumbing, not behavior.
Not found: snapshot bloat (no __snapshots__ or toMatchSnapshot; 2.4k lines of json fixtures in frontend/__tests__/fixtures), no giant parametrize copies; test_secret_redaction.py (883 lines) is properly parametrized (:74, :85, :107).

Under-testing signs:
- subscription_accounting (1.9k src, collector.py 1,080 lines, 19 commits in 90d on collector alone, 5 fix-ish): dedicated tests ~580 lines. The best candidate for more tests.
- frontend: ratio 0.26, with app/context 5.0k src (6 commits, tests 498) and app/sessions 5.4k (34 commits, 3 fix) covered mostly by sessions.test.tsx (762 lines). app/agents 5.0k has 7 agent-* test files; I found no test files by name for access-control 3.5k or token-share 2.0k (inference from file names).
- services/tools: 0.52 ratio but each executor has a named test file (test_executor_io.py, _consultation.py, _web.py, _model_mgmt.py); tests/tools also tests gemini_tools.py (224 lines) which has no non-test caller (see dead modules). Adequate.
- llm/providers openai_completions.py 1,322 + google.py 685: tests exist (params, streaming, tool replay); acceptable. llm has 9 fix-ish commits in 90d, the highest fix density per commit among backends (19%).
- session_ingestion: 10 fix-ish of 49 commits (20%), highest. Tests are 0.89 of src, so the fix churn is not from thin tests but from format variance in transcripts.
- alembic: no tests for individual migrations; only the head-upgrade in conftest. Fine for a solo project.

Verdicts: memory (right, heavy), workflow_runs (right, over-coupled to engine internals), api/complete (right), llm (slightly thin on openai_completions but ok), session_ingestion (right), st-cli (right), integrations/context-delivery (over), codex credentials / mock-heavy services (over-mocked), subscription_accounting (thin), frontend overall (thin by ratio, but stable pages), chat-ui (covered externally, fine). Overall: reasonable ratio (0.49-0.52), but the gate is at budget and the added test LOC is concentrated in a few giant files; no sign of a mass over-testing problem.

## 3. Recommendations, ranked

1. Delete dead frontend cluster + stale notes-ui fork + codex_protocol duplicate. Removes about 2.6k frontend src, 0.2k test, 1.9k notes-ui (+3.3k tracked dist), 10.7k JSON lines. Effort: small to medium (verify no dynamic imports; repoint notes page to summitflow's package).
2. Move docs/audits and docs/evaluations (50k lines, 141 files) out of main (Vault or an archive branch). Removes 50k lines of non-code from every grep/index. Effort: small.
3. Squash alembic to a baseline + short tail, and stop writing catalog bumps as migrations. Removes about 20k lines and speeds the test DB build (inference: fixed cost of 270 migrations in every gate/CI run, not measured). Effort: medium; needs prod `alembic stamp` and a restore-tested backup first.
4. Move run_claude_orchestrated_worker.py (+test) to summitflow, and delete the four one-shot backfill/repair scripts and evaluate_context_runtime.py. Removes about 3.4k src+test. Effort: small.
5. Delete the dozen backend modules with no non-test callers (~930 lines) after per-file check. Effort: small.
6. Trim the mock-heavy and giant test files (test_context_delivery_adapters 2.1k, test_engine_pg 3.3k, test_codex_credentials 0.4k, session_ingestion/test_service 1.4k): realistic cut 3-4k lines and a few seconds of gate time; gate median is 125s vs a 116s budget, so this is the only direct lever on the over-budget gate. Effort: medium. Add the missing subscription_accounting collector tests in the same pass (small, +0.4k).
7. Split workflow_runs/engine.py (2,509 lines, 93 functions, 24 commits in 90d) by concern so changes stop touching one file and one 3.3k-line test file. No LOC removed; lowers churn and token cost per change. Effort: medium.
8. Decide memory scope with the owner: the 36k-line memory stack serves 483 memories. Candidate cuts: analytics, lifecycle_score, redundancy, promotion layers and their UI tabs (up to ~8-10k src + matching tests, inference; needs usage evidence). Effort: large; owner decision required.
9. Consolidate the Python and TS clients only if usage shrinks: agent-hub-client (19 summitflow files) and agent-hub-sdk (aico 13) are both live, different languages, no duplication. Leave.
