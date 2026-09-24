# ST tools and dependency evidence, 2026-09-23

This checkpoint reports successful operations and full tasks where comparable. Timings are wall time from the managed command or an isolated browser run. Text cost is reported as characters and a rough characters/4 estimate where provider billing was unavailable; it is not billed token usage. Cold and warm browser runs are distinguished below. No package update or proposal was published.

## Browser

The managed local target used the approved headless Chrome AI profile. `st browser check` now reports uncaught JavaScript errors, failed HTTP responses, and missing response evidence separately; the latter is `INCOMPLETE`, not a pass. It waits for observable page loading to clear before screenshots, uses unique evidence paths, checks the selected target's health, and cleans up only sessions it owns. The live SummitFlow Runtime page reached `readiness=ready` with populated service cards. A separate `/api/system/stats` request lacked recorded response evidence and was correctly reported as incomplete. An earlier check exposed a real `/api/agent-hub/projects/permissions` HTTP 500.

| Route and workload | Observed wall time | Result and limit |
| --- | ---: | --- |
| Managed `st browser check` on example.com, three responsive views | 8.0 s, repeat 7.7 s | Completed screenshots and distinct evidence paths |
| Managed failure fixture, thrown error plus missing asset | 7.6 s | `ISSUES`: one page error and two HTTP 404s |
| Managed fixture with no recorded response | 7.6 s | `INCOMPLETE`: unavailable response evidence |
| ST no-op dispatch, warm median | 714 ms | Wrapper floor |
| Installed agent-browser 0.26.0, isolated single viewport | 5.79 s median before batching; 5.47 s after | Same managed interface |
| Reviewed agent-browser 0.38.1, isolated single viewport | 3.55 s median before batching; confirming trio 3.54 s | Candidate only; individual timings varied |
| Playwright CLI 0.1.21 attached to isolated ST-managed CDP | Snapshot 209 ms; eval 717 ms medians | Targeted operations, not an end-to-end check |
| Native browser route and Proxmox Chrome/Lightpanda | Unavailable | The isolated endpoints were down; the available personal Chrome profile was not used for an automated comparison |

The browser target remains unverified: there is no comparable isolated native successful-task token measurement. The 0.38.1 candidate and Playwright CLI results are useful for the next managed-interface iteration, not evidence of universal engine parity. The managed default remains 0.26.0. Browser task `task-4a3f92eb9d12497c` owns upgrade qualification; `task-5ec32b95802f4271` owns a policy-managed Playwright CLI backend with the same evidence and ST lock. The browser project's `BENCHMARK.md` holds the raw run notes.

## Code search

TypeScript and TSX symbols now come from Tree-sitter. Indexed slices check current file hashes and UTF-8 byte offsets, so dirty files and Unicode do not produce stale snippets. Checkout and indexed results apply secret-file exclusions, report total matches, searched-file counts, truncation and next offset, and rank implementation definitions ahead of tests. Literal ripgrep remains available for suitable text queries.

On the SummitFlow checkout, a no-match symbol query took 250 ms after the change versus 1.6 s before it; a matching symbol query took 276 ms and literal text search 219 ms. The live CLI returned `count=11`, two results at offset 2, and `next_offset=4`. These are individual local observations, not distributional latency claims. The code-intelligence project passed its full managed gate and rebuild; its Python package declares no service to restart.

## Public web research

The controlled question was the Python 3.13 free-threaded build caveat on the official What’s New page. Native web open plus find took about 2.14 s and returned about 38,311 characters across two calls. After the Agent Hub extraction fix, one `st web fetch --backend direct --focus-query ... --max-chars 2500 --raw` took 3.68 s and returned 3,383 characters, including 2,201 content characters. The rough output estimates are about 9,578 versus 846 tokens. ST kept the `-X gil=1`, `sys.version`, and extension-module qualifications together, marked `focus_selection` as incomplete, and flagged an inferred date. Native was faster in this run; billed usage and cache effects were not available.

The web benchmark passed 21/21 cases after Trafilatura single-pass extraction, structured headings/lists/tables, deduplication, direct-fetch routing, explicit incomplete/provider states, and private or credential URL fallback guards. Firecrawl returned a full 19,994-character scrape for the comparison page; Tavily was unavailable. These alternatives were not adopted without matched cost and reliability evidence.

## Dependency engines and inventory

The existing hosted Dependabot proposals are [Python PR #2](https://github.com/elias-leslie/summitflow/pull/2) and [Actions PR #1](https://github.com/elias-leslie/summitflow/pull/1). The live review packet linked PR #2 to FastAPI. Dependabot CLI and Renovate local were not installed, so their generation, cold startup, image caching, and artifact stability are explicitly unmeasured. [Dependabot CLI](https://github.com/dependabot/cli) runs isolated updater/proxy jobs and yields artifacts rather than opening PRs itself. [Renovate local](https://docs.renovatebot.com/modules/platform/local/) is experimental and supports extraction and lookup, not full update runs. Task `task-1fe586667a224a89` owns a pinned isolated comparison before any adapter is added.

`st tools dependencies` reads the existing Explorer pipeline and separates declared, locked, installed, latest, and recommended versions. The refreshed SummitFlow inventory has 627 current entries across Python and Node; one stale row was removed by Explorer’s existing cleanup rule. A Python refresh took 2.6–2.8 s. FastAPI showed declared `>=0.115.0`, locked and installed `0.136.3`, latest `0.141.1`, and no recommended version. The advisory check remains `unknown` because `pip-audit` was absent. A repeated review reused revision 3 with `new_evidence=false`; the evidence-linked decision is `investigate` pending PR compatibility and advisory coverage. No install was queued.

The Runtime Dependencies view shares this inventory and exposes review and decision controls. Its managed-browser snapshot showed the separate version columns, unknown advisory state, hosted PR link, and recorded decision. Pagination renders 50 rows at a time. The registered review workflow checks direct packages weekly and reacts to newly observed advisory changes; unchanged evidence does not create a revision. It does not install packages.

## Routing and telemetry

Scoped Agent Hub DB prompts now state capability-based routing and evidence policy. The measured effective dependency-manager context changed from roughly 1,349 to 1,519 estimated tokens; delivery preview included the updated prompt. Centrally managed ST skill guidance holds the detailed comparison. The ST registry advertises `st tools dependencies` on demand. Native web/browser call hints are reported as permitted telemetry outside the ST shell-command adoption rate; absent hints remain unclassified. Historical session events are not backfilled.

All implementation commits are local. SummitFlow’s last managed rebuild passed its full gate with 3,500 Python tests, 229 frontend tests, lint, types, and security checks. Agent Hub and code-intelligence passed their managed gates. Browser automation passed its full gate, including 24 tests; its final upgrade scorecard is recorded in its own benchmark file.
