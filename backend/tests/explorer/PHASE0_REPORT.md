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
