# Redundancy detector — Phase 0 metrics report

Phase 0 of the redundancy plan: *prove the detector empirically before wiring it
into the live refactor-task pipeline.* This is the data behind the go/no-go.

## What the detector is
A pure, offline, lexical near-duplicate detector over the `explorer_symbols`
index (`app/services/explorer/redundancy.py`). Precision-first: it would rather
miss a duplicate than flag a non-duplicate, because a false positive becomes a
misinformed refactor task (the failure mode that got `schema_tasks` /
`architecture_tasks` disabled). Scope = **top-level public surface**
(functions, classes, constants, exported types/components) — not class members.

## Labeled-corpus result (`test_redundancy.py`, CI-locked)
- **Precision: 1.000 (0 false positives)** on a hard-negative-rich corpus.
- **Recall (lexically reachable): 1.000.** Pure synonyms (e.g. `humanize_seconds`
  vs `prettyDuration`) are an accepted miss — unreachable without embeddings.

Hard-negative classes the corpus proves are NOT flagged: singular/plural
(`get_user`/`get_users`), specialization (`create_task`/`create_refactor_task`),
shared-verb/different-object (`format_date`/`parse_date`), same-name/different-kind,
common method names (`to_dict`), cross-layer delegation (`create_rule` api↔storage),
3-layer delegation (`get_stats`), React handlers (`handleKeyDown`), script
boilerplate (`parse_args`), vendored/test/private symbols. Positives it still
catches: verbatim copies, version-suffix copies (`_v2`/`_new`), same-layer
duplicates, and copy-pasted components (`CollapsibleSection`).

## Live dry run (`redundancy_dryrun.py`, summitflow index, task creation OFF)
| Iteration | Clusters flagged | Change |
|-----------|------------------|--------|
| Baseline (name-identity only) | 123 | — |
| + exclude methods, reject cross-layer delegation | 91 | −32 |
| + exclude React handlers / script boilerplate | 79 | −12 |

Final: **79 candidate clusters** (69 two-member, 9 three-member; 45 backend, 29
frontend, 4 scripts). Manual review confirms the large majority are genuine
duplicates — e.g. `is_subtask_id` ×3, `is_valid_git_repo`, the `subtasks.py` /
`db_workbench.py` god-module splits, the parallel `backup-sources.ts`/`backups.ts`
API surface (8 functions), duplicated constants (`HTTP_TIMEOUT`,
`CONFIDENCE_THRESHOLD`), and copy-pasted components (`StatPill` ×3,
`CollapsibleSection`).

### FP classes eliminated during honing
1. **Cross-layer delegation** (~23) — api↔services↔storage same-name = layered call.
2. **Interface/override methods** (~5+) — `get_health_status` across scanner subtypes.
3. **Frontend handlers / script boilerplate** (~12) — `handleX`/`onX`, `parse_args`.

### Residual (soft, low-harm) after cross-project honing
Resolved during honing: API-client mirrors (`cli/_client_*` and client SDKs),
React `Props`/`State`, Next.js route verbs, root-level migrations. What remains:
- **Framework-convention types** (~handful): Next.js `ErrorProps`/layout components,
  local `ViewMode`/`SortDirection` aliases, large N-way type re-declarations
  (e.g. a-term `XtermATerm` ×11) — dropped anyway by the Phase-1 2–3-member cap.
- **Reordered constants** (~2): `STATUS_SUCCESS`/`SUCCESS_STATUS` — arguably real.
- **Domain-ambiguous game/draw utilities** (monkey-fight) — `darken`/`getFramePose`;
  some genuine copies, some intentional per-entity. Left for human/assess review.

All residual are 2–3 member, low harm, and dismissed quickly by review. They are
the backstop's job: Phase 1 keeps the existing `assess_refactor_target` promotion
gate + 2–3-member cap + stale-task retirement, so the detector only needs to
produce mostly-genuine *candidates*, not perfect verdicts.

## Cross-project validation (all indexed projects)
Ran the dry run against every project to confirm no FP class was missed and the
shape generalizes beyond summitflow:

| Project | Clusters | Note |
|---|---|---|
| summitflow | 72 | baseline |
| agent-hub | 55 | client-SDK model mirrors excluded |
| portfolio-ai | 28 | React `Props` / Next.js route verbs excluded |
| a-term | 4 | root-level alembic migrations excluded (was 13) |
| monkey-fight | 14 | genuine duplicated game utilities (correct) |
| sha / vantage / aico | 0 / 1 / 0 | clean |

Cross-project testing surfaced and fixed three more convention FP classes, all as
small additions to existing mechanisms (no new subsystems):
- **Root-level Alembic migrations** (a-term) — `upgrade`/`downgrade` + migration
  constants. `is_first_party` now matches exclusions on path-segment boundaries,
  so `alembic/versions/` is caught at repo root *and* under `backend/` (and a real
  dir like `redistribute/` is no longer mis-excluded by the `dist/` substring).
- **Published client-SDK mirrors** (agent-hub) — `packages/<name>-client/` model
  packages re-declare server wire-types by design; the `_client`/`-client/` mirror
  rule now covers them.
- **Framework conventions** (portfolio-ai) — React `type Props`/`State` and Next.js
  route-handler verbs (`GET`/`POST`/...) are excluded as noise.

## Bug found & fixed
`is_first_party` used `lstrip("./")`, which stripped the leading dot off
`.dev-tools/...` and defeated vendored-code exclusion. Fixed to strip only a
leading `./`; covered by `test_vendored_excluded`.

## Go / no-go
The lexical bar is met (precision 1.0 on the corpus; every high-volume FP class
found on real data — across all six non-trivial projects — is eliminated). The
embeddings escape hatch is **not** triggered — the only misses are pure synonyms,
which are out of scope. The detector is honed; the remaining decision is purely
the Phase-1 go-ahead (wire the proven detector into the existing gated refactor
pipeline), not further detector tuning.

---

# Phase 2 — Precision honing via a BLIND multi-project subagent audit

After global rollout, hand-working the top clusters suggested the corpus's 1.000
precision was *corpus-bound*, not live (a schema-class FP, agent-hub
`ClientListResponse`, scored the detector's **max** 1.000). So we measured live
precision properly: dispatch subagents that judge each flagged cluster
genuine-vs-FP **from the source alone, never told the detector flagged it or its
score**, then tighten and re-measure. Precision-first remains the contract.

## Blind-audit method
Per project: run `redundancy_dryrun`, emit a score-free manifest of clusters
(name + member paths), partition into disjoint batches, and give each batch to a
`general-purpose` subagent framed as a neutral duplication audit (DUPLICATE /
DISTINCT / UNSURE per cluster, with a one-line reason from reading the real
files). Precision = DUPLICATE / (DUPLICATE + DISTINCT).

## Live FP taxonomy found (and what the index can/can't see)
The symbol index stores `signature` **declaration-only** (`class X(BaseModel)` —
fields are NOT captured; function signatures DO carry the full param list) plus a
`summary` (first docstring line) and `keywords`. There is **no symbol-level
import/reference table**. That bounds what is fixable lexically:

1. **Facade/impl with different parameter arity** (`get_effective_rules`,
   `validate_against_rules`, `run_scan_with_tracking`) — fixable: the param list
   IS in the signature. → arity gate.
2. **Same-name schema/model classes, different fields** (`ClientListResponse`
   1.000, `HealthResponse`, `VariantMetrics`) — fields invisible; the only shared
   text restates the name + framework boilerplate. → class domain-corroboration
   gate (require a concrete shared domain token after stripping name/stem/whole-
   identifier, framework vocab, and generic descriptors).
3. **Same-package hub/spoke facade/re-export** (`subtasks.py` ↔ `subtasks_crud.py`,
   `db_workbench.py` ↔ `db_workbench_targets.py`, `context_injector.py` ↔
   `context_injector_ops.py`) — a pass-through facade preserves arity, so the
   arity gate misses it; cross-layer misses it (same layer/tree). → sibling-module
   gate (same dir + spoke stem = `hub_<domain>`), **callable-only** (a CONSTANT or
   TYPE re-declared in a sibling is genuine duplication, not delegation; a
   version suffix `_v2`/`_new` is a copy, not a split — both exempt).

## Three new gates (all in `redundancy.py`, corpus-locked, CI-guarded)
- `reject_signature_arity_mismatch` — Python-only; fires only when both arities
  parse confidently. Also caught 5 unnamed facade/impl pairs the cross-layer rule
  missed (`acknowledge_no_citations`, `log_citations`, a Typer CLI wrapper, …).
- `class` kind now requires `min_domain_corroboration=1` via `_domain_corroboration`
  (strips name tokens + crude stems + whole identifier + conversion/schema/generic
  vocab). Kills all four live schema-class FPs; keeps real class copies that share
  a concrete word (`RetryPolicy`→`backoff`, `WebhookPayload`→`hmac`).
- `reject_sibling_module_delegation` — callable-only, version-suffix-exempt.

## Result (blind precision, surviving clusters)
| Project | Clusters before → after | Blind precision after |
|---|---|---|
| summitflow | 72 → 50 (−31%) | 47% |
| agent-hub | 55 → 50 | 46% |
| portfolio-ai | 28 → 28 (no FP class present) | — |

Corpus: precision still 1.000 / lexical recall 1.000, now over **10 gold
positives** (incl. a real schema-class copy, an arity-preserving rename, a
sibling-module constant) and the **12 new live hard negatives** above.

## Residual FPs — the binding limitation
The remaining "DISTINCT" verdicts are dominated by **frontend TS `type`/component
field-set divergence** (same name, different fields/props — `ExplorerStats`,
`SortField`, `Agent`, `ClientResponse` projections). This is the *same* root cause
as schema classes — invisible field sets — but TS types carry **no docstring**, so
there is no keyword/summary proxy to lean on; forcing domain corroboration on
`type` would reject genuine TS-type copies too (`MaintenanceRun`, `ModelScores`,
`Tier`). It is therefore **left to the load-bearing merge-or-reject agent gate**,
not auto-suppressed. A handful more are **stale-index entries** (symbols whose file
no longer exists — `BranchInfo`, `STATUS_BLOCKED`); these clear on the next scan,
not a detector concern.

**Recommended next lever (out of scope here — needs an extractor + schema change):**
capture class/interface **member/field lists** in the index. That is the only way
to lift precision on FP classes 2 and the TS-type residual without guessing from
names. Until then, the merge gate stays load-bearing and the 2–3-member cap +
`assess_refactor_target` promotion remain the backstop by design.
