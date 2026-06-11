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

- [ ] Self-referential contamination: honing artifacts (test strings, this doc) enter the index and text search, making "nonexistent identifier" probes return matches. Use `qqzz_`-prefixed probes for verification.
- [ ] `_PRECISION_INDEX_MAX_AGE` (30m) vs sweep cadence (2h) means `stale_hit` is true 75% of the time; consider event-driven (post-commit) symbol refresh or aligning the threshold with the cadence.
- [ ] `-P <other-project>` searches never escalate to checkout (`checkout_is_project` gate) — correct, but means stale *other-project* indexes have no self-heal path beyond the sweep.
- [ ] Hint layer can't tell whether checkout escalation already ran and found nothing; hint still suggests `--scope checkout`. Harmless but slightly redundant.

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
   fix it minimally (no speculative abstractions), add regression tests for both directions.
5. Verify: st check --quick --changed-only, then st service rebuild summitflow --detach,
   then re-run the live probes — build/tests alone are not evidence.
6. Update docs/st-search-honing.md: append a dated work-log entry, update open items,
   add any new invariant. Then commit everything: st commit -m "..." --push.

Constraints: use st tools (st search/check/db/service), never raw pytest/grep-first flows;
db writes only through app code paths; keep changes surgical; if an open item in the doc
is stale or already fixed, strike it with evidence instead of re-fixing.
```
