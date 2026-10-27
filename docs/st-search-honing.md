# st search — Honing Tracker & Iteration Prompt

Living doc for testing, auditing and improving `st search` (Precision Code Search). Since 2026-10-27
`st search` is **local-only**: code-intelligence owns it, and it parses the current checkout on every
query. SummitFlow hosts no symbol index any more (Explorer and its `explorer_symbols`/`explorer_entries`
tables were deleted), so there is no sweep, staleness window or post-publish refresh to tune. The
hosted-era work log (sessions 1–6, 2026-06-11) is in git history of this file.

## Architecture map (orient here first)

All paths are in the code-intelligence repository (`/srv/workspaces/projects/code-intelligence`).
SummitFlow only registers the extension (`scripts/lib/tool-registry.json`, namespace `search`) and
dispatches `st search` to that project's `.venv/bin/code-search`.

| Layer | File | Role |
|---|---|---|
| Entrypoint | `code_intelligence/cli/search_main.py` | native command owner wired to the ST SDK runtime |
| CLI command | `code_intelligence/cli/search.py` | scope/path/file/text options, local source resolution |
| Checkout search | `code_intelligence/search/search_checkout_symbols.py`, `search_checkout_text.py`, `search_checkout_paths.py`, `search_checkout_precision.py` | live symbol/text search over the checkout, path rules, adapter to the assembler |
| Assembly | `code_intelligence/precision/current_search.py` | current-source precision search: candidates, ranking, budgeted context |
| Query analysis | `code_intelligence/precision/query.py` | term extraction, NL/import detection, identifier-shape detection |
| Ranking | `code_intelligence/precision/ranking.py` | symbol match ranking, generic-only junk suppression |
| Output / hints / budget | `code_intelligence/search/search_output.py`, `search_hints.py`, `search_budget.py` | compact `SEARCH:` lines, decision-grade hints, prompt budget |

Key tests (code-intelligence): `tests/test_search_cli.py`, `test_current_search.py`,
`test_precision_ranking.py`, `test_precision_query.py`, `test_search_correctness.py`; SummitFlow keeps only
the wrapper/metadata tests `backend/tests/cli/test_search.py` and
`backend/tests/services/test_search_extension_metadata.py`.

## Invariants (do not regress)

1. **No confident junk.** A query whose user-typed identifier-shaped tokens ALL miss must never return
   symbols that matched only generic words — suppress and say so in the hint.
2. **NL queries keep weak-coverage hits.** Suppression applies only to user-typed identifier tokens, never
   to NL-synthesized CamelCase/snake variants ("project selector" keeps `ProjectSelector`-ish hits).
3. **Symbol hits survive weak coverage.** Weak multi-word coverage appends corrective text matches; it never
   discards symbol hits.
4. **Results are current source.** Every returned symbol comes from the files as they are now; no output may
   imply an index age or suggest a rescan.
5. **Compact output stays compact.** Default output is the `SEARCH:` line + hint + budgeted context.
6. **Hints are decision-grade.** Every empty/fallback mode names the most specific reshaping action and
   never recommends retrying verbatim.

## Open items / ideas

- [ ] **Retrieval confidence score**: 0–1 score in metadata and on the SEARCH line (`|conf=0.87`) from the
  top1/top2 score gap, top1 strength and identity-match presence, so agents can gate "trust or reshape".
- [ ] **Empty-result query suggestions**: on mode=empty with no missed-identifier diagnosis, suggest the
  nearest symbol names found in the checkout ("did you mean `write_index_file`?").
- [ ] **Batch queries**: accept several queries per invocation and return grouped compact sections.
- [ ] **BM25 over name/signature**: only with a probe corpus that shows ranking misses; build the probes first.
- [ ] **Import graph / references**: check Graphify first — if its graph stores imports, expose
  importer/reference queries from there instead of duplicating.
- [ ] **Secret-file exclusion audit**: verify live text/symbol search never reads `.env*` or key material.
- [ ] **Self-referential contamination**: honing artifacts (this doc, test strings) match "nonexistent
  identifier" probes; use `qqzz_`-prefixed probes.

## Verification recipe

```bash
st check --quick --changed-only                 # in code-intelligence
st search "qqzz_unwritten_helper handler"       # expect mode=empty + withheld-junk hint
st search "write_index_file qqzz_unwritten"     # expect real symbols + missed-identifier hint
st search "write_index_file"                    # expect healthy symbol-first, no hint
st search "project selector"                    # expect NL hits kept (no suppression)
st search --json "<query>"                      # inspect metadata: missed identifiers, suppressed symbols
```

---

## Iteration prompt (paste into a fresh agent session)

```
Run one honing iteration on `st search` (owned by /srv/workspaces/projects/code-intelligence;
SummitFlow only dispatches to it).

1. Read /srv/workspaces/projects/summitflow/docs/st-search-honing.md (map, invariants, open items).
2. AUDIT live behavior as an agent would use it — do not start from the code. Probe at minimum:
   a healthy identifier, a CamelCase name, an NL phrase, a nonexistent identifier alone and with a
   generic word (fresh qqzz_ names), a partial miss, --path / --file / --text runs, and -P <other-project>.
   Check --json metadata for honesty.
3. Judge every output against the invariants: would an agent be misled, flooded, or left without a next
   action? Junk tokens are the failure mode this effort exists to kill.
4. Fix the highest-impact deficiency at its root cause in code-intelligence, with regression tests for both
   directions. Structural fixes belong in this iteration, not a parked follow-up.
5. Verify with st check in code-intelligence, then re-run the live probes once the wheel is vendored.
6. Update this doc: open items, any new invariant. Commit through st.
```
