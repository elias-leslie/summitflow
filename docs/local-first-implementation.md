# Local-first implementation record

Task: `task-a6bee0c09e0e4a3c`. Owner: this orchestrator session.

This is the implementation checklist and evidence record for the owner's approved
workflow change, not a new reusable instruction store. GitHub publication is not
requested. Existing security controls, histories, unrelated work, and necessary
live validation must remain protected.

## Completion checklist

An unchecked item remains outstanding. Implementation alone does not establish
verification; record actual evidence before checking an item.

Current phase: implementation and focused regression coverage are present;
integration acceptance and managed rollout are still pending. No production
recovery key has been generated and no encrypted Drive backup or live restore has
been claimed as complete. Key custody will require the owner to save and submit
their saved copy through the authenticated UI.

### Local commits, integration, and validation

- [ ] Local commits are the default; explicit publication remains available.
- [ ] Frequent checkpoint commits use appropriate fast feedback and secret guards.
- [ ] Local commits are associated with their task immediately.
- [ ] Manual and autonomous execution preserve local work without a push.
- [ ] Acceptance checks run against the actual integrated source being accepted.
- [ ] Evidence records source, dependency/configuration inputs, scope, and results.
- [ ] Matching validation evidence is reused; changed inputs invalidate it.
- [ ] Full relevant tests, builds, fresh schema/migrations, package and context
      integration checks can run locally through the existing check surface.
- [ ] Existing local security scanners are usable through ST; findings and CodeQL
      coverage differences remain explicit, with no claim of unproved equivalence.
- [ ] Existing leases remain effective; commit/acceptance/deployment concurrency
      cannot overwrite other work or silently validate a different candidate.

### Completion and optional publication

- [ ] Local acceptance, required deployment, and required live validation determine
      completion; publication is independent.
- [ ] Missing required acceptance keeps the task open with an accurate reason.
- [ ] Closeout records completion promptly and idempotently; agents report actual
      persisted state rather than equating a merge or queued job with success.
- [ ] Optional publication adopts an existing same-source PR/receipt rather than
      creating a duplicate to repair task linkage.
- [ ] Later publication preserves newer local work and existing GitHub protections.
- [ ] Pending historical publication requests are preserved and safely reconciled.
- [ ] Local search/index refresh and cleanup no longer depend on publication.

### Managed deployment

- [ ] Managed rebuild accepts stable, accepted source and identifies its revision.
- [ ] Runtime cannot accidentally import later unaccepted development edits.
- [ ] Receipts bind source/build identity, migrations, restart/health and applicable
      live checks; queued work is never reported as completed.
- [ ] Previous release remains recoverable; database migration rollback limits are
      explicit. No new per-task services or ports.
- [ ] Required workers and current deployment destinations retain their safeguards.

### Independent recovery

- [ ] Backups preserve full unpublished Git history/refs and applicable JJ metadata.
- [ ] Staged, unstaged, valuable untracked/ignored work, and safe symlinks survive.
- [ ] Backup capture is consistent with concurrent repository writes.
- [ ] Required source/config/packaged dependencies have recoverable local copies.
- [ ] Task metadata, prompts/memory, PostgreSQL and valuable SQLite state, evidence,
      required secrets/configuration and encryption-key recovery are accounted for.
- [ ] Existing backup disk/Veeam/schedules are reused; actual retention is verified.
- [ ] Snapshot workspace configuration and observed lack of snapshots are resolved.
- [ ] Sensitive archives are protected without exposing or committing secrets.
- [ ] Capture each source once locally, then encrypt and replicate that completed
      archive to Drive under the same backup record. Failed transfer retries reuse
      the existing artifact and do not trigger a second source/database backup.
- [ ] An isolated restore proves history, work, database state, and runnable software
      without relying on GitHub or mutating production databases.
- [ ] Google Drive is an implemented offsite destination using the existing
      connection where available, encrypted completed archives, verified retention,
      and a download/decrypt/restore demonstration. Identify any missing machine
      credential or key-custody requirement explicitly; connection alone is not proof.
- [ ] All real SummitFlow-managed/backed-up solutions have explicit local and Drive
      coverage; intentionally disabled fixtures are distinguished from missing coverage.
- [ ] SummitFlow's existing backup UI shows separate local/Drive status, failures,
      source coverage, retention and restore evidence with appropriate recovery controls.
- [ ] Provide the actual encryption recovery key as a restricted separate file for
      the owner's password manager and verify it decrypts a downloaded archive.
- [ ] New native local and Drive archives are both encrypted: one ciphertext
      artifact, not independent captures or independent encryption passes.
- [ ] Key setup generates once, allows deliberate download/copy/reveal through the
      existing Cloudflare Access owner session, and proves a saved copy can decrypt.
      No new authentication challenge. No secrets in logs, query caches or browser storage.
- [ ] Later key retrieval uses the same authenticated owner controls; no destructive
      key regeneration. Recovery-key directory is excluded from encrypted archives.
- [ ] Actual owner custody is confirmed by the owner, not inferred from agent tests.

### Agent behavior and independence

- [ ] Canonical scoped DB prompts and computed capabilities reflect local-first
      defaults; effective context is previewed before and after changes.
- [x] Authentication scope bounded: the example's one-off Agent Hub Codex OAuth
      repair/human login wait is not a recurring workflow defect. No auth-flow
      redesign or claimed savings from removing that necessary wait.
- [ ] Validation reuses tested secret-safe helpers and supported model/environment
      capabilities rather than repeating the observed helper/model mistakes.
- [ ] Account-specific GitHub dependencies are distinguished from upstream GitHub,
      registries, model providers and actual deployment destination dependencies.
- [ ] No-account and no-GitHub tests are non-destructive and isolated.
- [ ] Later publication is tested locally against a disposable remote; actual GitHub
      publication remains a separate owner decision.
- [ ] Independent review and canonical quality gates pass.
- [ ] Actual managed runtime behavior is exercised after authorized rebuild.
- [ ] Task is closed locally only after all required work is verified.

### Performance and token impact

- [ ] Measure baseline and changed fast-checkpoint, full acceptance, acceptance
      reuse, deployment and closeout durations; distinguish CPU work, remote waits,
      authorization waits and necessary live validation.
- [ ] Record check/tool-call counts and avoid repeated full gates for the same
      immutable inputs. Every continuing administrative step needs a concrete purpose.
- [ ] Include redundant tool invocations, repeated reads, and unnecessarily broad
      tool output in the overhead comparison; consolidate related read-only queries
      and return bounded evidence, preserving required inspect-before-act boundaries.
- [ ] Quantify removed recurring workflow steps (duplicate PR/CI,
      polling, redundant validation and administrative agent exchanges), separating
      measured time/token savings from modeled savings and necessary retained work.
- [ ] Preview effective instructions before/after and measure injected context size;
      use observed token usage when available, explicitly label estimates otherwise.
- [ ] Profile one local backup capture, encryption, Drive upload/download and
      isolated restore: elapsed time, bytes and retry behavior, without a second capture.
- [ ] Document residual costs and evidence-based simplifications for one developer
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

## Everyday workflow after verified rollout

### Final gate repair evidence

- Full Python typing now passes. Runtime owner-module facades needed explicit
  source-adjacent re-export stubs; no type ignores, `Any` escape hatches or runtime
  behavior changes were used to hide the 356 diagnostics.
- Patched dependency locks were synced into the actual development environments.
  OSV now reports zero findings; 991 focused backend tests, 188 frontend tests and
  TypeScript passed against those versions. The narrow esbuild 0.28.1 override
  still needs the real managed production build, including notes-ui, before rollout
  can be called verified.
- Quick checkpoints now run directly attributable tests and explicitly defer
  cross-cutting configuration coverage to mandatory full acceptance. Explicit
  full checks retain the complete suite; lint, types and secret checks remain.
  The refinement passed 167 focused tests. This avoids converting every lockfile
  checkpoint into another broad test cycle without weakening final acceptance.
- Candidate gitleaks passes after replacing misleading fake-token fixture strings;
  no allowlist or detection rule was disabled. Drive retention now preserves both
  the just-verified object and the newest recovery point, including an old archive
  retried after an outage. Twenty focused backup tests passed.

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
