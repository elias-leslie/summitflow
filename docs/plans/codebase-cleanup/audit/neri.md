# Neri audit (read-only)

Scope note: every path matching hunt|hunter|case|evidence (src, tests, docs, scripts, proxy hunt_*,
neri-hunters, neri-mongo-*, DB, logs, state) is NOT AUDITED (off limits). Numbers below are the
non-excluded remainder (loc.py: src 17,909, test 6,130, ratio 0.34). Repo is 5 days old
(first commit 2026-10-28; `git rev-list --count --since=90.days HEAD` = 164), so "90-day" = whole life.
`st check budget` (includes the excluded files): src=20k tests=9k ratio=0.46/0.80 gate=29s/60s
gate_s_per_kloc=1.40 slow>3s=0 slowest10=7s. Gate stages (.st-check.toml): caps (tests/test_rules.py),
proxy-lint, proxy (pytest -n 4), plus legacy ruff/types/pytest/security.
Fix count: no commit subject starts with "fix" (the repo's style is descriptive sentences), so
`--grep='^fix'` is 0 everywhere and useless. Substitute: `git log --since=90.days -i
--grep='fix\|repair\|bug\|wrong\|broke' -- <path> (hunt/case/evidence excluded)`.
Churn command: `git log --since=90.days --format=%h -- <path> ':(exclude,icase)*hunt*' ... | wc -l`.

## 1. Largest areas

Per-file LOC from `git ls-files | grep -Eiv 'hunt|case|evidence' | xargs wc -l` (non-test .py/.js/.css/.sh).
Test LOC is by name/import mapping (my mapping, inference where noted). "Callers" = CLI entry /
import / doc reference found by rg (excluded globs applied).

| Area | src LOC | test LOC | commits (all <=5d) | fix-ish | last touch | live callers |
|---|---|---|---|---|---|---|
| backend/app/st_cli (the `st neri` CLI: commands.py 2189, gates 454, egress_cmd 415, scope 373, programs 340, tool_cmd 273, rank 251, alerts 187, store 186, lint 184, h1_draft 119, drafts 116, out 93, identity 64) | 5,262 | ~2,900 (st_flow 929, scope 533, program_store 417, cli_clarity 324, egress 225, policy_egress 185, tool_needs 166, drafts 103, + helpers/conftest) | 49 | 8 | 2026-11-01 | `st-extension.json` manifest; 12 typer commands in commands.py + egress/tool apps; all registered (no unreferenced defs, see dead.py check below) |
| proxy core: addon 1067, cli 500, api 397, store 347, export 263, runner 219, quarantine 130, hooks 121, fingerprint 118, config 99, pcap 98 | 3,359 | ~1,000 (adapter 489, conftest 318 shared, cli_export 122, store 95) | 28 (all proxy/neri_proxy) | 2 | 2026-11-01 | `neri-proxy` console script (cli.py), mitmproxy addon, backend imports policy.py only |
| proxy detection/policy: policy 846, sensitive 679, pii_ids 366 | 1,891 | 315 py (sensitive 219, policy_vectors 50, pii 46) + 2,866 JSON vector lines (decide.json 2116, policies 699, normalize 51) | incl. above | incl. above | 2026-11-01 | addon scans every response; backend scope.py loads policy.py by path (backend/app/st_cli/scope.py:28) so one engine, not two |
| proxy sandbox/egress/exits: sandbox 306, sandbox_root 301, sandbox_probe 251, exits 180, exit_worker 178, egress 155 | 1,371 | ~480 (egress 271, live_egress 170, sandbox_unit 115 partly) | incl. above | incl. above | 2026-11-01 | sandbox_root runs via `sudo -n python -m neri_proxy.sandbox_root` (sandbox.py:150); exit_worker via egress.py:28 |
| proxy selftests: selftest 764, exit_selftest 350 (sandbox_probe 251 counted above) | 1,114 | ~0 direct (qname_filter at test_egress.py:229; fake_people/uplink_filter imported by test_sandbox_unit.py) | incl. above | incl. above | 2026-11-01 | `neri-proxy selftest` writes live-ready.json (proxy/README.md:128-138); needs sudo, tcpdump, podman, so cannot run in the gate |
| backend/app/web (owner PWA: app.js 657, view 400, program_view 287, app.css 265, access 163, routes 109, actions 99, sw.js 79, icons 68) | 2,158 | 799 (test_web.py) | 9 | 1 | 2026-11-01 | Live: https://neri.summitflow.dev behind Cloudflare Access (docs/st-neri.md:5, :201) |
| proxy/ops (live 675, oracle 301, synthetic 297, warp 72) | 1,345 | 0 | 8 | 0 | 2026-11-01 | live_check/dns_probe/exit-wireguard/install-exit documented in its header; oracle + warp have READMEs; synthetic/* referenced by nothing (rg for disk-pause-proof, resources-proof: 0 hits) |
| backend/alembic (9 revisions 0001..0009) | 534 | 69 (test_live_program_migration) | 7 | 0 | 2026-11-01 | env.py + 9 versions |
| backend/app root: schema.py 312, config 57, others | 415 | n/a | - | - | - | schema imported by st_cli and web |
| backend/scripts/import_index.py | 267 | 0 | 2 | 0 | 2026-10-29 | docstring: "One-shot import of the Neri Hunters index.md"; only ref is itself |
| tools/ranking_backtest.py | 148 | 30 (test_ranking_backtest.py) | 2 | 0 | 2026-10-31 | run by hand (`PYTHONPATH=backend ... --case-history <csv>`), docs none |
| proxy/scripts/install-host.sh | 45 | 0 | - | - | - | proxy/README.md, docs/st-neri.md reference scripts/hunt-box/install-host.sh (hunt side, not audited) |

Unused-module check: `python3 -I scratchpad/dead.py` (every top-level def/class name that appears once
in all non-excluded tracked text). Only hits were decorator-registered typer/FastAPI handlers
(commands.py next_cmd/show_cmd/..., egress_cmd, tool_cmd, web/routes.py). So no dead non-hunt
functions or modules; every neri_proxy module has an importer or an entry point
(`rg -n "\bMODULE\b" proxy backend docs` for sandbox_probe, sandbox_root, pcap, export, exit_worker,
exit_selftest, runner, quarantine, fingerprint, selftest). The wins are not dead code but oversized
files and unexercised breadth.

### Not worth it / shrink list
1. proxy/ops/synthetic (disk-pause-proof.py 184, resources-proof.py 113 = 297 LOC): header says
   "Bounded local C proof / D/G proof ... Run through `st tools run`"; nothing references them,
   no tests, last touched 2026-10-31/11-01. One-time acceptance proofs for work already landed.
   Action: delete (they live in git history), or fold the useful asserts into the hunt test suite
   (not audited). -297 LOC, zero gate time.
2. backend/scripts/import_index.py (267) : one-shot migration of the old Neri Hunters index.md,
   dry-run/--apply, "refuses if cases exist". Only referenced by migration history
   (`git log -- backend/scripts/import_index.py`: 2 commits, last 2026-10-29). Inference: already
   applied (I did not look at the DB). Action: delete after confirming the import ran. -267 LOC.
3. Exit kinds beyond direct: exits.py:16 `KINDS = {direct, wireguard, warp, platform-vpn}`;
   defaults.toml:209-215 enables only `direct`, `research-wg` is commented out. Supporting code:
   proxy/ops/oracle (301 + server.json), proxy/ops/warp (72 + Containerfile), proxy/ops/live
   (675), exit_selftest (350), exit_worker (178), exits (180) ~= 1.75k LOC for exits the shipped
   config does not use. Inference: if the owner's real config (state dir, not read) uses only
   direct/one wireguard exit, then warp and platform-vpn plus oracle server.py are speculative.
   Action: ask owner which exits are live; delete warp (72 + exits branch + test_egress.py:194
   case) and oracle provisioning (301) if unused; keep one tunnel kind. Potential -400 to -900 LOC.
4. Four selftest/proof layers for the sandbox: selftest.py 764 + exit_selftest 350 + sandbox_probe 251 +
   live_check.py 480 = 1,845 LOC of root-only live proofs that no gate runs. They are safety
   proofs for a security boundary, so keep, but live_check.py (480, an outside-the-package
   uplink/pcap check also needing pcap.py 98) overlaps selftest's exit checks: shrink by merging
   live_check into `neri-proxy selftest --live`. -300 LOC est (inference).
5. commands.py 2,189 LOC in one file (46 defs; next_cmd 173, program_set 194, new_cmd 134, show_cmd
   120, advance_cmd 115 lines). Not dead, but it is the highest-churn file (26 commits in 5 days)
   and a context-token sink every agent re-reads. Action: split program_* and check into the
   existing programs.py/gates.py modules; no LOC removed, but edits and test runs get narrower.
6. Migrations 0001..0009 (534 LOC, 9 files): squashable into one baseline only if every
   deployed DB is at head; production DB exists, so low payoff (-350 LOC at most). Skip unless it
   blocks work.
7. policy.py 846 LOC is engine-neutral "so any implementation (Python today, maybe Rust later)"
   (proxy/tests/vectors/README.md:3): speculative generality in the docs only, the code is single
   Python, and it is good (shared by backend scope.py). Keep; just drop the "maybe Rust" framing.

Not flagged: backend/app/web (live PWA, 1 test file), alembic, st_cli beyond the split, sensitive/pii
(real detector logic, shared with no other project: bounded rg for luhn/iban_ok in nightshift,
security-research, vault-tools non-test python returned no files, so no duplicate to merge).

## 2. Tests

Test:src ratios (non-excluded): overall 6,130:17,909 = 0.34.
- st_cli: ~2,900 : 5,262 = 0.55. 
- web: 799 : 2,158 = 0.37.
- proxy core: ~1,000 : 3,359 = 0.30.
- policy/sensitive/pii: 315 py (+2,866 JSON vector lines) : 1,891 = 0.17 py, vectors make it the best covered area.
- sandbox/egress/exits: ~480 : 1,371 = 0.35 (see below).
- selftests: ~0 : 1,114.
- ops/scripts/tools: 30 : 1,800 (ranking_backtest only).
Gate time is fine: 29s of 60s cap, no test over 3s, slowest 7s (`st check budget`). Nothing here needs
speeding up.

### Under-tested (churn and risk)
- addon.py 1,067 LOC (6 commits, the most-edited proxy file) is only exercised through
  test_adapter.py (489 lines, 25 tests, 0 mocks: real local synthetic servers, good style). That is
  integration only (no coverage measured), on the module the whole security story rests on.
  Medium risk; the right fix is more adapter scenarios (e.g. block/pause paths), not more mocks.
- sandbox.py 306 + sandbox_root.py 301 (607 LOC, root nftables/veth): tests are unit-only
  (test_sandbox_unit.py 115 lines, 7 tests: rule tables, addressing, spec_for). sandbox_root has
  zero direct test imports (`rg` of tests: 0); the real behavior is only proven by the sudo selftest,
  which is not in the gate. Acceptable by design, but a regression there is caught only when someone
  runs `neri-proxy selftest`. Cheap improvement: render the nft rule text from sandbox_root's builders
  in unit tests (no root) and assert the key drops; (small).
- export.py 263 LOC: 3 tests in test_cli_export.py (122 lines, 17 monkeypatch/mock refs) including
  test_openapi_file_is_current:14; the export stream path has thin direct coverage.
- selftest.py/exit_selftest.py/sandbox_probe.py 1,365 LOC with ~0 unit tests: they are the tests,
  but their pure helpers (uplink_filter, fake_people, qname_filter) are the only parts reached.
- api.py 397, cli.py 500: covered only incidentally (adapter/cli_export); cli.py has one
  import in tests.
- No fix-heavy hotspot exists (fixword counts: proxy/neri_proxy 2, st_cli 8, web 1, tests 5 of 164
  commits), so under-testing is a risk, not an observed defect rate.

### Over-testing signs (modest; the suite is mostly appropriate)
- backend/tests/test_st_flow.py: 929 lines, 58 tests, 1 file. Plenty of near-neighbours on the
  alert resend rules: test_check_advice_resends_got_one_failed_at_ready (:422), ..._an_earlier_stage_alert
  (:433), test_refused_regate_still_resends_failed_alerts (:446), test_uncertain_alert_is_never_resent
  (:457), test_alert_retry_rules (:399) = five tests on one retry policy. Parametrize or merge into
  two. Also splits into >1 file (>800 lines is slow to read).
- Copy-testing: test_st_flow.py:753 test_refusal_texts asserts full `git -C ... add findings/...`
  and "fix: set it with st neri log ..." message strings; test_web.py:511
  test_view_page_why_pay_words asserts exact wording ("pay band 0 (under $1,000)"). These break on
  every wording tweak (the repo's recent commits are mostly copy edits). Keep one assertion that
  a fix hint is present; drop exact strings. Also test_help_describes_commands_and_choices
  (test_st_flow.py:882) and test_rules.py's help-size caps overlap.
- Overlapping egress files: backend/tests/test_egress.py 225 + test_policy_egress.py 185 +
  proxy/tests/test_egress.py 271 + test_live_egress.py 170 = 851 LOC in four files on the same
  policy/egress allow concept (backend rows -> policy v1 -> proxy decision). Likely scenario overlap
  with decide.json vectors (129 cases); I did not diff them (inference). Candidate for merging the
  two backend files (-100 LOC est.).
- Mock-heavy: backend/tests/test_program_store.py 417 lines, 21 tests, 35 monkeypatch/mock/patch
  refs (highest density in the repo); proxy/tests/test_cli_export.py 17 refs in 122 lines;
  test_scope.py 24 refs in 533 lines. These are mock-leaning but not mock-only.
- Vectors: decide.json 2,116 + policies.json 699 lines (2,866 JSON) behind a 50-line runner.
  Data-driven, engine-neutral by design; the size is data, not logic. Fine, but check for duplicate
  cases when next editing (129 cases / 2,116 lines = 16 lines each, mostly pretty-printed JSON).
- test_rules.py (112 lines, 9 tests) is the "growth caps" gate (table/command/help size). Reasonable
  guardrail, runs without a DB.

### Verdict per area
- policy/sensitive/pii: right (vector-driven, deepest coverage).
- st_cli: slightly too much copy/assert-text coverage; right on logic. 0.55 ratio is the highest.
- web: right (auth/JWT/CSRF cases are what you want tested; two small copy tests).
- proxy core (addon, api, cli, export): too little (integration only; thin on export/api/cli).
- sandbox/egress/exits: too little in-gate for sandbox_root (relies on a root selftest that is not
  gated); egress is OK.
- ops/scripts: untested one-shots; delete rather than test.
- Overall: roughly right in volume (0.34/0.46 vs the 0.80 cap), pointed at the wrong places a bit:
  trim copy tests in st_cli/web, add a few proxy addon/sandbox_root cases. Net test LOC about flat.

## 3. Recommendations (ranked by payoff)
1. Delete proxy/ops/synthetic and backend/scripts/import_index.py, after confirming the import ran
   (small; -564 LOC, 0 gate time).
2. Ask which exit kinds are really in use; delete the rest: warp, platform-vpn, oracle provisioning,
   probably exit branches in exits.py/exit_selftest (small to medium; -400 to -900 LOC,
   some selftest time).
3. Merge live_check.py into the package selftest (`neri-proxy selftest --live`) (medium; -300 LOC,
   one fewer out-of-package tool to keep in step with the proxy).
4. Split commands.py (2,189) into programs/gates/check modules, and split test_st_flow.py (929) by
   area (medium; 0 LOC but cuts per-edit reads/test scope; highest churn file).
5. Trim copy-asserting tests (test_st_flow.py:753, test_web.py:511, help test) and merge the five
   alert-retry tests (small; -150 to -250 test LOC).
6. Add rule-text unit tests for sandbox_root and a few addon block/pause cases to test_adapter
   (small to medium; +150 LOC test, removes the only unguarded security boundary regression path).
7. Merge backend/tests/test_egress.py + test_policy_egress.py (small; -100 LOC).
8. Leave alembic alone; reconsider squash only after the DB moves.
Estimated total removable: ~1.2k to 2.3k src LOC (7 to 13%) and ~300 test LOC, no gate-time gain
needed (gate already 29s).

Excluded area: not audited (off limits).
