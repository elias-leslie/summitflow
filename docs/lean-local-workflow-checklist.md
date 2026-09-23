# Lean local-first workflow implementation

Task: `task-36705f79827e4110`. This checklist records implemented behavior and observed evidence. An unchecked item is still open; observations alone do not count as a repair.

## Curator retirement

- [x] Disable schedules, alternate launch paths, queued inference, automatic context edits and repair-task dispatch. Retired endpoints return 410; the legacy schedule re-import path keeps review jobs disabled.
- [x] Retire the active agent, tool registrations, launch controls and background-maintenance instructions while retaining historical sessions, findings, revisions and receipts. Agent Hub deployed accepted commit `8360ebda` with 3,701 backend and 226 frontend tests passing.
- [x] Reconcile curator-originated tasks individually; preserve independently valid defects and other agents' claims. Five unclaimed curator-dispatched tasks were cancelled with reasons; 14 failed histories and unrelated automations remain.
- [ ] Verify manual inventory, editing, exact preview, revision conflict, history and undo in the actual API/UI; unrelated automations still run.

## Context and discovery

- [x] Revise the inspected prompts with applicable scope and revision controls. Before/after effective previews were captured for SummitFlow and Learn-o-Tron; local completion, approval boundaries, manual context ownership, and verifier instruction hierarchy remain. The global learner memories still await dashboard-only scope correction below.
- [ ] Retarget global learner history and lab procedure to the learning context without deleting history.
- [x] Default `st tools manifest` to compact core discovery, retain explicit `--density full`, make `--task` select task density, and provide actionable unknown-surface guidance. Focused gate: 90 passed; actual CLI misspelling returned a suggestion and full-catalogue route.
- [x] Resolve unique short surface names directly. During this implementation, `--surface browser` initially required two calls; after the change the same live registry returns `st.browser` in one call. Ambiguous names list choices; 54 manifest tests pass.
- [x] Verify the Agent Hub tool-capability consumer explicitly passes `--density` (`adaptive`, `core`, or `task`) on each call; no full-manifest consumer was found in the inspected call path.
- [x] Label status percentages as HTTP outcomes and keep managed check detail artifacts; local acceptance failures exposed their exact test names through the retained report. Broader native usage reporting remains below.

Discovery measurement from the same live registry: before the change, `st tools cost` estimated full at about 18,157 output tokens and core at about 1,040 (generated-text estimate). After the change, the CLI emits 4,171 bytes by default versus 72,676 bytes with `--density full`. These are generated output sizes, not billed tokens or elapsed-time savings.

## Native records and reports

- [ ] Ingest supported native custom calls/results once across split batches and replay, preserving event identities, timestamps and call/result pairing.
- [ ] Record available response-level input/output/cache usage with provenance; reconcile cumulative counters separately and keep missing attribution unknown.
- [ ] Preserve parent/child usage relationships without double counting.
- [x] Correct ST tool-report period labels, separate findings from inspected shell events, mark unobserved adoption as unknown, and add audit/cost session filters. HTTP status is labelled as HTTP status; manifest text estimates are labelled separately from native/cache usage and billed cost. Live 24h audit observed 3,337 events but zero inspectable shell calls, so absence of findings is not evidence of healthy tool use.
- [ ] Surface native usage/cache provenance and task outcomes in the appropriate existing reports/views after ingestion supports them.
- [x] Remove legitimate Git inspection from the waste rules and stop emitting cost feedback from aggregate output volume, aggregate request tokens, or HTTP status alone. Remove the scheduled tool-governance feedback scan; historical maintenance rows remain in the existing API.
- [x] Reproduce and repair current completion and learning-save caller/tool defects. The planner's unsupported restricted local fallback was removed and its primary changed to the verified Codex OAuth subscription route; automatic task/QA-history calls to `sdk.save_learning` that produced 422 were removed, with task evidence retained in task results/events. Live post-rollout request reduction remains to be observed.

## Coordination, checks, security and transcripts

- [x] Correct relative lease path resolution against the project checkout and reject `st commit` of files held by a foreign lease, including `--skip-checks`; focused tests cover overlapping and unrelated paths. Direct filesystem writes and direct Git commands remain outside this ST guard.
- [ ] Verify acceptance is bound to the exact integrated/deployed source and ordinary local completion does not require publication.
- [x] Profile broad-check duplication and expensive full-suite work. Agent Hub full acceptance took about 137 seconds, with 119 seconds in 3,753 backend cases. JUnit showed one oversized tokenization fixture at 10.6 seconds; replacing it with four threshold cases brought that focused file to 0.14 seconds. SummitFlow full acceptance passed 3,482 backend and 229 frontend tests; backend tests took 94.32 seconds. Its largest individual case took 3.13 seconds, with no comparable single hot spot worth a test rewrite. Commit checks and full acceptance serve different scopes; the exact-source acceptance cache is existing behavior and is not counted as a new gain.
- [ ] Assess local secret, dependency and static checks in relevant repos. SummitFlow now runs gitleaks, OSV and one local Semgrep rule on 920 files (zero findings, about 3.4 seconds), with positive/negative fixtures. Agent Hub gitleaks/OSV pass but Semgrep still skips without local rules. Neither project has local CodeQL parity.
- [x] Measure growing-transcript reread cost: 45 JSONL files changed in 24h total 220 MB, with largest about 43 MB. A three-run local sample of its full `read_text().splitlines()` path took about 0.17 s per read; a 64 KiB tail read took about 0.00007 s. The sync timer is every 15 s. This is implementation/runtime sampling, not provider usage or billed cost.
- [ ] Improve the existing incremental path with rotation/truncation/replay coverage because the observed reread cost is material for growing active files.

## Everyday task result and rollout

- [x] Use this coding task's failed `--surface browser` discovery as a recorded recurring-pattern candidate and repair its cause in the ST registry CLI. This specific lookup now takes one successful call rather than a failed call and correction; aggregate per-task recurrence remains unproven.
- [ ] Demonstrate fewer avoidable calls, output, turns or waiting without worse acceptance or owner intervention, or record why further change does not justify its cost.
- [ ] Complete integrated managed checks, actual route/UI checks, task-scoped diff review, coherent local commits and task closeout. GitHub publication is optional.
