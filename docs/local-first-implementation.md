# Local-first implementation record

Task: `task-a6bee0c09e0e4a3c`. Owner: this orchestrator session.

This is the implementation checklist and evidence record for the owner's approved
workflow change, not a new reusable instruction store. GitHub publication is not
requested. Existing security controls, histories, unrelated work, and necessary
live validation must remain protected.

## Completion checklist

Resume evidence, 2026-09-23: seven small scheduled transfers failed because
the existing Google Drive mount disappeared, not demonstrated concurrency.
The existing account remounted without prompts in 0.435 seconds. The transfer
path now retries that specific mount failure once using the same account.
AfterTimes (4,604,444,264 bytes) and Codex (5,372,374,294 bytes) retain completed
local ciphertext; multipart transfer and standalone reassembly pass focused
regressions, including an actual producer-to-consumer manifest test. Both large
transfers subsequently passed live readback verification, recorded below.

The seven smaller archives total 5,185,110 bytes versus 72,907,291 previously
(about 93% smaller). File-count differences match the new rebuildable `.venv`
exclusion and Git HEAD/bundle evidence remains present. These are different
capture times, not a controlled benchmark. Daily infrastructure restore drills
already exist; the 48-hour missed-drill warning remains. A newer archive does
not erase dated successful drill evidence, and the UI explicitly identifies
which backup was tested rather than implying the latest one was restored.

Live follow-up: accepted source `cc9424650e087a6135de219f6bbe631a6f42b5f0`
passed 3,346 backend and 189 frontend tests in 105.56 seconds wall, 119.81 user,
19.97 system, peak 672,056 KiB. Managed deployment
`64f7889c175c4863ae2bca265ca025d2` succeeded from that exact source; all services
passed health. Seven small retained-ciphertext retries each took 1.45–2.30
seconds, transferring 10,370,220 bytes including complete readback, with no new
capture. AfterTimes verified nine parts in 323.896 seconds (329.110 seconds
queue-to-result), preserving its 4,604,444,264-byte ciphertext and full history.
Transfer bytes including readback and manifest: 9,208,892,740. Worker/descendant
RSS alone is not whole-transfer memory: the separate GVfs daemon must be counted.
AfterTimes did not have a complete daemon RSS time series, so its full peak is
not claimed. Codex returned an explicit provider HTTP 500 after 547.693 seconds;
its retry reused the same archive and verified parts, not another capture.
That retry succeeded: 11 parts, 5,372,374,294 ciphertext bytes, 210.431 seconds
replication / 214.081 seconds queue-to-result. Transfer bytes were 5,912,915,220:
nine existing 512 MiB parts avoided 4,831,838,208 bytes of repeated upload while
the full ciphertext was still downloaded and verified. Sampled worker/children
peak was 352,944 KiB; separate GVfs peak was 3,102,656 KiB, with daemon lifetime
high-water mark 3,373,188 KiB. These are separate measurements, not a falsely
small whole-transfer peak. All 29 enabled sources now have latest Drive copies
verified. The full measurements are in `.dev-tools/large-backup-live-evidence.json`.

Owner follow-up requires that slow work not be killed by arbitrary elapsed
duration. Changes awaiting final verification/rollout: a visible activity
controller maintains workflow liveness separately from verified byte progress;
live Redis leases protect long-running captures from orphan
cleanup, hourly schedules skip overlapping runs instead of cancelling them,
and historical transfer errors are not displayed as current failures after
successful retry. The remaining transfer lifecycle correction is explicitly
open: GIO progress may represent local buffering, so opaque waits must be shown
as unknown/needs attention, not called a proved stall. The former 600-second
bulk-copy kill becomes an attention threshold, not a claim that work failed.
Active-run retry exclusion and real child-process cancellation accompany that
change. The UI shows the phase and last verified part, and keeps cancellation
in a requested state until work actually stops. Metadata requests retain
their distinct bounds. No new OAuth integration or transfer platform is planned.

An unchecked item remains outstanding. Implementation alone does not establish
verification; record actual evidence before checking an item.

Current phase (2026-09-23): local-first acceptance and immutable managed rollout
passed. The owner saved and verified the recovery key; downloaded infrastructure
recovery passed all six disposable restore checks with 10/10 component coverage.
All 29 enabled sources have a verified latest Drive copy. Seven small copies,
the 4.60 GB AfterTimes archive and 5.37 GB Codex archive passed retained-ciphertext
retry. Final lifecycle rollout and live UI review, a fresh SummitFlow capture
and recovered runnable SummitFlow proof, updated Drive recovery kit and persisted
task closeout remain open. The latest lifecycle checkpoint passed 161 focused
backend tests plus three SMB upload regressions; these are not a substitute for
the pending managed rollout and actual cancellation demonstration.

### Local commits, integration, and validation

- [x] Local commits are the default; explicit publication remains available.
- [x] Frequent checkpoint commits use appropriate fast feedback and secret guards.
- [x] Local commits are associated with their task immediately.
- [x] Manual and autonomous execution preserve local work without a push
      (regression-tested; overall live closeout remains open).
- [x] Acceptance checks run against the actual integrated source being accepted.
- [x] Evidence records source, dependency/configuration inputs, scope, and results.
- [x] Matching validation evidence is reused; changed inputs invalidate it.
- [x] Full relevant tests, builds, fresh schema/migrations, package and context
      integration checks can run locally through the existing check surface.
- [x] Existing local security scanners are usable through ST; findings and CodeQL
      coverage differences remain explicit, with no claim of unproved equivalence.
- [x] Existing leases remain effective; commit/acceptance/deployment concurrency
      cannot overwrite other work or silently validate a different candidate.

### Completion and optional publication

- [x] Local acceptance, required deployment, and required live validation determine
      completion; publication is independent.
- [x] Missing required acceptance keeps the task open with an accurate reason.
- [ ] Closeout records completion promptly and idempotently; agents report actual
      persisted state rather than equating a merge or queued job with success.
- [x] Optional publication adopts an existing same-source PR/receipt rather than
      creating a duplicate to repair task linkage.
- [x] Later publication preserves newer local work and existing GitHub protections.
- [x] Pending historical publication requests are preserved; compatibility paths
      are regression-tested without executing unwanted historical pushes.
- [x] Local search/index refresh and cleanup no longer depend on publication.

### Managed deployment

- [x] Managed rebuild accepts stable, accepted source and identifies its revision.
- [x] Runtime cannot accidentally import later unaccepted development edits.
- [x] Receipts bind source/build identity, migrations, restart/health and applicable
      live checks; queued work is never reported as completed.
- [x] Previous release remains recoverable; database migration rollback limits are
      explicit. No new per-task services or ports.
- [x] Required workers and current deployment destinations retain their safeguards.

### Independent recovery

- [x] Long-running capture/transfer management uses real ownership and observed
      progress, not an arbitrary total-duration cutoff. Opaque waits are clearly
      labeled unknown/needs attention; they are not falsely declared stalled.
- [ ] The Backups UI presents local capture, Drive copy and restore-test status
      separately, shows current phase/last verified progress, prevents duplicate
      active retries, and offers cancellation that actually stops owned work.
      Verify these states and actions through the rendered UI without key access.

- [x] Backups preserve full unpublished Git history/refs and applicable JJ metadata
      (isolated recovery regressions; real downloaded restore remains below).
- [x] Staged, unstaged, valuable untracked/ignored work, and safe symlinks survive
      isolated recovery regressions, including staged-only Git objects.
- [x] Capture detects concurrent repository writes and refuses inconsistent success;
      valuable SQLite files use consistent snapshots (regression-tested).
- [ ] Required source/config/packaged dependencies have recoverable local copies.
- [x] Task metadata, prompts/memory, PostgreSQL and valuable SQLite state, evidence,
      required secrets/configuration and encryption-key recovery are accounted for.
- [x] Existing backup disk/Veeam/schedules are reused; native retention settings
      and protected-retention regressions are verified. No production expiry was
      forced. Veeam retention/image encryption/bare-metal restore remain unverified;
      native encrypted recovery does not depend on them.
- [x] Snapshot availability is diagnosed and not counted as recovery protection:
      these project directories are not Btrfs subvolumes. No filesystem conversion
      or disabling of protection is part of this bounded workflow change.
- [x] New native archives require encryption; key/error-output protections and
      source secret scanning passed. Historical archive/image limits are explicit.
- [x] Capture each source once locally, then encrypt and replicate that completed
      archive to Drive under the same backup record. Failed transfer retries reuse
      the existing artifact and do not trigger a second source/database backup.
- [ ] An isolated restore proves history, work, database state, and runnable software
      without relying on GitHub or mutating production databases.
- [x] Google Drive is an implemented offsite destination using the existing
      connection where available, encrypted completed archives, verified retention,
      and a download/decrypt/restore demonstration. Identify any missing machine
      credential or key-custody requirement explicitly; connection alone is not proof.
- [x] All real SummitFlow-managed/backed-up solutions have explicit local and Drive
      coverage; intentionally disabled fixtures are distinguished from missing coverage.
- [ ] SummitFlow's existing backup UI shows separate local/Drive status, failures,
      source coverage, retention and restore evidence with appropriate recovery controls.
- [x] The owner exported and saved the recovery key separately, then verified the
      saved copy through the UI. That configured identity decrypted downloaded
      archives. The agent did not access the password manager or upload the key.
- [x] New native local and Drive archives are both encrypted: one ciphertext
      artifact, not independent captures or independent encryption passes.
- [x] Key setup generates once, allows deliberate download/copy/reveal through the
      existing Cloudflare Access owner session, and proves a saved copy can decrypt.
      No new authentication challenge. No secrets in logs, query caches or browser storage.
- [x] Later key retrieval uses the same authenticated owner controls; no destructive
      key regeneration. Recovery-key directory is excluded from encrypted archives.
- [x] Actual owner custody is confirmed by the owner, not inferred from agent tests.
- [ ] Hard-loss recovery instructions, source-bootstrap utility, dated archive
      inventory and checksums are downloaded/read-back verified in the existing
      Google Drive “SummitFlow Backups” folder. No private recovery key is uploaded.

### Agent behavior and independence

- [x] Canonical scoped DB prompts and computed capabilities reflect local-first
      defaults; effective context is previewed before and after changes.
- [x] Authentication scope bounded: the example's one-off Agent Hub Codex OAuth
      repair/human login wait is not a recurring workflow defect. No auth-flow
      redesign or claimed savings from removing that necessary wait.
- [x] Validation uses tested secret-safe helpers and working managed capabilities.
      The historical unsupported-model/helper sequence was agent-reported; it was
      not rerun or independently proven fixed. No claim of savings from the rare
      owner-authentication wait or unrelated model repair is made.
- [x] Account-specific GitHub dependencies are distinguished from upstream GitHub,
      registries, model providers and actual deployment destination dependencies.
- [x] No-account and no-GitHub-client tests are non-destructive and isolated;
      no complete network-isolation claim is made.
- [x] Later publication is tested locally against a disposable remote; actual GitHub
      publication remains a separate owner decision.
- [x] Independent review and canonical quality gates pass.
- [x] Actual managed runtime behavior is exercised after authorized rebuild.
- [ ] Task is closed locally only after all required work is verified.

### Performance and token impact

- [ ] Measure baseline and changed fast-checkpoint, full acceptance, acceptance
      reuse, deployment and closeout durations; distinguish CPU work, remote waits,
      authorization waits and necessary live validation.
- [x] Record available check/tool-call counts and avoid repeated full gates for
      unchanged accepted inputs. Latest receipt records one canonical full-check
      invocation, 3,305 backend tests and 189 frontend tests. Session-wide tool-call
      and billed-token totals are unavailable; do not infer them from test counts.
- [x] Include redundant tool invocations, repeated reads, and unnecessarily broad
      tool output in the overhead comparison; consolidate related read-only queries
      and return bounded evidence, preserving required inspect-before-act boundaries.
- [x] Quantify removed recurring workflow steps (duplicate PR/CI,
      polling, redundant validation and administrative agent exchanges), separating
      measured time/token savings from modeled savings and necessary retained work.
- [x] Preview effective instructions before/after and measure injected context size;
      use observed token usage when available, explicitly label estimates otherwise.
- [x] Profile one local backup capture, encryption, Drive upload/download and
      isolated restore: elapsed time, bytes and retry behavior, without a second capture.
- [x] Document residual costs and evidence-based simplifications for one developer
      managing agents. Do not invent performance budgets or token savings.

## Owner decisions retained from the approved plan

- Acceptable loss interval and changed retention were not specified: preserve
  existing schedules/retention while measuring recovery evidence.
- Owner explicitly added Google Drive to required scope during implementation.
  Reuse its existing connection; offsite encrypted backup uploads are authorized.
  No new spending or account changes; verify recoverable encryption-key custody.
- Exact automated CodeQL equivalence outside GitHub is not established. Preserve
  findings and document the coverage/license limitation rather than hide it.
- Owner explicitly excluded the rare Codex OAuth repair/login wait from optimization
  scope and projected savings. Do not spend work redesigning authorization.
- Owner chose encryption for new local and Drive native archives, with automatic
  key generation and UI retrieval using existing Cloudflare Access Gmail auth only.
  Existing plaintext history is retained safely; Veeam image encryption is a separate
  existing-system contract, not silently changed by native-archive encryption.

## Working evidence

- Initial checkout clean; `st pulse --gate` clear.
- Plan validated by `st verify .dev-tools/local-first-plan.json` and imported.
- Task claimed before implementation. No GitHub publication requested.
- Local closeout/autonomous changes are in progress. Focused tests: 7 local
  acceptance/completion tests passed; 3 live-evidence import/hash tests passed.
  These are unit results, not end-to-end workflow or deployment evidence.
- Expanded focused local closeout/commit suite: 63 passed in 2.74s. Recovery-key UI
  tests: 6 passed (explicit retrieval, no query-cache secret, saved-copy verification,
  wrong-key failure, local-bypass denial, idempotent setup action).
- Existing Drive quota via native GIO: 5,497,558,138,880 bytes capacity,
  4,116,679,172,813 bytes free at inspection. No new storage purchase needed.
- Created a dedicated `SummitFlow Backups` Drive folder and configured the existing
  local backend `stb-d95e6a5c` to replicate there; no backup upload yet. Provider URI:
  `google-drive://eliasleslie@gmail.com/0ABTXoyBqewLJUk9PVA/1u49hftdtwOEfY7pe_zaORj7ZmlO8-Qqq`.
- Native GIO metadata has opaque etags, not a documented content digest. Remote
  integrity currently requires downloading each uploaded ciphertext for SHA-256
  comparison; profile this bandwidth/time cost explicitly.
- Real GIO metadata exposed a parser mismatch (space-separated attributes after
  tab-separated columns). Corrected folder-name parsing and added a passing regression
  test, avoiding duplicate folders and failed archive lookup.
- Snapshot diagnosis: `/srv/workspaces` is Btrfs but project directories are not
  Btrfs subvolumes. With the correct explicit workspace root, baseline capture reports
  `Not a Btrfs subvolume`. No repository moves/conversions or deletion were performed.
  Existing scheduled autosnapshot success must not be counted as recoverable snapshots.
- Seven real Git sources currently disabled were identified: browser-automation,
  code-intelligence, design-tools, desktop-automation, security-research, slopminer,
  vault-tools. Enable after encrypted runtime/key setup; preserve configured daily/14d
  retention. Leave test/fixture/deleted sources disabled.
- Canonical prompt corrections retain scope/assignments: safety-directive global
  enabled; persona-wake-guidance and feedback-audit non-global enabled. Measurements
  (tool estimates, not billed tokens): wake prompt 635→664, feedback 189→196,
  safety 913→932. Runtime preview coder 3984→4011 and persona 3942→3969 includes
  changed computed capability/task text; these are small increases, not token savings.
  Expected savings come from omitted workflow cycles, not pretending prompt edits shrink context.
- Existing `st tools cost --hours 24 --limit 5` reports request token counts unknown
  for major recorded endpoints; tool-output estimates are incomplete. Do not claim
  measured billed-token savings from these records.
- Integration: deployment/check focused suite 219 passed, 2 skipped; manual closeout
  suite 78 passed; autonomous closeout 60 plus 19 adjacent tests passed. These are
  focused test results, not full acceptance or live rollout evidence.
- Independent recovery review found two blocking defects before rollout: copied Git
  indexes referenced staged-only objects absent from bundles, and infrastructure
  restore-test/drill paths still treated encrypted archives as plaintext. Two new
  regression tests reproduced them; fixes are required before acceptance.
- The integrated quick gate passed TypeScript, Biome and candidate-only gitleaks,
  but caught one architecture violation, one unused test binding and five typing
  diagnostics. Corrections are in progress; this gate is not recorded as passing.
- Existing agent backup exclusions omit valuable recovery state: Codex sessions
  (~3.0 GB), history and state SQLite; Claude project transcripts (~306 MB), file
  history (~3.9 MB), plans and task state. Include this state after encrypted runtime
  is active, preserving cache exclusions and explicit provider-credential exclusions.
  Provider sign-in remains a separate dependency. Do not expose credential contents.
- Veeam managed status reports the latest session successful, daily 02:00 schedule,
  repository accessible and no active job. Image encryption and bare-metal restore
  remain unverified; native age encryption does not establish either.
- Independent recovery regressions now pass: staged-only Git objects are included
  without modifying source refs/index; infrastructure validation/drill uses private
  temporary decryption. Separate verifier rerun: 2 passed. Autonomous suite: 79
  passed; backup and isolated-restore CLI suite: 67 passed.
- Local-input review corrected stale acceptance reuse: hashes of known runtime env
  files and selected check-affecting variables now bind receipts; no secret values
  are stored. Changes during checks fail acceptance. This is not a claim of universal
  environment reproducibility (arbitrary variables/caches/installed dependency
  trees are outside this fingerprint). Acceptance regressions: 14 passed.
- Declared file changes or recorded commits now require local acceptance even at
  direct task-status completion. New commits invalidate old acceptance while
  retaining its artifact; lifecycle transitions retain independent receipts but
  invalidate completion intent. Source-bound completion suite: 40 passed.
- VCS doctor no longer fetches by default or treats unpublished local history as
  a blocker. Explicit `st vcs reconcile` retains its remote-sync semantics and is
  reference guidance, not a mandatory ordinary-task step. Regression suite: 5 passed.
- First timed integrated quick gate: 39.47 s wall, 34.03 s user, 6.22 s system,
  peak 594,636 KiB; 1,093 tests selected, 1,081 passed, 2 skipped, 10 failed.
  This was a failed integration run, not a successful-checkpoint performance claim.
  Failures exposed old publication-order expectations, a legacy artifact-exclusion
  expectation and release-bound Neri deployment fixtures; fixes are being verified.
- Rollout preflight corrected two concrete release gaps: frontend local tarballs
  required by the existing lockfile are now included with verified lock hashes;
  durable mockup files remain at their existing configurable path across immutable
  releases. Accepted compose configuration uses the existing host secret source,
  without copying or printing secrets. Neri rollout adapter tests: 36 passed.
- Isolated recovery is available through the existing command:
  `st backup restore BACKUP_ID --into EMPTY_DEST [--source SOURCE_ID] [--file DOWNLOADED_ARCHIVE]`.
  A supplied archive must match the backup checksum. This restores files/VCS and
  preserves a database dump; it does not restore a production database or prove
  the database dump can be loaded. Containerized database drill remains separate.
- First local checkpoint is `db3f78afd6090d6a5a8951f555d450c5eb1771c9`, no push.
  Its canonical checkpoint gate passed in 42.84 s wall (36.13 s user, 7.54 s
  system, peak 561,804 KiB). This large cross-cutting change is not a typical
  single-file checkpoint.
- Exact-source full acceptance with an empty GitHub CLI config, empty GitHub token
  variables and disabled Git SSH completed in 79.02 s wall: 3,231 backend tests and
  188 frontend tests passed; 2 backend tests skipped and 71 deselected by existing
  test configuration. Ruff/Biome/TypeScript passed. Acceptance remained **failed**:
  356 Python type diagnostics, three gitleaks findings and OSV dependency findings.
  Receipt: `.git/st/acceptance/24166d407962a0c587bfd336c2a5784bda26d43da6b7deb0ae25baf03a663ac6.json`.
  This disabled account credentials for that process; it was not an all-network
  isolation experiment. Public dependency-advisory access remained available.
- Type diagnostics were traced to existing dynamic owner-module aliases: installed
  owner packages/runtime tests work, but static facades lack explicit exports. Exact
  typed compatibility stubs are being added without `Any`, ignores or exclusions.
  Dependency findings are being fixed with bounded patched versions, not suppressed.
- All three gitleaks findings were the same fake lease-owner test argument pattern,
  not production credentials. A named test-only owner fixture removes the misleading
  inline pattern; whole-candidate gitleaks now passes without allowlisting or disabling
  scanner rules. Focused backup/lock/retention tests: 20 passed.
- Remote retention now protects both the newest copy and the specific copy just
  verified. A retry of an old archive after an extended outage cannot immediately
  delete its own verified recovery artifact. No live remote deletion was performed.
- Representative one-backend-file quick feedback: 2.65 s wall, 12 tests passed in
  0.95 s; Ruff/types/gitleaks passed, unrelated frontend checks skipped. This is
  an actual scoped-check measurement, not measured end-to-end task savings.
- Optional later publication was tested with real Git and a disposable local bare
  remote. Publishing an older accepted revision preserved newer local commits and
  another agent's untracked work; no GitHub client was consulted. This tests local
  publication mechanics, not current GitHub policy/API availability.
- Existing GNOME Drive integration is active; user-manager lingering is enabled
  and GVfs/GOA services are active. Cold-boot credential/keyring availability has
  not been tested by logging out or rebooting the owner's workstation.

## Remaining work

All unchecked items above. Update this record at coherent implementation and
verification boundaries; do not count substitute demonstrations as completion.

## Evidence-backed bottlenecks and intended corrections

The representative incident was Agent Hub task `task-976b1c3721244db2`, source
commit `15977c208`. Its timeline does **not** establish 42 minutes of CI overhead.
The commit was at 14:11:10 EDT; first PR at 14:11:56, service rebuild completed at
14:13:19 (26-second job), and initial CI finished about 14:14:54. Human OAuth
reauthentication was requested at 14:14:44 and supplied at 14:36:47. Live validation
then encountered helper/environment/model problems. A duplicate same-source PR was
created at 14:44:44, CI finished at 14:50:32, and merge completed at 14:53:05.
Closeout was requested at 14:53:10, but persisted task completion was 15:00:08.
The latter is 48:58 after the commit, not 42:00.

| Bottleneck or recovery risk | Targeted correction and evidence location |
| --- | --- |
| ST made publication part of local completion | Local commit default, local acceptance, separate explicit publication: `backend/cli/lib/commit_workflow.py`, `backend/cli/commands/done_task.py`. |
| Same-source task linkage created another PR/CI cycle | Adopt existing same-source publication before making another: `backend/cli/lib/github_publish.py`, `publish_workflow.py`. The incident's duplicate publication sequence took about 8:26; this is a case observation, not a per-task savings guarantee. |
| Queued closeout/merge was confused with completed work | Persist source-bound acceptance and required deployment/live evidence; close locally without waiting on publication: `app/services/task_acceptance.py`, `storage/tasks/status.py`, autonomous completion modules. |
| Broad checks and administrative output repeated unnecessarily | Focus quick tests, retain full acceptance once per unchanged candidate, reuse matching receipts, give concurrent checks distinct artifacts: `cli/commands/check_changed.py`, `check_artifacts.py`, `cli/lib/acceptance.py`. |
| Live-validation helpers and unsupported retries wasted time | Use known working managed interfaces/model capabilities and existing DB context corrections. Necessary live validation stays; rare human OAuth wait is explicitly not optimized away. |
| Runtime consumed a mutable development checkout | Build/deploy accepted immutable source and retain previous release with a source-bound receipt: `cli/lib/service_release.py`, `service_ops.py`. Durable state and packaged local dependencies must survive this transition. |
| GitHub publication was mistaken for adequate recovery | Preserve unpublished history, index objects, working files, databases and valuable agent state in one encrypted local archive, then replicate the same bytes to Drive. Existing archives are not deleted. |
| Backup success hid offsite/recovery gaps | Separate local capture, Drive verification and isolated-restore evidence in existing backup UI; retries transfer an existing archive rather than recapture it. |
| Scheduled snapshot execution did not mean snapshots existed | Record actual unsupported project-directory layout. Do not count nonexistent Btrfs snapshots as protection or convert all repositories as an incidental workflow change. |

### Independence boundaries

Ordinary local acceptance and completion must not require this owner's GitHub
account, a PR or Actions. Source/history and task/provider configuration need
independent backups. Existing model-provider sign-in, Cloudflare Access, Google
Drive access and production infrastructure remain real service dependencies.
Upstream package registries and public GitHub projects may still be needed for
uncached installation; account independence is not an air-gapped-build claim.
GitHub/GHCR distribution and optional remote checks remain separate capabilities.

Local Semgrep is not claimed to replace CodeQL. Fresh schema verification already
has `backend/scripts/verify_bootstrap_schema.py` but requires a disposable database,
not production. Agent Hub's private-context CI fixtures remain an explicitly
unproven no-account path for changes affecting those integrations. Docker/compose
and package distribution checks remain necessary when their inputs change, not
for every ordinary edit.

### Recovery-key interaction

The existing authenticated Cloudflare Access owner session is sufficient to
generate, download/copy/reveal, and later retrieve the key. No additional password,
reauthentication or show-once-only restriction is added. Setup proves that a
separately supplied saved key decrypts a fresh test message; this is not itself a
full backup restore. Actual owner custody and a downloaded archive restore remain
separate evidence requirements. A fresh installation can import the saved key,
but cannot silently replace existing configured key material.

## Verification and measured evidence

### Final gate repair evidence

- Full Python typing now passes. Runtime owner-module facades needed explicit
  source-adjacent re-export stubs; no type ignores, `Any` escape hatches or runtime
  behavior changes were used to hide the 356 diagnostics.
- Patched dependency locks were synced into the actual development environments.
  OSV now reports zero findings; 991 focused backend tests, 188 frontend tests and
  TypeScript passed against those versions. The narrow esbuild 0.28.1 override
  subsequently passed the real managed production build, including notes-ui;
  see the accepted revision and live evidence below.
- Quick checkpoints now run directly attributable tests and explicitly defer
  cross-cutting configuration coverage to mandatory full acceptance. Explicit
  full checks retain the complete suite; lint, types and secret checks remain.
  The refinement passed 167 focused tests. This avoids converting every lockfile
  checkpoint into another broad test cycle without weakening final acceptance.
- Candidate gitleaks passes after replacing misleading fake-token fixture strings;
  no allowlist or detection rule was disabled. Drive retention now preserves both
  the just-verified object and the newest recovery point, including an old archive
  retried after an outage. Twenty focused backup tests passed.

### Accepted revision and live evidence, 2026-09-21

- Local checkpoints: `db3f78a`, `5f461d9`, `7a6e19b`; no push or PR. A final
  focused-test correction excludes shared `conftest.py` from inferred test targets;
  explicitly changed fixtures still require full acceptance. Twelve regressions
  passed. The second checkpoint took 59.77 seconds before this correction.
- Full acceptance of `7a6e19bc6b93c9428767fd5d0df8c9821b7e4f14` passed with a
  temporary empty GitHub CLI configuration, empty GitHub token variables, disabled
  Git SSH and noninteractive Git. No stored credential was changed. This is an
  account-independence test, not complete network isolation.
- Acceptance: 78.89 seconds wall time; 3,237 backend tests passed, 2 skipped,
  71 deselected; 188 frontend tests passed; Ruff, Biome, Python types, TypeScript,
  gitleaks and OSV passed. Semgrep explicitly skipped because no local rules are
  configured. Artifact: `.git/st/acceptance/b8b2611853970101f6bdb5514d09313e729a5c4a0ea5760a3687f696791b897f.json`.
- Unchanged receipt reuse: 0.75 seconds end-to-end, 270.87 ms lookup. This avoided
  about 78 seconds of repeated checks for these exact inputs, not 78 seconds on
  every future task. Gate stdout was 1,337 bytes; the CLI unnecessarily expanded
  its full receipt to 15,507 bytes. Compact default output is now 319 bytes for
  that receipt (97.94% less). Character/4 estimates: about 3,877 to 80 tokens;
  these are not billed-token measurements. `--json` retains full machine output
  and the complete durable artifact is unchanged.
- Managed rebuild job `2e0b2c072ace4805ad193d4c507aa722` succeeded in 23.56 seconds.
  Frontend build took 16.90 seconds, migrations 0.86, restart 2.06, health 2.04.
  Build `b94042cce8e64e8a983ffef02aab6547` binds the accepted revision; deployment
  receipt is `/home/kasadis/.summitflow/services/jobs/2e0b2c072ace4805ad193d4c507aa722.deployment.json`.
  The backend, frontend and required Hatchet worker are active with WorkingDirectory
  inside that immutable release, not the subsequently edited checkout. Actual
  `/health` is healthy. The production build also exercised the patched esbuild
  override and notes-ui package successfully.
- Managed browser `/backups` check passed with zero reported errors/warnings;
  screenshot `/tmp/summitflow-backups-local-first.png`. Actual encryption status
  is unconfigured and local key setup returns 403, as intended: existing Cloudflare
  owner authentication is required, not a new authentication layer. The old
  protection summary incorrectly claimed complete setup. Regression reproduced it;
  the correction accounts for saved-key proof, latest Drive copies and matching
  infrastructure restore-drill backup identity. Three frontend tests and TSC pass;
  correction still requires final integrated rollout and rendered recheck.
- Fresh schema proof ran through `st check cleanroom` in a uniquely named,
  loopback-only tmpfs container from cached `pgvector/pgvector:pg16`: 1.571 seconds.
  Fresh snapshot restore, full migration chain, retained upgrade fixture and repeat
  upgrade passed. Container `sf-bootstrap-verify-20260921-a7c4` was stopped and
  auto-removed, with no remaining volume. Production databases were untouched.
- After the encrypted runtime went live, seven real sources were enabled with
  their existing daily schedule and 14-day retention: browser-automation,
  code-intelligence, design-tools, desktop-automation, security-research, slopminer,
  vault-tools. Fixtures/retired sources remain disabled. No captures were requested
  before owner key proof. `.codex/.backupignore` now preserves history, sessions,
  local instructions and durable state SQLite; `.claude/.backupignore` preserves
  project conversations, file history, sessions, tasks, todos and plans. Diagnostic
  caches, generated environment snapshots and provider-login files remain excluded.
  The non-project CLI dry-run only reports that capture is server-side; it did not
  prove these archives and is not counted as backup/restore evidence.
- Read-only recovery inventory confirms shared PostgreSQL contains ST tasks,
  Agent Hub prompts/history and Hatchet; the infrastructure capture already covers
  those DBs plus global/compose configuration and Redis. Additional live ingress,
  service receipt/unit and Agent Hub durable-state gaps are being added to that same
  capture, not a separate backup system. Root-owned unreadable state must be reported,
  not silently omitted. Existing Veeam status is successful but its CLI job-info
  exposed no encryption status; image encryption remains unverified and unchanged.

Remaining live prerequisites: owner saves and verifies the recovery key through
the normal Cloudflare-authenticated UI; finish final coverage/UI rollout, perform
real encrypted captures and verified Drive transfers, download/decrypt/isolated
restore (including disposable infrastructure), complete rendered copy review and
source-bound closeout evidence. The overall task remains open.

### Final integration findings and explicit human prerequisites

- Infrastructure recovery capture now includes exact Cloudflared config and its
  referenced credential file, exact Caddy config/environment, user systemd unit
  files and enablement-link metadata, Agent Hub durable host state, and managed
  service receipts/jobs/current+previous build identities. Release trees and
  dependency caches are rebuilt, not duplicated. Link targets are recorded rather
  than followed; the recovery-key directory is hard-excluded. Missing/unreadable
  components are explicit incomplete-coverage facts without throwing away the
  database archive. Focused coverage, safe-reference, secret-exclusion and error
  regressions pass. Root ingress capture is not yet operationally complete.
- Live inspection confirms the required worker is native user-systemd, PID
  1854271 at inspection, inside accepted release `b94042cce8e64e8a983ffef02aab6547`.
  Exactly one SummitFlow `app.worker` process was present; no live or stopped
  `summitflow-worker` Docker container exists. Its journal shows active Hatchet
  assignments. An earlier container-mount concern was disproved by live evidence;
  no container mount change is needed.
- Only two host credential files currently need additional read authority:
  `/etc/caddy/env` and
  `/etc/cloudflared/2757c3c8-caa6-444b-8f88-dc02b21bd1a8.json`, both root-owned 0600.
  The owner was asked before granting the backup user read-only access. No ACL,
  permission, credential or security-boundary change has been made. Until resolved,
  the encrypted infrastructure archive preserves other state but reports the gap.
- Owner key custody was requested through the existing authenticated UI. The key
  is still unconfigured at the last check. Agent-generated test keys do not satisfy
  this requirement. There is no additional login or show-once recovery restriction.
- Actual storage probe found writable local storage; its old compact output hid
  the separate offsite/key result and returned zero even on failure. The API now
  combines those facts into its diagnostic, and failed CLI tests return nonzero.
  Regression sequence: three reproduced failures, then 12 passing focused API/CLI
  cases. Infrastructure health and setup summary also require complete required
  coverage and a current, matching restore drill before reporting protection checks
  passed. Frontend regressions pass.
- The native `/backups` and `/backups/storage` routes rendered with zero reported
  errors/warnings. SlopMiner inspected the complete rendered encryption section
  using the owner-approved general voice and this product's developer audience,
  not Neri's research-record semantics: no deterministic findings. Agent review
  retained the concrete setup action, same-archive explanation and host-compromise
  limit. Only the visible local-session/setup-required state was reviewed; secret
  retrieval states require the owner's existing Cloudflare session. Artifacts:
  `.dev-tools/backup-key-copy.json` and `.dev-tools/backup-key-copy-review.json`.
- Actual schedules are current: 29 enabled real sources, with representative
  SummitFlow/infrastructure/Codex last runs on September 21 and next runs on
  September 22. Old July storage-test timestamps are not evidence of stopped backup
  scheduling. Six fixtures/retired sources remain disabled.
- Unexpected task `running` to `pending` transitions were traced to the existing
  30-minute claim expiry and 15-minute reset cron, not local commits or deployment.
  Claims at 19:40:39 and 20:26:30 UTC expired before resets at 20:15 and 21:00.
  Parent resumed at 21:42:03. A targeted renewal/auditing correction is being
  integrated; no longer TTL, periodic agent polling or idle-liveness assumption.
- Deployment subtask metadata closeout was attempted while other integration edits
  remained. The existing clean-checkout guard refused it. Parent task-level closeout
  was not substituted: the overall work is unfinished. Subtasks will be closed at
  a coherent verified checkpoint, not by committing another agent's unfinished work.
- Existing Veeam image encryption remains an explicit exception, not covered by
  native age encryption. Its vendor uses job password-based encryption; this is
  not automatically the age recovery key or retroactive image encryption.
  [Veeam encryption settings](https://helpcenter.veeam.com/docs/agentforlinux/userguide/backup_job_encryption.html).
  No Veeam job, password, legacy archive or recovery point has been changed/deleted.
- Cold-start review found that the ID-based isolated restore still needs ST backup
  records. A DB/API-free explicit archive-and-external-key CLI path is being added
  using the existing decrypt/safe-extract/Git-recovery primitives, with a separate
  short recovery runbook. No second archive engine or backup capture is needed.
  Downloaded ciphertext authentication and internal Git/index checksums must be
  distinguished from an externally retained ciphertext SHA-256. The existing
  offsite manifest is local-only, so Drive-only recovery cannot currently obtain
  that independent expected SHA-256 from the sidecar.
- Actual release storage is 1.1 GB for the first immutable build (job metadata
  16 KB). Older build directories currently accumulate. The owner was asked before
  adding guarded removal of rebuildable releases: preserve current/previous and
  every service-referenced build, all Git history, receipts and logs. No release
  directory has been deleted. This is an explicit pending retention/authority
  decision, not a silently completed cleanup feature.
- Live same-owner renewal at 22:12:14 UTC preserved `claimed_at=21:42:03.323722`,
  owner `davion-sidarli` and `running` state, extending expiry to 22:42:14.461698.
  This exercised the editable CLI against the prior API without changing another
  task. The renewal/security/receipt-preservation slice passed 140 focused tests
  in 15.14 seconds, targeted Ruff and Python types. API authorization failures
  never fall through to local DB access; the old-server compatibility path is
  restricted to loopback HTTP 409 and exact configured project/owner matching.
  Task-bound claim, commit and acceptance renew the existing lease. More than
  30 minutes without task-bound activity can still expire; no longer TTL or
  periodic agent polling was introduced.
- Final immutable-runtime review found infrastructure capture resolving ignored
  compose configuration relative to released source. A stable host-configuration
  root is being integrated for backend/worker capture; executable code remains
  bound to the immutable release.
- Owner confirmed saved-key custody. Non-secret status independently reports
  `configured=true`, `ready=true`, `identity_exported=true`, and
  `roundtrip_verified_at=2026-09-21T22:21:59.124862+00:00`.
  No recovery key was retrieved into this conversation.
- Owner approved narrow read-only access to the two root-owned ingress secrets.
  Applied `user:kasadis:r--` ACLs to `/etc/caddy/env` and
  `/etc/cloudflared/2757c3c8-caa6-444b-8f88-dc02b21bd1a8.json` only.
  Both remain root-owned; effective read=yes/write=no, other/group access absent.
  Their contents were not printed. Rollback is removal of these two named-user
  ACL entries; capture coverage must then report the missing state again.
- Owner approved guarded cleanup of rebuildable releases that are neither current,
  previous rollback nor referenced by any service. Implementation passed 53 focused
  tests plus one edge-case regression, Ruff and Python types. Read-only live
  inventory completed for both systemd managers (one user reference, zero system
  references). Ambiguous paths/inventory skip cleanup; receipts/jobs/logs remain.
  Arbitrary non-systemd processes are not claimed as service references.
  No real release deletion has yet occurred.
- First real encrypted local/Drive archive: SlopMiner `bkp-0cf933039a1d416b`,
  created 22:23:56.168019 UTC, completed 22:24:01.140978 UTC. Capture 2,027 ms;
  plaintext compressed bytes 5,480,869, ciphertext 5,482,397; replication/full
  verification download 2,839 ms, transfer 10,964,794 bytes. Local and downloaded
  ciphertext SHA-256 matched; no remote retention deletion occurred.
- Separately downloaded that Drive object in 0.79 seconds and restored it through
  `st backup restore --into` in 1.00 second at
  `/tmp/summitflow-drive-restore.yKptsl/restored`. Git fsck passed (an expected
  synthetic staged-index commit is dangling); restored HEAD
  `73b87d92e9b33626c5c9d6f84c90b247e137bef5`, five HEAD-history commits.
  This actual restore used the host identity after the owner's separate saved-key
  proof; it is not a claim that the agent read their password manager.
- Retrying offsite sync kept the same backup ID, capture timestamp, local checksum
  and Drive object. It took 1,300 ms and transferred 5,482,397 bytes (verification
  download only), with `reused_local_archive=true`. No second capture/upload.
- The live inventory exposed 532 rebuildable root `.venv` files because the old
  default only excluded `backend/.venv`. Generic `.venv` exclusion now handles
  nested project layouts; regression failed first, then all 20 archive-safety
  tests and Ruff passed. Valuable `.dev-tools` evidence remains included.
- DB/API-free cold recovery plus host-config capture passed 54 focused tests.
  The offline test forbids project configuration, API and backup-store access;
  wrong keys, tampering, checksum mismatch and nonempty destinations fail safely.
  Cold-start instructions are in `docs/local-first-recovery.md`.
- The real downloaded SlopMiner ciphertext also passed the new DB/API-free CLI
  restore in 0.98 seconds with its independent expected SHA-256 and host identity,
  into `/tmp/summitflow-drive-restore.yKptsl/offline-restored`; Git fsck passed.
  No production database or source directory was overwritten.
- Owner explicitly requested a fire/electrical-loss recovery kit in Drive and
  confirmed that the saved encryption key stays in their password manager.
  The kit must cover replacement-host prerequisites, fresh-volume database/Redis
  restore, durable config/state, rebuilding releases and ingress restoration.
  It is not a bootable OS image, and normal fresh-install instructions must not
  regenerate restored secrets or initialize conflicting database roles first.
- Existing scheduling independently ran the seven newly enabled real sources
  from 22:30:00 to 22:30:42 UTC after key verification. All seven completed and
  verified their Drive copies; their next scheduled runs are September 22.
  This is live schedule evidence, not a manually substituted scheduler demo.
  SlopMiner's scheduled run is a separate legitimate recovery point after the
  earlier manual transfer-retry test. Already verified sources need not be
  recaptured just to fill the all-source verification checklist.
- Standalone `scripts/recovery-bootstrap.py` unlocks SummitFlow source when ST
  and its database do not exist. Nine focused tests cover valid extraction,
  wrong key, tamper, checksum mismatch, nonempty destination, traversal, wrong
  root and forbidden member types. Private staging is cleaned on failure; it
  never installs dependencies, restores databases, starts services or prints keys.
- Cross-component infrastructure coverage/health review passed 19 tests after
  removing the false directory-count inference. Offline restore now hashes and
  decrypts the same private staged ciphertext bytes. `backup all` excludes
  disabled sources, while explicit per-source capture remains available.
- `docs/disaster-recovery.md` now covers replacement-host recovery in full,
  including source/WIP, fresh PostgreSQL/Redis volumes, config/state, key import,
  managed builds and ingress. The real Redis 7/Compose test disproved direct
  AOF-enabled startup from a copied RDB (all three test databases lost their keys).
  Loading RDB first, enabling/waiting for AOF rewrite and restarting normally
  preserved all three databases, even without the disposable RDB. The guide uses
  that verified sequence. All test containers/volumes were removed; production
  data and service configuration were untouched.
- Integration checkpoint correctly blocked on five test-only type diagnostics
  and two scoped-closeout fixtures that had not mocked the new owned-claim renewal
  seam (844 other focused tests passed). Assertions/fixtures were corrected without
  weakening runtime ownership or backup checks. The failed checkpoint took 47.99
  seconds. Its compact output hid the existing failed-gate artifact hints; those
  hints now print directly, without repeating successful checks or raw test logs.
- Independent review found that legacy top-level `configs` tree counts could
  falsely imply every required infrastructure configuration file existed. Exact
  per-component evidence is being corrected before the final rollout; the new
  protection-summary claim must not depend on directory counts alone.

### Recurring work removed and retained

- Ordinary local tasks no longer need a push, task-linked PR, remote CI wait or
  publication polling. The incident's duplicate-publication interval was 8:26;
  this is not a guaranteed savings rate. The human OAuth interval is excluded.
- Matching acceptance avoids a second full check run (measured 78.89 seconds
  versus 0.75 seconds reuse). Changed inputs still require validation.
- Default receipt output is 319 rather than 15,507 bytes for the measured receipt.
  Full machine output remains available; unique detail artifacts avoid reruns
  caused by another agent overwriting a result.
- Necessary costs remain: integration reasoning, correctness/security gates,
  destination-specific deployment/live acceptance, one encrypted local capture,
  offsite transfer verification and restore exercises. Backup and final closeout
  timings remain unmeasured until their actual live runs.
- This implementation session itself included avoidable repeated path lookups,
  overly broad tool output and a subtask closeout attempt while agents were still
  editing. These are waste, not product savings. Billed-token telemetry for the
  incident was unavailable; zero recorded usage is not zero consumption.

## Everyday workflow after verified rollout

### Final lifecycle rollout and live cancellation, 2026-09-23

- Local checkpoint `c29a1402f0bddc8dfd64518744291f3e006ba98a` passed full
  acceptance: 3,406 backend tests, two skipped, 71 deselected; 214 frontend tests;
  Ruff, types, Biome, TSC, gitleaks and OSV passed. Semgrep has no configured
  local rules and is explicitly skipped; CodeQL equivalence is not claimed.
  Wall time was 100.43 seconds, user 120.40, system 20.04, peak RSS 679,808 KiB.
  Evidence: `.dev-tools/final-lifecycle-acceptance-performance.txt` and acceptance
  `68fe1072e74a325bd2d8bad7958762ac722bfff738a1b49dfe7a89a80947ff9a`.
- Managed rollout `c75e7fed0df54e969723c5a8d6f632f2` used that accepted source
  and passed service health. Prepared-to-completed time was 21.68 seconds,
  including 14.50 seconds frontend build and 2.63 seconds service restart.
  This is an observed rollout duration, not an attributed speedup over an
  earlier rollout with different restart timing.
- The rendered UI started and cancelled one real SummitFlow capture:
  `bkp-8ab9c6ba4df54c12`, run `ab6ce4c0-c908-42c8-9493-ed24ef60ab5f`.
  The cancel click at 14:40:10.417 UTC preceded terminal cancellation at
  14:40:10.934887 UTC by about 0.52 seconds. The worker lease was released;
  no capture subprocess remained. The prior completed backup
  `bkp-f7eeb8884e604903` retained its SHA-256 and verified Drive status.
  UI showed cancellation requested, then cancelled, without claiming the
  previous recovery point was lost. Screenshots are in
  `/tmp/summitflow-backup-ui.rDr8Mv`; a durable compact receipt follows.
- This live check found generic labels for several real capture phases.
  A frontend-only wording correction is being completed before the final
  successful capture. No additional cancellation attempt is needed for labels;
  final render/progress verification remains required.
- Independent review closed an enqueue race with stable non-secret attempt IDs:
  a late queue response or failed old attempt cannot overwrite a newer retry.
  Cancellation persists atomically through local-checkpoint writes and binding.
  Former bulk timeouts for GIO, age, Git, database capture and SMB upload now
  signal attention, not failure. Metadata bounds and production database restore
  safeguards remain. No LLM is used for monitoring; state polling is local and
  sparse, and renewed liveness is never described as verified byte progress.

### Final live recovery verification (in progress)

- Owner explicitly approved practical AfterTimes cleanup while retaining large
  backup support. Its worktree was clean; 3,953,640,722 of 3,967,008,566 Git-object
  bytes are reachable from refs (about 99.7%). History is not disposable bloat.
  Only two reproducible environments were excluded from future captures:
  `.dev-tools/vendor/spritefusion-pixel-snapper/target` (~71 MB) and
  `.dev-tools/yaml-env` (~13 MB). Installed tools, graph results, useful audio/
  animation evidence, assets and all history remain. Local AfterTimes checkpoint
  `c3cf1d764e9791dc12dd2ad1e223cf57eaf93a77` contains only `.backupignore`; no push,
  deletion, garbage collection or history rewrite occurred.
- Large-file support remains required independently of that cleanup. The actual
  retained AfterTimes ciphertext is **4,633,275,582 bytes**, not the earlier
  approximate small-backup estimate. Two whole-object uploads hit the existing
  600-second deadline; the helper reached roughly 8 GiB RSS. Upstream installed
  GVfs/libgdata code confirms whole-request buffering and non-resumable upload;
  no hard 4 GiB limit was established. The proposed correction transfers the same
  ciphertext in verified 512 MiB parts (below the already successful 853 MB
  transfer), publishes an ordered checksummed manifest last, and reuses good parts
  on retry. No new key, account, service or independent backup is introduced.
  The standalone utility assembles and verifies the original ciphertext before
  normal age decryption. Implementation/large live proof are in progress.
  Primary references: [installed GVfs upload path](https://gitlab.gnome.org/GNOME/gvfs/-/blob/1.54.4/daemon/gvfsbackendgoogle.c#L3240),
  [non-resumable libgdata API](https://gitlab.gnome.org/Archive/libgdata/-/blob/0.18.1/gdata/services/documents/gdata-documents-service.c#L807),
  [whole-body buffering](https://gitlab.gnome.org/Archive/libgdata/-/blob/0.18.1/gdata/gdata-upload-stream.c#L1035).
- Claude, BlackBox and Ominull now have real encrypted, Drive-verified captures
  after their fixes. Codex's next observed failure was active JSONL appends and
  changing JJ metadata, not the repaired Git-index conflict. A bounded raw-prefix
  JSONL capture preserves active transcripts without reading a growing tail;
  prefix mutation/truncation and meaningful JJ changes still fail closed. Its
  isolated test overlapped a real JJ operation, so final capture needs a quiet VCS
  window after the integration checks. Only an exact empty JJ import/export lock
  is disposable; no valuable JJ metadata was excluded.

- Follow-up source `13124290b31d903b06c14e3dfc8334e822363cec` passed full
  acceptance with process-only GitHub credentials unavailable: 100.09 seconds
  wall, 119.54 user, 19.87 system, peak 673,528 KiB; 3,305 backend tests and
  189 frontend tests passed. Lint/types/gitleaks/OSV passed; Semgrep remains an
  explicit no-local-rules skip, not CodeQL-equivalent coverage.
- Managed job `6ab6eab95e284423ba25d3ad0c465efc` deployed that exact accepted
  source successfully in 22.068 seconds. Live health passed. Approved cleanup
  removed only unused rebuildable release `b94042cce8e64e8a983ffef02aab6547`;
  current/previous releases, source, receipts and logs were preserved.
- Both SQLite fixes and the Git-index fix are now deployed. Focused regressions
  passed for live WAL churn, orphan/excluded-database sidecars, database replacement
  and unrelated source mutation. The two real configuration Git restores preserved
  exact index bytes; full encrypted recaptures are still pending.
- A 600-second AfterTimes Drive upload timeout blocked other GIO requests. Once
  the timed-out operation settled, the exact same root listed successfully in
  0.58 seconds. No daemon restart, unmount, reauthentication or credential change
  occurred. Remaining transfers are being verified sequentially; the cause is not
  proven to be concurrency. Learn-o-Tron retry reused its existing archive and
  verified in 9.536 seconds. The AfterTimes retry is pending.
- `START-HERE.md`, `OFFLINE-RESTORE.md` and `recovery-bootstrap.py` were uploaded
  to the existing Drive folder and individually downloaded/hash-matched.
  `.dev-tools/recovery-kit-evidence.json` records their SHA-256 values. The final
  source inventory and `SHA256SUMS` are not uploaded yet. No private key is in the kit.

- Infrastructure backup `bkp-d52d5305f5074eee` has exact 10/10 component
  coverage and a verified Drive copy. Its downloaded ciphertext was checked and
  decrypted with the protected host identity; all six disposable restore checks
  passed in 177,016 ms. No production database was restored or overwritten.
- Real Claude/Codex captures exposed intent-to-add file/directory index states
  that Git cannot turn into a commit tree. A minimized regression reproduced
  the exact failure in 0.47 seconds. The fix bundles a synthetic flat tree of
  referenced index objects while preserving the original index bytes, rather
  than requiring a commit-ready index. Both actual configuration repositories
  passed isolated Git restoration with identical original/restored index hashes;
  neither source index was modified. Full encrypted captures remain pending.
- BlackBox/Ominull exposed live SQLite WAL/SHM churn in the generic source
  stability check; the existing transactional SQLite copy needs matching
  inventory treatment. A focused regression/fix is underway, not yet deployed.
- Learn-o-Tron's local ciphertext completed, but one Drive listing timed out.
  Retry uses that same artifact and record, not another capture.
- The first final SummitFlow capture correctly rejected a new generated test
  artifact during capture. Retry follows the final checkpoint with a quiet
  source tree; this failed attempt is not counted as protection.
- The hard-loss runbook now handles normal archive retention: the dated
  inventory maps source folders, but is not a permanent filename lock. Static
  kit checksums are separate from expiring archives. Newer selected archives
  still require authenticated decryption and actual restore validation; absent
  independent prior checksum evidence is recorded honestly.

1. Claim the task once and use existing file/lane ownership for parallel agents.
   Each agent edits its assigned files; commits are local and path-scoped where
   another agent has unrelated edits. No per-task PR or branch is required.
2. Use focused feedback during development and `st commit --no-push --task TASK`
   at meaningful checkpoints. Publication is not implied by a commit or task event.
3. Integrate the compatible changes, then accept the actual clean candidate with
   `st check --acceptance --task TASK`. Reuse only matching receipts; a changed
   source, relevant configuration or failed check does not inherit success.
4. For a task that requires deployment, rebuild the existing managed destination
   from that acceptance receipt. Observe actual health and required live behavior;
   a queued rebuild is not a deployed release. Import matching deployment/live
   receipts with `st done TASK --evidence FILE` when required.
5. Complete the task locally once its acceptance work is finished. Backups run on
   the existing schedules: one encrypted local capture, then the same ciphertext
   copied to Drive. Failed transfer retries do not recapture source/databases.
6. Publish later only when the owner chooses. No weekly schedule is imposed.
   Existing GitHub protections still govern optional publication, and same-source
   publication is reused instead of generating a task-linkage-only duplicate PR.

## Rollout and rollback boundaries

- Checkpoint code locally before rollout; preserve existing histories, local
  archives, package artifacts and unfinished task state. No force pushes or
  destructive repository operations are part of this migration.
- Full acceptance must pass before the managed rebuild. The release directory is
  outside the editable checkout; registered ports/services and existing durable
  configuration/data paths remain in use. Failed activation retains/restores prior
  service definitions. Database migrations require their own compatibility/recovery
  evidence; reverting a service unit does not undo migrated database state.
- Do not enable the seven previously disabled real sources or remove valuable-state
  exclusions until the encrypted runtime is active. Preserve their existing schedule
  and retention. Leave fixtures/deleted projects disabled.
- Generate/import the recovery key through the existing owner session, save it
  independently, and verify the saved copy. Then demonstrate a real local capture,
  Drive upload/download checksum match, decryption and isolated restore. Restore
  database dumps only into disposable infrastructure, never production for this test.
- Keep legacy plaintext archives until normal retention or a separately approved
  migration handles them. New native encryption does not retroactively encrypt
  previous archives or establish Veeam image encryption. Do not rotate/delete working
  recovery material simply to make the UI report a cleaner state.
- Rollback cannot mean silently resuming plaintext captures after encryption was
  promised. If an older runtime must be restored, retain ciphertext/key material and
  explicitly stop affected capture jobs until an encryption-capable runtime is ready.
  No schedules have been disabled as part of the work so far.
