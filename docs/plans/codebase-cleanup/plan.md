# Codebase cleanup plan (agent-hub, summitflow, aico, nightshift, neri)

The single plan for this cleanup. Every decision from the owner conversation is recorded here, and no separate task is filed.
Started 2026-11-02. The evidence is the per-project audits in `audit/`. Where the coordinator re-checked an audit claim live, the result is noted.
Neri rule: line counts are fine. Never review case or hunter details.

Status: **Decided** = the owner said do it. **Proposed** = recommended and checked, awaiting a go-ahead. **Owner call** = needs your judgment. **Exploring** = still being designed.

## Decisions log
- 2026-11-02 **Cut `st claude` and the Agent Hub Claude worker.** Agents ran `st claude task` once in 120 days: on 2026-10-09, to test it after the restore. Every other mention was a `--help` read or text inside another command. Native subagents and Aico sessions do this work now.
- 2026-11-02 **Notes stay, rebuilt properly in Aico.** "Just because I haven't used it doesn't mean I don't need it." Google Keep is your current notes app. See the notes section below. The SummitFlow and agent-hub notes code goes away once Aico notes exist and the 36 existing notes are moved over.

## Cross-project
| # | Item | Status | Size / gain |
|---|---|---|---|
| X1 | Bring the full test check back under its time target: nightshift 154s vs 60s (was 32s), summitflow 121s vs 90s, aico 100s vs 60s, agent-hub 125s vs 116s | Proposed | Check time |
| X2 | Stop tests that assert exact wording or copy, in all five repos (nightshift alone has 314) | Proposed | 3-6k test lines |
| X3 | Run the Rust and Kotlin tests in a check: summitflow host-monitor (54 tests), nightshift desktop and android (61) | Proposed | Closes a gap |
| X4 | Remove notes and notes-ui from summitflow and agent-hub after Aico notes ship | Decided (after N1-N3) | About 6k lines |

## Notes in Aico (Exploring)
Facts:
- **SummitFlow:** 36 notes (19 "prompt", 17 "note"). None created since 2026-07-14. Two were edited on 2026-10-23, both scoped to aico.
- **agent-hub:** its notes page shows agent-hub-scoped notes, and there are 0.
- **Earlier decision:** the 2026-10-10 Tether plan removed notes and prompts from A-Term, which is now Aico (`aico/docs/history/migration-plan.md:60`). Bringing notes back as an Aico feature now reverses that decision on purpose.
- **Aico:** you use it daily as a phone PWA, and it has its own database (`web/server/src/db.ts`). That makes it the natural home for quick capture.
- **Google Keep:** the official API is for Google Workspace (enterprise) accounts only. Consumer Gmail accounts can't use it. Live sync would need gkeepapi, which is unofficial, reverse-engineered and needs a Google master token. Google Takeout can export Keep as JSON for a one-time import.

Proposed shape:
- **N1.** Aico owns notes in its own database: quick capture on the phone, checklists, pin, labels and search.
- **N2.** Agents can read notes and act on them through `tether` (e.g. "send this note to a session"). This is the thing Keep can't do.
- **N3.** One-time import of the 36 SummitFlow notes and a Google Keep Takeout export. No live Keep sync.

Open questions are listed in the chat reply of 2026-11-02 and are recorded here once answered.

## agent-hub
| # | Item | Status | Size |
|---|---|---|---|
| A1 | Delete `backend/scripts/run_claude_orchestrated_worker.py` (1,470 lines) and `backend/tests/scripts/test_run_claude_orchestrated_worker.py` (1,107) | Decided | -2.6k |
| A2 | Delete the unreachable runtime-context frontend files (useRuntimeContext, LibraryPane, RenderedPane, BlockRow...). Keep ContextManager and PolicyModal, which are live. Re-checked live. | Proposed | -2.6k |
| A3 | Remove the duplicate Codex protocol JSON copy in packages/agent-hub-client, and keep only the protocol versions still in use | Proposed | up to -11k (JSON) |
| A4 | Move docs/audits and docs/evaluations out of main. Nothing in the code references them. | Proposed | -50k (docs) |
| A5 | Squash the alembic migrations (278 files, 23k lines) and stop writing model-catalog updates as migrations. Needs a tested backup and an `alembic stamp` on the production database. | Proposed | about -20k |
| A6 | Dead backend modules and one-time backfill scripts, checking each file before removing it | Proposed | about -1.2k |
| A7 | Trim the giant mock-heavy test files and add tests for the subscription collector | Proposed | -3-4k tests |
| A8 | Scope of the memory system: about 36k lines for 483 memories | Owner call | up to -8-10k |

## summitflow
| # | Item | Status | Size |
|---|---|---|---|
| S1 | Remove `st claude` (`backend/cli/commands/claude.py`, `_claude_dispatch.py`, `backend/tests/cli/test_claude.py`), its registration and its help and capability text | Decided | -0.9k |
| S2 | Fix the `test_guard_corpus.py` fixture so it is built once, not once per worker. It starts about 3.9k subprocesses. | Proposed | about -9s check time |
| S3 | Delete `experiments/system-monitor`, which host-monitor superseded | Proposed | -1.8k |
| S4 | Dead backend and frontend files; mockup ratings and comments (0 rows in the database) | Proposed | about -1.4k |
| S5 | Re-baseline the 77 alembic migrations | Proposed | -4.7k |
| S6 | Low-use `st` commands: critique (1 mention in 90 days), ready-all (7), exec-log (12), sync-progress (27). The counts are mentions, so confirm real runs before cutting. | Proposed | about -1.4k |
| S7 | Clean `.git/st/acceptance/isolated-observations`: 6.0G of state that `st` regenerates | Proposed | disk |

## aico
| # | Item | Status | Size |
|---|---|---|---|
| C1 | Delete `tether/src/lifecycle/native-admin.ts` and its test, `qualify-codex-admin.py` and the qualification JSONs. Only docs reference them. Re-checked live. | Proposed | about -1k |
| C2 | Collapse the pane/tab/slot hook chain left over from multi-pane | Proposed | -1-1.5k src, -1.5k tests |
| C3 | Trim tests that read source text or rely on heavy mocks. Test lines grew by 10.3k recently. | Proposed | -3-4k tests |
| C4 | Split `tether/scripts/aico-root-watch.py` (3.2k lines, 86 commits in 90 days) and `lifecycle/engine.ts` (3.3k), and add tests for `engine.ts` and `daemon.ts` | Proposed | 0 net |
| C5 | Three scripts that only docs reference: tether-lifecycle-harness.sh, tether-real-session-smoke.sh, aico-install-context-hooks.sh | Owner call | -0.5k |

## nightshift
| # | Item | Status | Size |
|---|---|---|---|
| T1 | Parallel tests (xdist) and a look at the 13 autouse fixtures. Tests take 48s on their own, but the check takes 110-154s. | Proposed | check time |
| T2 | Remove the file-vs-store comparison (`items/diff.py`, `shadow.run_diff`). It still runs every 15 minutes after the migration finished. | Proposed | -1-1.8k |
| T3 | Fold `decide/` into `rules.py`; the module itself says nothing there learns. Collapse ingest schema versions v1-v4. | Proposed | -0.9-1.5k |
| T4 | Tray vs PWA: make the desktop tray just open the PWA | Owner call | about -3k Rust |
| T5 | Keep or cut ledger and drill | Owner call | -1.2k src, -0.6k tests |

## neri
| # | Item | Status | Size |
|---|---|---|---|
| R1 | Delete `proxy/ops/synthetic` and `backend/scripts/import_index.py`. Nothing references them. Re-checked live. | Proposed | -564 |
| R2 | Remove exit kinds the live config doesn't use. The shipped defaults enable only `direct`. | Owner call (which exits are live?) | -0.4-0.9k |
| R3 | Merge `proxy/ops/live/live_check.py` into the selftest | Proposed | about -300 |
| R4 | Split `st_cli/commands.py` (2.2k lines) and `hunt_cmd.py` (2.0k); add tests for `sandbox_root.py` and `addon.py` | Proposed | 0 net |
