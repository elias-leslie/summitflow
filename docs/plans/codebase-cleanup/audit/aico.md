# Audit: aico (/srv/workspaces/projects/aico) — 2026-11-02, read-only

Method note: LOC from `python3 -I <SCRATCH>/loc.py <repo> 3|4` (src 76.7k, test 52.8k, ratio 0.69; confirmed). `st check budget` counts differently (src 70k, tests 48k) but agrees on ratio 0.69. 90-day commit counts: `git log --since=90.days --format=%h -- <path> | wc -l`. "fix" = first-line match on `fix|bug|regress` (this repo rarely uses a `fix:` prefix; `--grep='^fix'` gives near-zero everywhere, so I used the looser match; it is an inference-grade signal).
Repo: 995 commits total, 834 in 90 days (very high velocity). Tests: 1,978 vitest cases in 207 files + 315 pytest cases.

## 1. Biggest areas

| Area (path) | src | test | t:s | commits 90d | fix-ish 90d | last touch | live callers |
|---|---|---|---|---|---|---|---|
| tether/src/lifecycle (incl tui 1254/1230) | 11,900 | 9,481 | 0.80 | 103 | 12 | 2026-11-01 | daemon, lifecycle-api, recovery, reboot, wake-runtime import it |
| tether/src root files (waits, wakes, lane-reports, recovery, model-switch, agent-state, daemon, store, schema, lifecycle-api, asks...) | 21,100 | 11,079 | 0.53 | daemon 56, lifecycle-api 58, store 33 | 29 (whole dir) | 2026-11-01 | the daemon itself |
| tether/src/hub (multi-host: placement, peer, host-admin, update) | 4,184 | 3,421 | 0.82 | 40 | 5 | 2026-11-01 | live: ~/.config/tether/hosts.json has 2 entries, placement.json exists |
| tether/src/agent-hub | 2,411 | 2,384 | 0.99 | 26 | 3 | 2026-10-31 | chat/runs routes, web/server chat.ts |
| tether/src/term | 1,355 | 1,620 | 1.20 | 9 | 1 | 2026-10-31 | web/server terminal.ts |
| tether/src/client + files | 1,577 | 748 | 0.47 | 33 / 2 | 2 / 0 | 2026-11-01 | web/server (`tether/client`) |
| web/frontend/components | 10,074 | 6,792 | 0.67 | 149 | 22 | 2026-11-01 | the app |
| web/frontend/lib/hooks | 7,145 | 5,160 | 0.72 | 93 | 13 | 2026-11-01 | the app |
| web/frontend/lib (utils/health/chat/constants) | ~1,940 | ~1,920 | ~1.0 | 126 (lib total) | 19 (lib total) | 2026-11-01 | the app |
| web/frontend/app (1,301 of 1,562 is globals.css) | 1,604 | 138 | 0.09 | 35 | 0 | 2026-11-01 | the app |
| web/server/src | 6,243 | 4,515 | 0.72 (0.80 if testing.ts, a 341-line test fake counted as src, is moved) | 54 | 9 | 2026-11-01 | the app |
| tether/scripts (Python `st aico` CLI + helpers) | 4,100 | 4,887 | 1.19 | 123 | 16 | 2026-11-02 | `st aico`, install-release.sh, hub/update.ts |
| shared/ (chat 1,225/472; rest 357/138) | 1,582 | 610 | 0.39 | 3 | 0 | 2026-10-31 | web/frontend, web/server |
| docs + *.md | 5,531 lines in *.md (docs/ 4,504 lines, ~1.2k of it docs/history) | | | docs 122 | 2 | 2026-11-01 | n/a |
| vendor (`vendor/agent-hub-chat-ui-0.4.7.tgz`, `tether/vendor/agent-hub-sdk-0.1.4.tgz`) | 112K | | | | | | see below |

Big single files (src): tether/src/lifecycle/engine.ts 3,344 (34 commits, 6 fix-ish); tether/scripts/aico-root-watch.py 3,196 (86 commits, 10 fix-ish); lifecycle-api.ts 1,546 (58 / 7); lifecycle/catalog.ts 1,484; waits.ts 1,415; lane-reports.ts 1,339 (17 / 4); model-switch.ts 1,268 (3 / 1); recovery.ts 1,256; root-control.ts 1,207; wakes.ts 1,206; web NeedsYou.tsx 971; HostsSheet.tsx 750.
Reproduce: `git ls-files tether/src | grep -v test | xargs wc -l | sort -rn | head`.

Findings on specific questions in the brief:
- shared/chat vs agent-hub packages/chat-ui: NOT a duplicate. shared/chat is a consumer: it imports `ChatHubClient` from `@agent-hub/chat-ui` (shared/chat/bridge-client.ts:7) and adds aico-specific forwarding to Tether (forward.ts, 311 lines), a model/effort picker and an HTTP transport. `rg -il "effort|ModelPicker" /srv/workspaces/projects/agent-hub/packages/chat-ui/src` hits only voice and prompt-history files, so the picker/effort ladder is not in chat-ui. Keep. (Inference: if chat-ui later grows a model/effort select, effort.ts + pickers, ~150 lines, could move there; not today.)
- vendor/: only the two tarballs, 112K, versions equal agent-hub's current package.json (chat-ui 0.4.7, sdk 0.1.4). They are how aico consumes unpublished agent-hub packages (`package.json` devDependencies `file:vendor/...`). Needed, small. Cost is manual re-vendoring on each agent-hub release; no change recommended.
- No other project imports aico code (bounded rg over agent-hub, summitflow, nightshift, neri for `projects/aico/(shared|tether/src)` or `tether/client`: 0 hits). `aico-due.py` is live via claude-config/hooks/aico-due.sh.

### Not worth it list

| Area | LOC | Why | Do |
|---|---|---|---|
| tether/src/lifecycle/native-admin.ts + native-admin.test.ts | 217 + 199 | No importer outside its own test: `rg -n "native-admin" tether/src` shows only the file, its test and docs/history. Last touched 2026-10-24. Pure dead code from the Codex native-admin experiment. | Delete both. |
| tether/scripts/qualify-codex-admin.py (+ docs/history/qualifications/codex-admin-0.160.1.json 296 lines, codex-native-private json) | 223 + ~330 data | Referenced only from CHANGELOG and docs/history; its subject (native Codex admin) has no runtime consumer (above). Last touched 2026-10-19. | Delete script and qualification JSONs (history stays in git). |
| Desktop-app remnants: shared/font-settings.ts (+test), shared/terminal-history.ts, web/frontend/lib/hooks/use-hover-style.ts, use-dropdown-position.ts | 82+27, 4, 63, 50 = ~226 | CHANGELOG.md:315 says the Electron desktop app is gone. font-settings.ts is read only by web/frontend/lib/constants/lantern.test.ts:24 as text (a test that greps another file's source); terminal-history.ts, use-hover-style.ts, use-dropdown-position.ts have zero importers (`python3 orph.py`-style check: no import of the basename anywhere outside tests/docs). | Delete the four files and font-settings.test.ts; drop the font-settings assertion from lantern.test.ts. |
| tether/scripts/aico-root-watch.py name and shape | 3,196 (+ 4.5k tests) | It is the whole `st aico` CLI (sessions, roots, admin, create, widget, root, wake, wait, waits, nudge, placement; main at line 3128), one 93-def Python file named after one of its subcommands, loaded by tests through an `importlib` hack (tests/aico_cli_fixtures.py:11). 86 commits and 10 fix-ish in 90 days: the highest-churn file in the repo. Only part of the product that is Python in a TS codebase (owner rule: choose language on merit). | Do not port wholesale. Split into a package by subcommand (create, watch, wait, sessions, placement) so tests import modules, and rename. Port to TS only if sharing Tether's client/contracts is wanted (`descriptor()` in tests re-implements hashing that lives in TS). Medium-large effort, mostly mechanical. |
| docs/history (12 files), docs/plans, docs/INCIDENT-2026-07 | ~1.5k lines | Migration plans/cutover notes for finished migrations (cutover-aico.md 231, cutover-a-term.md 198, ASSESSMENT-2026-07.md 221, migration-plan.md 143...). Git already keeps them. | Delete docs/history and the incident write-up unless linked from a live doc; keep root-control.md, web-guide.md, project-guide.md. |
| tether/scripts/tether-lifecycle-harness.sh, tether-real-session-smoke.sh, aico-install-context-hooks.sh | 275 + 160 + 23 | Referenced only by tether/docs/LIFECYCLE_HARNESS.md and docs/history; harness was last touched 2026-10-31 but is not part of the gate. aico-install-context-hooks.sh is referenced only in docs/history/inventory-aico.md (last touch 2026-10-16). | Confirm with owner whether the harness is still run by hand; if not, delete all three. (Unverified: could be run manually.) |
| web/frontend/lib/hooks terminal-tab/pane/slot machinery (use-terminal-tabs-state, use-terminal-panes, slot.ts, use-project-mode-switch, use-active-session, use-terminal-handlers + utils) | ~2.3k src / ~2.6k test | Not dead (all imported) but a chain of 10+ hooks and utils threaded through each other for what is now a single-session-view mobile/browser UI; "detached panes", "pane limit", "project mode switch" survive from the multi-pane era (test names in use-terminal-tabs-state.test.ts: "creates new sessions detached, so no pane limit applies"). Inference only: I did not run the UI. | Medium: have an agent map which of tabs/panes/slot behaviors the UI still reaches and collapse; likely 1-1.5k LOC src and 1.5k test. |
| tether/src/lifecycle/engine.ts size | 3,344 | Not removable, but a god file with 6 fix-ish commits in 90 days and no dedicated test file (only engine-session-state.test.ts, 242 lines). | Split by concern when next touched (see tests section); no standalone cleanup. |

Not on the list, checked and fine: tether/src/hub (live, 2 hosts configured, 5 fix-ish in 40 commits), agent-hub, term (including real-tmux control.live.test.ts), client, web/server, vendor, shared/chat, `tether/scripts/aico-due.py` (live via claude-config hook).

## 2. Tests

Budget (`cd <repo> && st check budget --json`): `BUDGET:aico|state=over|src=70k|tests=48k|ratio=0.69/0.80|gate=100s/60s|gate_s_per_kloc=1.43|slow>3s=0|slowest10=5s|over=gate_duration|worsened=test_loc +10263`. Gate median 100.05s vs a 60s budget (one receipt only; baseline had been 135s at test_loc 38,104, now 48,367). No slow tests (slowest ten total 5.04s, none over 3s), so the 100s gate is the sum of three `tsc` stages, biome, ui-spec, vitest (4 projects), pytest, plus install checks, not a few slow tests. `st check budget` gives no per-stage breakdown; I did not run the gate. Test lines added in 90 days: 80,293, deleted 42,605 (`git log --since=90.days --numstat -- '*.test.*' tether/scripts/tests`): that is heavy rewrite churn (the net is +37.7k by raw numstat, but budget's own baseline shows test_loc up only +10,263 since it was set, so much of the numstat is moves/rewrites). Either way tests are growing faster than the gate budget allows.

Per-area t:s and verdict:
- tether/src root files 0.53: right for the churn, with specific thin spots (below).
- lifecycle 0.80: slightly heavy. root-control.test.ts is 1,688 lines for 43 tests (39 lines/test) against a 1,207-line root-control.ts (t:s 1.4). root-control.ts has 38 commits but only 1 fix-ish, so the heavy test is not buying many caught regressions. Trim.
- hub 0.82: right/slightly heavy (hub.test.ts 1,609, placement.test.ts 905). This is live and fix-prone enough to justify.
- agent-hub 0.99, term 1.20: heavy. term/ has 9 commits and 1 fix-ish in 90 days with 1,620 test lines (protocol.test.ts 328, control.live.test.ts 405). control.live.test.ts runs real tmux and is worth keeping; the 78 unit cases around it are mostly stable protocol, so test volume exceeds risk.
- web/frontend components 0.67, hooks 0.72: heavy on the hook side (below).
- web/server 0.72: right.
- tether/scripts 1.19 (4,887 test lines for 4,100 src): why more test than code: the 3,196-line CLI has 315 pytest cases across 14 test files, and tests/aico_cli_fixtures.py re-implements the create descriptor hashing in the test (`descriptor()`, lines ~25-45) so a request-format change edits code, fixture and many cases; 65 tests in test_aico_create.py (1,008 lines) look like variations on one create scenario (inference from skimming, not a full read). Verdict: too much; collapse to table-driven cases.
- client 0.40, shared/chat 0.39, web/frontend/app 0.09 (css): thin but low-risk (client is a typed wrapper; 33 commits with 2 fix-ish). shared/chat/forward.ts (311 lines, the security-relevant owner-side forwarding) has a 20-line forward.test.ts; web/server chat.test.ts covers it indirectly. Mild under-testing, worth one table-driven test.
- Overall: too much, but not wildly; ratio 0.69 is under the 0.80 ceiling. The problem is gate time (100s vs 60s) and growth rate, not the ratio.

Over-testing examples:
1. web/frontend/lib/hooks/use-terminal-tabs-state.test.ts:1-60 and :101-934. 934 lines for 11 tests, six `vi.mock`ed collaborator hooks (useActiveSession, useTerminalPanes, useTerminalSettings, useTerminalHandlers, useMediaQuery, useProjectSettings) with hand-built session fixtures repeated in each test: it asserts what the mocks were told to return. Source is 233 lines. Replace with 3-4 tests on the pure selection logic (terminal-tabs-state/utils.ts) and delete the rest.
2. web/frontend/lib/constants/lantern.test.ts:20-33 reads `shared/tokens.css`, `app/globals.css` and `shared/font-settings.ts` as text and `toContain`s strings; tests copy/CSS, not behavior (and pins a file that is dead, section 1). Delete the file-grepping cases, keep only what a UI check cannot catch.
3. tether/src/lifecycle/tui/tui.test.ts:29-34 mocks `node:fs` and `node:child_process` wholesale (55 mock calls in 675 lines, the highest in the repo) and asserts launch strings; also tui/lane-tools.test.ts, instructions.test.ts assert fixed prompt/copy text (`rg -c "toContain\('"`). These re-state implementation strings; any wording change fails tests with no behavioral signal.
4. web/frontend/lib/utils/slot.test.ts: 676 lines, 34 cases against a 401-line util (t:s 1.7) in the hook chain flagged above.
5. tether/scripts/tests/test_aico_create.py (1,008 lines, 65 cases) and test_aico_root_watch.py (1,202 lines, 69 cases): near-duplicate scenarios; each test file also pays for a 3,196-line module import.

Under-testing (churn vs tests):
- tether/src/lifecycle/engine.ts: 3,344 lines, 34 commits, 6 fix-ish in 90 days, no engine.test.ts (only engine-session-state.test.ts, 242 lines; the rest is exercised through root-control/entries/invariants tests). Highest-risk code with the thinnest direct tests. Adding focused tests while splitting the file is the one place to spend test budget.
- tether/src/daemon.ts: 958 lines, 56 commits, 9 fix-ish (the highest fix count in tether/src), no daemon.test.ts; covered only through server.test.ts (506 lines, 19 tests, 48 commits). Add a few startup/shutdown/recovery-order tests.
- tether/src/lifecycle-api.ts: 1,546 lines, 58 commits, 7 fix-ish, no own test file; covered via root-control/server tests.
- aico-root-watch.py: churn is highest, tests are plentiful, so it is not under-tested, just expensive.

## 3. Top recommendations (ranked by payoff)

1. Delete dead code and finished-migration leftovers (small, one agent, an hour or two): native-admin.ts + test (416), qualify-codex-admin.py + qualification JSONs (~550), desktop remnants (shared/font-settings*, terminal-history, use-hover-style, use-dropdown-position, ~226), docs/history + INCIDENT doc (~1.5k lines of docs), likely the three harness/smoke/hooks scripts (458, confirm first). Removes about 1.2k code LOC plus ~2k doc/data lines, and a few seconds of gate. Lowest risk, clear evidence.
2. Collapse the terminal tabs/panes/slot hook chain and its mock-only tests (medium): -1k to -1.5k src, -1.5k test. Check which pane behaviors the live UI still reaches first. Likely the largest single gate-time and maintenance win on the frontend (hooks tests are 5,160 lines).
3. Trim test volume to bring the gate under 60s (medium): table-drive test_aico_create.py/test_aico_root_watch.py (target -1.5k of 2.2k lines), shrink root-control.test.ts and tui.test.ts mock/copy cases (-800), delete file-grepping lantern.test.ts cases, thin term/ unit tests that duplicate control.live.test.ts. Estimate -3k to -4k test LOC. Then hold the line: budget already reports test_loc +10,263 over its baseline. Before trimming, get a per-stage gate timing (budget shows only the 100s total) so effort goes to the slow stage; I inferred the vitest+pytest share, not measured it.
4. Split aico-root-watch.py into a package by subcommand and rename it (medium-large): no LOC removed, but removes the importlib test hack, the 3,196-line single file with 86 commits/quarter, and shrinks duplicated fixture code (~300 LOC). Decide separately whether `st aico` should be TS to share Tether's client types; I would not port without a measured reason.
5. Split engine.ts (3,344 lines) while adding direct tests (medium, large if it needs live tmux): the highest-risk file with the thinnest direct tests; do it opportunistically next time a lifecycle bug lands, not as a standalone project. Add daemon.ts startup tests at the same time (small).
6. Leave alone: vendor/ tarballs, shared/chat (not a duplicate), hub, term/control.live.test.ts, web/server, lockfiles (package-lock.json 7,987 lines is lockfile, not maintained by hand).

Summary: realistic reduction is about 1.2k src LOC plus 1.5k to 2.5k more from the pane/tab chain, and 3k to 4k test LOC. Top three recommendations together take roughly 5k to 6k lines out (about 8% of src+test) and are the lever for the 100s to 60s gate target.
