# SummitFlow code-size and test audit (read-only, 2026-11-02)

Repo: /srv/workspaces/projects/summitflow, main @ d1bf17c86. Nothing edited; the uncommitted edits were left alone.
Method notes: LOC = tracked code files via `python3 -I <SCRATCH>/loc.py . 2|3` (src 177,193 / test 91,709 / ratio 0.52, matches the baseline). `st check budget` reports src=150k / tests=76k because it skips migrations, fixtures, docker and similar; I use the loc.py numbers below unless noted. "c90" = commits touching the path in 90 days: `git log --since=90.days --oneline -- <path> | wc -l`. The repo has 1236 commits in that window. Only 50 have a subject starting with "fix" (subjects are mostly descriptive sentences), so I also use a broad word match (`--grep='\b(fix|fixes|fixed|repair|regression)\b' -E -i`, 299 commits) as a rough fix-churn proxy. Mark: [I] = inference, not directly measured.

## 1. Biggest areas

| Area (src / test LOC) | c90 | last touch | fix-ish commits (broad) | Live callers |
|---|---|---|---|---|
| backend/cli/commands 26,484 / tests/cli 39,828 (shared with lib) | 412 | 11-02 | 105 | the `st` entry point (backend/pyproject.toml `st = "cli.main:app"`), every agent |
| backend/cli/lib 19,541 / (same tests) | 302 | 11-02 | 94 | same |
| backend/app/api 13,862 / tests/api 10,197 | 138 | 10-31 | 36 | 22 routers in app/main.py; frontend/lib/api |
| backend/app/services 12,601 / tests/services 9,707 | 128 | 10-31 | 45 | api, tasks, cli |
| backend/app/storage 11,441 / tests/storage 4,365 | 59 | 10-30 | 19 | api, tasks |
| backend/app/tasks 9,431 / tests/tasks 6,226 | 173 | 11-01 | 67 | Hatchet worker (backups, retention, publication) |
| frontend/components/tasks 9,160 / 735 | 15 | 10-30 | - | Next app |
| frontend/components/runtime 5,747 / 1,395 | 36 | 10-31 | - | runtime page |
| host-monitor/src (Rust) 4,884 / 54 inline #[test] | 19 | 10-31 | 3 | systemd collector, writes monitor.sqlite3 |
| backend/alembic/versions 4,754 (77 files) + docker/compose/summitflow-schema.sql 3,899 | 21 | 11-01 | 0 | schema |
| frontend/components/design 4,635 / 169 | 6 | 10-29 | 0 | Design page (mockups) |
| scripts/ + scripts/lib 4,457 (bash/py hooks, 0 direct tests; covered via backend/tests/scripts 1,470) | 311 | 11-02 | 74 | hooks, installers |
| docker/compose 3,952 (3,899 is the schema snapshot) | 11 | 10-27 | 11 | compose stack |
| backend/app/utils 3,486 / tests/unit 4,898 | 44 | 10-31 | 9 | everywhere |
| backend/monitor_* (observe 1,473, reader 1,187, extended 474, control 143, standalone 310) = 3,587 / tests 1,745 | 17 | 09-27 | 0 | `st monitor` (stdlib launcher), app/api/monitor.py |
| packages/notes-ui 2,255 (+ frontend/lib notes tests 386) | 6 | 10-30 | 2 | frontend + agent-hub (own copy) |
| packages/st-sdk 1,699 | 17 | 10-31 | 0 | neri, agent-hub (wheels) |
| experiments/system-monitor 1,633 / 157 | 5 | 09-29 | - | none |

Commands: `python3 -I loc.py . 3`; `git log --since=90.days --oneline -- <path> | wc -l`; `git log -1 --format=%cs -- <path>`.

### st CLI broken down by family (src = backend/cli files matching the family name, test = backend/tests/cli files matching)
Script: grouped `git ls-files backend/cli backend/tests/cli` by filename. Family, src LOC / test LOC, c90.
- service (service_ops 1,954, service_release, heal, docker, setup): 4,353 / 4,162, c90 101
- check + acceptance + ci_parity + budget + native fixture: 8,141 / 5,111, c90 142 (hottest area in the repo)
- coord (coord, coord_deliver, lineage, remote, disrupt, memory): 3,341 / 3,554, c90 60 (80 incl. scripts)
- tasks/claim/subtask/_client_*: 4,499 / ~900, c90 29
- sessions (incl. fleet, handshake, native delivery): 3,734 / 3,131, c90 68
- done/abandon (done_task_acceptance 561, done_task 620): 2,684 / 2,433, c90 56
- snapshots, autosnapshot, quick_snapshots, checkpoint: 4,108 / 1,865, c90 23
- cleanup + cleanroom: 2,857 / 1,564, c90 15
- vm + proxmox + vm_clone + vm_forward: 1,763 / 1,650, c90 36
- monitor/logs/runtime/exec_monitor: 2,131 / 332, c90 17
- tools (manifest/cost/run): 1,542 / 2,257, c90 22
- vcs/commit/git: 1,427 / 1,588, c90 36
- backup CLI 548, leases 888 (tests 1,134), pulse 925 (tests 1,179), db 660, agent/claude/deep_lane 1,292 (tests 1,037)

### Whole-feature stacks (all layers, grep by name across api/cli/ui/tests; src / test, c90)
- Backups: 11,373 / 5,619, c90 117, last 11-01. Biggest feature stack in the repo and still churning (btrbk, Drive restic, Proxmox, offsite, verify, safety, keys, freshness; recent commits are edge cases such as offline guests, retention floors, UTC parsing).
- Host monitor (host-monitor + monitor_* + API + CLI + UI): 14,636 / 4,392, c90 43.
- Tasks domain (api/storage/tasks UI/CLI): 18,738 / ~7,500 [I, test files only matched by name], c90 59.
- Snapshots/recovery: 5,141 / 2,480, c90 28. VM/Proxmox: 2,630 / 2,144, c90 40. Docker API+UI: 6,223 / 1,452, c90 37.
- Command guard/publication: 3,611 / 3,041, c90 52. Retention/cleanup/scratch: 5,725 / 3,031, c90 42.
- Mockups/design: 6,205 / 838, c90 8. Notes: 3,275 / 586, c90 7. DB workbench: 1,257 / 263, c90 7.

### Not worth it (ranked by LOC removable with confidence)

1. experiments/system-monitor, 1,790 LOC (1,633 src + 157 test), 20 tracked files (go/, rust/, python/ collectors, profile-managed.py). Superseded: the Rust prototype became host-monitor/ (its README lists the same /proc sources), and the decision is written in docs/research/system-monitor/. No importers: `rg -n "experiments/" backend scripts docker .github` is empty; only two docs link it; not in any gate stage. Do: delete the directory, keep docs/research as the record.
2. Never-imported modules, about 475 LOC. Found by name search across backend/app, backend/cli (script in this audit) and confirmed with `rg -w <name> backend scripts docker docs .github` returning nothing: cli/lib/project_config.py 209 (last touched 04-18), app/utils/smb_commands.py 71, cli/commands/done_memory.py 54 (03-22), done_qa.py 49 (04-23), app/tasks/backup_codex_policy.py 38, cli/_project_client.py 22, app/services/git_service.py 16, cli/commands/prompt_api.py 15. Do: delete. (Name-based, so one dynamic-import surprise is possible; the gate will show it.)
3. Orphaned frontend files, about 450 LOC, zero importers (`rg -w` per name): components/tasks/hooks/useTimelineHistory.ts 112, useVoiceRecording.ts 110 (+ its test), components/tasks/TimelineChatInput.tsx 96, components/design/DesignFilters.tsx 85, components/tasks/TimelineHeader.tsx 53. Do: delete.
4. packages/notes-ui duplicate, 2,255 LOC here vs 1,906 in /srv/workspaces/projects/agent-hub/packages/notes-ui, same package name `@summitflow/notes-ui`. Agent Hub consumes its own copy (agent-hub/frontend/package.json `workspace:*`), last touched 2026-06-05 while this copy had 6 commits in 90 days. `diff -r` shows 267 changed lines plus pasteFormat.ts only here, so the two have already drifted. Do: pick one source of truth (publish this one as a tgz; docker/workspace-packages already carries summitflow-notes-ui-0.1.0.tgz) and drop the other: about 1.9k LOC and a drift class.
5. Mockup features with zero use: `mockup_ratings` has 0 rows, `mockup_comments` 0 rows, `mockup_votes` 3 (st db query, read-only), while mockups themselves are in use (137 rows, newest 10-31, 9 in the last 60 days). StarRating.tsx 87 + ArtifactComments.tsx 217 + rating/comment endpoints in app/api/mockups_crud.py (~100) + tables. Do: shrink (remove ratings and comments, keep mockups). About 400-500 LOC.
6. Alembic history: 77 migrations / 4,754 LOC, 25 named drop/retire/remove (Explorer, design standards, dependency review, autonomous-pipeline keys). A bootstrap snapshot already exists (docker/compose/summitflow-schema.sql, `verify_bootstrap_schema.py` uses it as the base revision). Do: re-baseline the snapshot at head and delete the old revisions: about 4.7k LOC, and shorter per-worker DB bootstrap (conftest.py:192 runs `alembic upgrade head` in each xdist worker DB; time not measured). Needs care because the production DB's alembic_version must map to the new base.
7. Backups, 17k LOC at 117 commits in 90 days: not deletable (owner-critical), but "tiny new rules per week" pattern. Do: stop adding sources and kinds (guest_unit, offline_since etc.), and merge the three alerting/freshness paths (backup_alerts.py, freshness receipt, Nightshift sources.json) when it settles. Savings unknown; a freeze costs nothing.
8. Host-monitor Python mirror (backend/monitor_reader 1,177 + observe 1,473 + control 143 + standalone 310) alongside the Rust collector: not duplicate (reader reads the sqlite the Rust side writes; observe does live logs/connections/inventory), c90 17 and zero fix commits. Overlap with Nightshift exists but is partial [I]: Nightshift has its own /proc pressure and journal checks (nightshift/src/nightshift/checks/workstation.py, memctl.py) for alerting; this stack is for `st monitor` troubleshooting. monitor_extended (benchmark 87, disk 195, export 185 = 474 LOC, c90 2) is the least-used slice [I]; check `st` usage telemetry before cutting.
9. graphify: not a size problem. graphify-out/ is gitignored (`git check-ignore -v graphify-out` hits .gitignore:89; `git ls-files graphify-out` = 0) and holds 307M on disk (284M cache) that is regenerable. Code in the repo is a thin wrapper, about 1.2k LOC with tests (api/graphify.py 187, tasks 76, UI page 327, client 101), live (a project page, a scheduled task, `st graph`), last api touch 04-30. Keep.
10. Others checked and fine as-is: packages/st-sdk (wheels consumed by neri and agent-hub, `rg summitflow-st-sdk` in their pyproject.toml), docker/workspace-packages (6 binary wheels/tgz, needed for builds), db_workbench (1.2k, c90 7, live route + UI), host-monitor Rust (live, see section 2).

## 2. Are the tests appropriate?

### Gate and budget
`st check budget`: `state=over src=150k tests=76k ratio=0.51/0.80 gate=121s/90s gate_s_per_kloc=0.81 slow>3s=33 slowest10=125s`. The ratio is fine (ceiling 0.8). Only gate duration is over.
Stages (.st-check.toml, newest receipt in .git/st/acceptance): fresh-schema 4s, python 102s (6,110 tests, pytest xdist `-n min(8, cpu/2)`, backend/scripts/native_check_fixture.py:32), frontend 21s (391 tests whose total test time is 6s; the rest is vitest startup with `--cache=false`). Python is ~80% of the gate.
Python JUnit (retained report 8ad2bbf8...): wall 94.7s, summed test time 516 CPU-s. tests/cli takes 333 CPU-s (65%) for 3,219 tests; tests/scripts takes 108 CPU-s (21%) for 166 tests; everything else is ~75 CPU-s.

### What is driving gate time
a) test_guard_corpus (backend/tests/scripts/test_guard_corpus.py, 148 lines + 327 KB fixture). A module-scoped fixture (`actual`, line 71-73) spawns 4 shell/python subprocesses for each of 979 commands (3,916 launches, 8 threads). The four tests that use it each show 22-26s in the newest run (26.3, 23.8, 23.4, 21.7 = 95 CPU-s, 18% of all test time). In the older retained run (.dev-tools/native-python.xml, 6,027 tests) the module cost 15.4s total, one test paid and the others were ~0. [I] With `--dist worksteal` the four tests landed on different workers and each rebuilt the fixture. It also floods the machine with 32 concurrent spawns.
b) Contention inflates unrelated tests. test_sessions_fleet "send" tests take 0.012-0.02s in the isolated fleet stage (.dev-tools/native-fleet.xml) but 4.5-6.0s in the full python stage; 19 of the 33 ">3s" tests are in tests.cli.test_coord_deliver (11, median test 0.95s for 112 tests) and test_sessions_fleet (8). They are mocked in-process tests, so they are victims, not causes [I]. Real heavy ones: 4 guard corpus (95s) and 9 in test_done_isolated_acceptance (37s; 42 tests, 56 CPU-s; real git worktrees at 2.5-4.9s each).
c) The headline jump is mostly noise plus (a). Python stage on the same plan ranged 82-102s across the two newest runs; before 11-01 it was 62-80s. Test count barely moved (6,008 on 10-31 to 6,110 now, +102 tests) while guard-corpus time went 15s to 95 CPU-s. The budget median uses only receipts with the newest plan fingerprint (limit 5), so right after a plan change it is a median of 2-3 noisy samples (quality_budget.py:`_full_receipts`).
d) Test LOC +1,907 recently is real growth but not the cause: `slow_tests +16` is mostly (b).

### Per-area verdicts (test LOC : src LOC)
- backend/cli (39.8k : 49.2k = 0.81, heaviest tests per line in the repo): too much in places, mocked, not wrong in kind. The st CLI is the product, changes daily (569 commits) and has the most fix-ish commits (about 200), so heavy coverage is defensible. Trim candidates below.
- backend/app/api 0.74, services 0.77, tasks 0.66: right, with mock-heavy exceptions below.
- backend/app/storage 0.38 with 11.4k src and c90 59: thin but low fix churn; right.
- backend/app/utils + tests/unit: 4.9k tests for 3.5k src (unit/ also hosts test_cli_commands.py 1,672 lines for the tasks CLI); over for utils, fine for CLI.
- frontend 0.22 (9.5k : 43.4k; 389 tests, 6s of test time, no snapshots anywhere: `rg toMatchSnapshot` is empty): right, arguably thin for tasks/design UI (components/tasks 9.2k : 0.7k, design 4.6k : 0.17k) but both have low churn (c90 15 and 6, zero fix commits), so under-testing is not hurting.
- host-monitor (Rust, 4.9k, 54 inline `#[test]`: provider 16, store 22, main 16): UNDER-tested in practice. `.st-check.toml` and ci.yml have no cargo stage (`grep cargo` returns nothing), so these tests are not in the gate. It owns the only writer of monitor.sqlite3, so a regression there is silent.
- monitor_* Python: 1.7k tests : 3.6k src, c90 17, no fixes. Right.
- docker api/ui: 6.2k src : 1.45k test, c90 37. Mildly thin [I]; one fix commit in 90 days, so leave.
- scripts/ (bash hooks, installers; c90 311, 74 fix-ish commits): the highest fix rate in the repo (24%) with only 1,470 lines of tests in backend/tests/scripts, one of which is the 979-command guard corpus. Hooks/installers are the weakest per-line coverage, but the guard corpus covers the dangerous part.
- check/gate stack (8.1k : 5.1k, c90 142, 8 explicit fix commits): right; keep.

### Over-testing evidence (file:line)
1. backend/tests/scripts/test_guard_corpus.py:71-108: a recorded "decisions are unchanged" snapshot of 979 commands x 4 execution paths, rerun on every gate (95 CPU-s), re-recorded by hand whenever a rule changes (docstring lines 1-18). Equivalent protection from one test and one execution path per command family, or a corpus run only when scripts/lib or app/services/command_guard* changes.
2. backend/tests/cli/test_check_mandate_wording.py:14-20 asserts the exact manifest sentence `"iterate on a failing check; st commit already runs the quick check"`; backend/tests/cli/test_usage_terseness.py:18-21 ratchets line caps and `TOTAL_CAP = 23_500` on agent-facing copy (60 lines); test_startup_mandate_text.py (45) and test_usage_manifest.py (582) are in the same family. This is copy testing: any wording edit needs a test edit. Keep one structural manifest test, drop the exact-string ones.
3. backend/tests/services/test_project_pulse.py: 920 lines (16 test functions, 45 mock/patch operations) for a 180-line module (app/services/project_pulse.py). Ratio 5:1, AsyncMock-driven.
4. backend/tests/cli/test_operator_tools_cli.py:42-72 and :75-100: patch private helpers (`cli.commands.db._run_psql`, `_alembic`, `_detect_project`, `setup._preview`, `setup._run`) and assert only that they were or were not called, plus argv lists. 157 mock operations in 65 tests. Same pattern: test_service_lifecycle.py (178 mocks, 104 tests, 1,847 lines vs 1,954 src for service_ops.py), test_coord_deliver.py (34 private-name references, 81 mocks).
5. backend/tests/cli/test_done_isolated_acceptance.py:1030, :1103: parametrized variants (`[mode]/[content]`, `[advance]/[rewrite]`) each pay a full isolated-worktree setup at 2.5-4.8s; 9 of them are in the >3s list. Fold variants into one scenario per behavior.
6. backend/tests/unit/test_heavy_work.py: 860 lines for 613-line app/utils/heavy_work.py, 37 tests, ~10 CPU-s.
Overall mock density in backend/tests: 4,223 mock/patch operations across 3,849 test functions (~1.1 per test); 681 references to underscore-private names. 3,849 functions become 6,110 cases via parametrization.

### Under-testing evidence
- host-monitor Rust tests not in the gate (above).
- scripts/ hotspot (74 fix-ish commits of 311); only the hooks have the guard corpus.
- Nothing else: high-churn areas (cli check, service, coord, sessions) all have ratio 0.8-1.1.

### Overall verdict
Test volume is about right in size (0.52 overall, within the 0.8 ceiling) but badly distributed in cost: 5 files burn 40% of CPU time, and the CLI suites over-assert on mocks and copy. The gate overrun is mainly one structural problem (guard corpus x4 + contention) rather than too many tests.

## 3. Recommendations (ranked by payoff)

1. Fix the guard corpus fixture (small). Make the four tests share one run (single test, one `xdist_group`/loadgroup, or cache results in a tmp file under a lock) and drop the redundant `hook_unfiltered` or `fallback` pass per command unless a rule changed. Removes about 70 of 516 CPU-s (roughly 9 s of wall at 8 workers) and the 32-process storm that makes ~19 mocked tests look slow (sessions_fleet, coord_deliver). Likely brings the gate to about 85-95s [I]. Single largest item.
2. Delete dead code (small): experiments/system-monitor 1,790 LOC, 8 backend modules about 475 LOC, 5 frontend files about 450 LOC (+ useVoiceRecording test). Total about 2,700 LOC, 0 gate-time risk.
3. Add `cargo test` for host-monitor as a conditional gate stage (`inputs = ["host-monitor"]`, like the frontend stage's inputs) (small). Adds time only when the Rust code changes; closes the one real coverage hole.
4. Trim copy/mock tests (medium): the mandate/terseness/manifest-wording tests, test_project_pulse.py down to behavior tests, private-helper patching in test_operator_tools_cli.py and test_service_lifecycle.py, merge isolated-acceptance variants. Roughly 3-5k test LOC and 10-25 CPU-s [I].
5. Unify packages/notes-ui with agent-hub's copy (medium): about 1.9k duplicate LOC, ends drift.
6. Re-baseline alembic at head (medium; needs owner-visible care for the production DB): about 4.7k LOC and a faster per-worker DB bootstrap.
7. Remove mockup ratings and comments (small-medium): about 400-500 LOC across api, table and UI; zero rows in use.
8. Make `st check budget` gate median robust (small): it takes the median of up to 5 receipts after a plan change, so 2-3 noisy samples decide "over". Use at least 5 samples or the python-stage minimum; avoid chasing noise.
9. Freeze backup scope (no code): 117 commits in 90 days on 17k LOC; each new source kind adds tests and alerts. Revisit consolidation after a quiet month.

## Side note (outside the project code)
`.git/st` is 7.4G (st/acceptance/isolated-observations 6.0G, st/native-stages 1.3G, 1,297 acceptance receipts), against 283M of git objects. It is regenerable ST state; retention there belongs to the st tooling owner (`du -xs .git/st/*`).
