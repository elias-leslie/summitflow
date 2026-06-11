# st search — Honing Tracker & Iteration Prompt

Living doc for the ongoing effort to test/audit/fix/improve `st search` (Precision Code Search).
Update the Work Log and Open Items every iteration. The Iteration Prompt at the bottom is
self-contained — paste it into any agent session to run another honing pass.

## Architecture map (orient here first)

| Layer | File | Role |
|---|---|---|
| CLI command | `backend/cli/commands/search.py` | scope resolution (project/checkout/combined/AUTO), checkout escalation, stale-index stderr notes |
| CLI output | `backend/cli/lib/search_output.py` | compact `SEARCH:...\|mode=...` lines |
| CLI hints | `backend/cli/lib/search_hints.py` | actionable refinement hints from result metadata |
| Checkout search | `backend/cli/lib/search_checkout_symbols.py`, `search_checkout_text.py`, `search_checkout_precision.py` | live filesystem symbol/text search + merge payloads |
| Result merge | `backend/cli/lib/search_results.py` | checkout-overlay-ahead-of-index merging |
| Server entry | `backend/app/services/context_gatherer/precision_code_search.py` | symbol-first retrieval, text fallback, per-term union, staleness, metadata |
| Query analysis | `.../_precision_query.py` | term extraction, NL/import detection, identifier-shape detection |
| Ranking | `.../_precision_ranking.py` | candidate search, generic-only junk suppression, ranking |
| Index source | `explorer_symbols` + `explorer_entries` tables; refreshed by bi-hourly explorer sweep (`backend/app/tasks/explorer_tasks.py`) + daily maintenance (`backend/app/storage/scan_history/_maintenance.py`) |

Key tests: `backend/tests/cli/test_search.py`, `backend/tests/services/context_gatherer/test_precision_ranking.py`, `test_precision_code_search.py`, `test_explorer_collector.py`.

## Invariants (do not regress)

1. **No confident junk.** A query whose user-typed identifier-shaped tokens ALL miss the index must never return symbols that matched only generic words — suppress and say so in the hint (`missed_identifier_terms`, `suppressed_generic_symbols` metadata).
2. **NL queries keep weak-coverage hits.** Suppression applies only to user-typed identifier tokens, never to NL-synthesized CamelCase/snake variants ("project selector" must keep `ProjectSelector`-ish hits).
3. **Symbol hits survive weak coverage.** Weak multi-word coverage appends corrective text matches; it never discards symbol hits (combined mode + reserved text budget share).
4. **Stale index self-heals.** Identifier query + zero indexed symbols + AUTO scope + checkout-is-project → live checkout escalation; merged checkout overlay suppresses misleading "missed" hints.
5. **Honest stderr notes.** "refresh did not complete" only when an inline refresh was actually attempted (missing index/timestamp reasons); age-only staleness says the index predates the latest scan.
6. **Compact output stays compact.** Default output is the `SEARCH:` line + hint + budgeted context; never raw dumps.
7. **Hints are decision-grade.** Every empty/fallback mode tells the agent the *most specific* reshaping action, not generic advice, and never recommends retrying verbatim.

## Work log

### 2026-06-11 (session 5)
- **`--file` exact-path trap killed**: `--file <basename>` (or any non-exact partial path) returned `mode=empty` with **zero hint** — invariant-7 violation, and other hints actively steer agents to `st search --file <path>`, so the trap was on the recommended path. Fix is structural across both backends: server `symbols/by-file` (`explorer.py`) and storage `resolve_symbol_file_paths` (`explorer_symbols.py`, suffix LIKE with escaped `_`/`%`, whole-segment match only: `ranking.py` ≠ `_precision_ranking.py`) resolve a unique basename/path-suffix fragment to the indexed path; checkout scope mirrors it via `_resolve_checkout_file_suffix` (filesystem walk, sorted, cap 5). Unique → normal output with `|resolved_from=<frag>` on the SEARCH line; ambiguous → hint lists candidate paths; none → hint says fragment resolution exists + spelling/new-file advice; indexed-but-symbol-less file (`file_exists`) → "no extractable symbols, use --text or read it". `--no-hint` now also suppresses file-mode hints (`_emit_file_output` threads the flag).
- Live-verified all four behaviors on both scopes plus `-P agent-hub --file _heartbeat_state.py` (resolves in the other project's index). Note: probes 1–9 of the audit (healthy/CamelCase/NL/missing/generic-combo/partial-miss/--path/--text/cross-project) all matched invariants — session 4 fixes holding.
- Tests: +4 storage (resolution, segment boundary, literal `_`, ambiguity), +4 API (exact unchanged, basename, partial path, unknown plain-empty), +6 CLI (not-found hint, candidates hint, resolved_from line, no-symbols hint, checkout resolve, checkout ambiguity).

### 2026-06-11 (session 4)
- **Futile-retry hint loop closed** (open item): when AUTO escalation already live-parsed the checkout and found nothing, `_precision_result` now stamps `checkout_escalation_empty` into metadata, and the hint layer stops recommending `--scope checkout` — empty-mode hint says the identifier does not exist as written; definition-stale text-fallback hint recommends rescan only. Without an escalation attempt the brand-new-code advice is unchanged.
- **Stale threshold aligned with sweep cadence** (open item): `_PRECISION_INDEX_MAX_AGE` 30m → 150m (bi-hourly `summitflow-refresh-precision-indexes` cron `10 */2 * * *` + slack), so `stale_hit` only fires when the sweep demonstrably missed a cycle instead of ~75% of the time on a healthy system. Event-driven post-publish refresh added to open items as the next iteration's primary candidate.
- Hermeticity fix found en route: `test_search_text_fallback_definition_match_shows_stale_index_hint` was silently making a real `/projects` API call + live agent-hub tree parse through the session-3 cross-project escalation path — now pinned with `get_project_root_path=None`.
- Tests: +2 CLI hint directions, +1 CLI definition-hint variant, +2 collector threshold edges (119m fresh / 151m stale).

### 2026-06-11 (session 3)
- **Cross-project wrong-tree trap killed** (`commands/search.py::_resolve_search_roots`): `st search X -P agent-hub --scope checkout` run from a summitflow cwd silently searched the *summitflow* checkout and presented its files as agent-hub results — and the empty-result hint actively steered agents into this trap ("rerun with `--scope checkout`"). Now `_resolve_cross_project_roots` resolves the target project's registered `root_path` (new `config.get_project_root_path`) and searches *that* tree; if no root is registered/present, it fails with a precise error instead of wrong-project output.
- **Cross-project escalation** (open item closed): AUTO-scope `-P <other-project>` identifier misses now escalate to a live parse of the target project's registered root (`SearchRoots.cross_project_id`, lazily resolved only when escalation fires — no extra API call on indexed hits). Stale other-project indexes now self-heal like same-project ones.
- Live-verified both directions with a `qqzz_` probe planted in agent-hub: `--scope checkout` finds it (scope=checkout), AUTO escalates and prepends it (scope=combined), `build_project_pulse -P agent-hub --scope checkout` correctly empty after searching agent-hub's 6554 files (was: returned summitflow source). Same-project probes unchanged.
- Tests: +4 CLI (target-root search, no-root error, cross-project escalation, no-local-tree-parse without registered root); rewrote `test_search_auto_scope_does_not_escalate_for_other_project_override` to the new contract.

### 2026-06-11 (session 2)
- Verified explorer scan self-healing end-to-end: daily maintenance auto-failed scans stuck `running` since 2026-04-2x (agent-hub, a-term, sha); the 16:10 bi-hourly sweep rescanned all three with zero manual help. Watch item closed.
- **Generic-word junk suppression** (`_precision_ranking.py`): `search_and_rank_symbols` now tracks which query terms produced candidates; when every user-typed identifier token missed, candidates that matched only generic words are suppressed (`identifier_tokens`/`coverage` kwargs). Before: `st search "resolve_search_timeout handler"` → 20 unrelated "handler" symbols, ~1000 tokens. After: mode=empty + hint naming the missed identifier and withheld count.
- **Checkout guard** (`search_checkout_symbols.py::_without_generic_only_items`): same rule for live checkout search, so stale-index escalation can't merge generic junk as "Current Checkout Overrides".
- **Hints** (`search_hints.py`): empty/symbol-first/text-fallback(union) modes now name the missed identifier; suppressed when checkout overlay answered the query.
- **Stale note honesty** (`commands/search.py::_emit_precision_search_metadata_note`): age-only staleness (index 30m+ old, scan every ~2h — true 75% of the time) no longer claims "refresh did not complete".
- New helper `identifier_shaped_tokens` in `_precision_query.py`.
- Tests: +9 CLI, +8 ranking, +1 collector metadata threading.

### 2026-06-11 (session 1) — commits `9a33d5644`, `213147ef5`
- Fixed scan_states rows stuck in `running` blocking ALL scheduled scans since 2026-04-22 (maintenance now recovers scan_states, not just scan_history).
- Per-term text union when a multi-term phrase text-fallback misses (capped terms dropped as junk).
- Definition-aware stale hint: a `def X`/`class X` line surfacing via text fallback = stale symbol index signal.
- Auto checkout escalation for identifier queries with zero indexed symbols.
- Budget slice reserved for text section in combined mode.

## Open items / ideas

- [ ] Text-fallback hint recommends "Try a specific identifier like `FunctionName` or `function_name`" even when the query already is identifier-shaped (e.g. `st search stale_hit --path backend/cli` → text-fallback with a hit, hint suggests what the user just did). Hint should branch on identifier-shaped queries: acknowledge the term exists only as text (no definition) and suggest `--text` for more matches or a rescan if a definition is expected. Found session 5, deferred (lower impact than the `--file` trap fixed that session).
- [ ] Self-referential contamination: honing artifacts (test strings, this doc) enter the index and text search, making "nonexistent identifier" probes return matches. Use `qqzz_`-prefixed probes for verification.
- [x] ~~`_PRECISION_INDEX_MAX_AGE` (30m) vs sweep cadence (2h) means `stale_hit` is true 75% of the time~~ — fixed 2026-06-11 session 4: threshold now 150m (cadence + slack).
- [ ] **Event-driven symbol refresh** (next highest-impact item): the index only updates on the bi-hourly sweep, so brand-new code is invisible to index searches for up to ~2h. Same-project searches self-heal via checkout escalation, but every escalation is a full live tree parse — repeated cost that a post-publish targeted refresh (e.g. `st commit`/`st done` publish path enqueues a symbol rescan of just the changed files' project) would eliminate. This is in scope for an iteration: design it, build it, verify a fresh commit's symbols are indexed within seconds without escalation.
- [x] ~~`-P <other-project>` searches never escalate to checkout (`checkout_is_project` gate)~~ — fixed 2026-06-11 session 3: escalation now targets the other project's registered root; explicit `--scope checkout` cross-project no longer searches the wrong tree.
- [x] ~~Hint layer can't tell whether checkout escalation already ran and found nothing; hint still suggests `--scope checkout`~~ — fixed 2026-06-11 session 4 via `checkout_escalation_empty` metadata marker.

## Verification recipe (used after every change)

```bash
st check --quick --changed-only          # gates: ruff, types, pytest
st service rebuild summitflow --detach   # deploy; watch journalctl --user -u sf-rebuild-summitflow
# live probes (replace qqzz_* with anything guaranteed absent):
st search "qqzz_unwritten_helper handler"      # expect mode=empty + withheld-junk hint
st search "scan_all_projects qqzz_unwritten_helper"  # expect 8 real symbols + missed-identifier hint
st search "scan_all_projects"                  # expect healthy symbol-first, no hint
st search "project selector"                   # expect NL hits kept (no suppression)
st search --json "<query>"                     # inspect metadata: missed_identifier_terms, suppressed_generic_symbols, stale_hit, refresh_reasons
```

---

## Iteration prompt (paste into a fresh agent session)

```
Run one honing iteration on the `st search` feature in /srv/workspaces/projects/summitflow.

1. Read docs/st-search-honing.md (architecture map, invariants, work log, open items).
2. Run `st pulse --gate`, then AUDIT the live deployed behavior as an agent would use it —
   do not start from the code. Probe at minimum:
   - a healthy identifier search, a CamelCase search, an NL phrase search
   - a nonexistent identifier alone, and one combined with a generic word
     (use fresh qqzz_-prefixed names; prior probe strings are now indexed)
   - a partial miss (one real + one absent identifier)
   - a --path / --file / --text / --scope checkout run
   - a -P <other-project> run
   - check stderr notes and `--json` metadata for honesty (stale_hit, refresh_reasons,
     missed_identifier_terms, suppressed_generic_symbols)
   Also check `scan_states` for projects stuck in running/failed older than the sweep cadence.
3. Judge every output against the invariants in the doc, plus: would an agent reading this
   output be misled, flooded, or left without a next action? Token cost matters —
   junk tokens are the failure mode this effort exists to kill.
4. Pick the highest-impact deficiency. Reproduce it, find the root cause in the layer map,
   fix it properly, add regression tests for both directions. "Properly" includes redesigns:
   if the right fix is structural (new trigger path, schema change, replacing a mechanism),
   do THAT in this iteration — never park it as a "separate design task", "future work",
   or a created-but-unclaimed task. The only valid reasons to leave a deficiency unfixed
   are: a higher-impact one was fixed instead (log it as an open item with evidence), or
   it requires capability this environment genuinely lacks (say exactly what's missing).
5. Verify: st check --quick --changed-only, then st service rebuild summitflow --detach,
   then re-run the live probes — build/tests alone are not evidence.
6. Update docs/st-search-honing.md: append a dated work-log entry, update open items,
   add any new invariant. Then commit everything: st commit -m "..." --push.

Constraints: use st tools (st search/check/db/service), never raw pytest/grep-first flows;
db writes only through app code paths; surgical means no unrelated churn, NOT small-only —
the blast radius should match the problem, however large that is; if an open item in the
doc is stale or already fixed, strike it with evidence instead of re-fixing.
```
