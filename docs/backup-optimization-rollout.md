# Backup optimization rollout and inventory

Native encrypted age archives remain the production default. Restic is an
explicit pilot until recovery coverage and measured incremental operation pass. Retain legacy
archive readers, retained ciphertext and keys. Preserve the existing Veeam
seven-point image policy. Veeam remains the full-system recovery path; these
backups provide portable source, configuration and data recovery on the same or
a new system.

## Repository and qualification gates

Use restic 0.19.1 and rclone 1.75.1. Keep one encrypted local repository and an
independent encrypted Google Drive repository with separate password custody.
Provision shared chunker parameters, then replicate with native `restic copy`.
Do not mirror raw repository files or build a custom incremental chain. Git
recovery remains a standalone full bundle, optionally reused only after state,
compatibility and checksum validation.

The rollout must retain these distinct gates:

1. Managed acceptance, independent review, fixture deduplication and interrupted,
   corrupt and unavailable-repository tests pass.
2. An operator provisions dedicated Drive OAuth and a bounded remote, verifies
   provider behavior, and saves the offsite password/bootstrap references in
   separate offline custody. These credentials remain pending until that occurs.
3. Seed every enabled source into both repositories. On a fresh VM, recover
   project/Git and configuration payloads from Drive alone without the local
   repository or surviving SummitFlow database/API, and actually load the
   PostgreSQL and Redis data. File extraction alone does not pass. Use the
   [offline repository procedure](local-first-recovery.md#repository-payload-recovery).
4. After the cold-recovery gate, separately qualify offsite retention/prune and
   authorize its bounded policy. This can precede default cutover so maintenance
   traffic is included in observation. Prune qualification is not cutover.
5. Measure a complete normal post-seed incremental cycle, including all enabled
   sources, transfer/structure checks and due maintenance. Include metadata,
   payload scrub reads, critical restore downloads, retention and prune in actual
   total backup traffic, both upload and download; account for the cadence of
   weekly restores and monthly rotating payload checks when judging daily cost.
6. Switch only after recovery/coverage gates pass and measured operation shows
   a substantial reduction against the audited 35.8 GiB/day baseline (17.9
   GiB/day remains the efficiency target). Keep failed or interrupted attempts
   and their traffic in the evidence. Disable the temporary pilot after cutover.

The owner approved this lean rollout on 2026-09-30. A full fresh-OS application
rebuild/four-hour deadline and mandatory seven-day parallel pilot are superseded,
not claimed achieved. The fresh VM is a one-off restore test, not new permanent
infrastructure. Legacy backups, keys, retention protections and the no-purge
rule remain intact.

`new_object_bytes` measures a repository inventory delta. It is not network
traffic and cannot qualify the reduction. Record actual transferred bytes in
both directions across every backup operation, including rclone/HTTP metadata
and maintenance. Missing traffic measurement leaves the cutover gate open.
Record the baseline scope, observation interval and attribution method so
unrelated host traffic is not silently compared with backup-only traffic.

## Opt-in daily pilot and physical measurement

The existing hourly backup workflow can run a separate daily UTC Restic pilot.
Seed traffic is excluded from observation. Before capture, the runner checks
existing verified offsite Restic coverage for every enabled source/backend;
missing coverage marks the whole attempt `seed=true` with `missing_seed_sources`.
This includes the first all-source expansion and newly enabled sources. Only a
later complete run after initial coverage can become a post-seed candidate. The
canonical worker Settings accept these environment variables through the normal
managed service configuration (this document does not enable them):

```text
BACKUP_RESTIC_PILOT_ENABLED=true
BACKUP_RESTIC_PILOT_BACKEND_ID=<explicit enabled nondefault Restic backend ID>
BACKUP_RESTIC_PILOT_DAILY_UTC=02:00
BACKUP_RESTIC_PILOT_INTERFACE=enp8s0
```

The first existing hourly pass after the selected UTC time captures every
enabled source with that explicit backend, irrespective of its native frequency.
Native `last_run`/`next_run` and the production default stay intact. The pilot
attempts each UTC date once; overlapping invocations skip, and an interrupted
attempt is recorded as incomplete on restart. A same-day retry cannot turn that
incomplete date into qualified coverage. Changing the enabled source set during
a run, or an envelope crossing the UTC date, invalidates its daily coverage result
while preserving measured bytes. Pilot maintenance follows the
existing `restic_offsite_prune_qualified` policy: retention/prune remain previews
until that flag is separately authorized after cold recovery. The pilot never
sets or promotes the flag, so scheduling cannot enable destructive operations.

The synchronous envelope starts before capture/copy and ends after all source
outcomes and maintenance. A remaining pending offsite copy gets one synchronous
retry through the existing source lease, and unresolved outcomes fail the day.
A successful retry can complete the day when every source is eventually verified;
failed attempts and their traffic remain in that day's evidence and byte total.
Daily checks, rotating payload reads, weekly
critical restores, retention/prune previews and their child process traffic are
inside the envelope. The selected backend is excluded from ordinary hourly
repository maintenance so those operations cannot escape the envelope through
that scheduler path. Other backends retain their normal maintenance behavior.

Raw `enp8s0` RX and TX counters are sampled before/after operations and every five
seconds while the envelope is active. The journal retains raw first/latest and
operation-boundary counters, sample count and accumulated continuity failures;
periodic samples validate the previous interval without retaining unbounded
sample history. Evidence records UTC and monotonic times,
boot ID, physical device path, interface index/link/MAC and route-table identity.
The interface must be physical and the sole IPv4 default route; an alternate
IPv6 default route is rejected. Missing counters, observed resets, route/device
changes or invalid intervals fail measurement, without substituting zero.
Sampling cannot establish that no transient route change/reset occurred between
samples. This is a **conservative HOST upper bound**, including unrelated and
LAN traffic, not exact backup WAN attribution or repository-object accounting.

The existing private `restic-state/pilot.json` journal stores the active/last
daily attempt and bounded raw samples; `maintenance_runs` workflow `restic_daily_pilot`
stores starts, source checkpoints and final/incomplete evidence. Journal and
history failures cannot produce a successful result. No new daemon, telemetry
service, schema or repository identity field is introduced.

This scheduled envelope alone does not establish complete traffic attribution.
Manual backups, `st backup all --backend`, offsite retries, repository checks and
restores outside it must be suspended during observation or separately audited
and measured. An unaudited/outside operation invalidates that day's qualification;
the runner explicitly records `outside_operations_audited=false` and never
automatically qualifies cutover. Review operation/task/backup history from the
post-seed boundary, retain failed/incomplete intervals and their measured bytes,
and require every enabled source's verified point in the normal incremental
cycle. A complete audited post-seed cycle can support the owner-approved lean
traffic gate, alongside independent recovery and maintenance evidence. Include
failed-attempt traffic; do not select a lower-traffic subset or omit failures.
Preview traffic does not establish the cost of destructive prune; qualification
must measure the separately authorized policy in the same envelope before
default cutover.

`st backup all --backend <ID>` forwards the explicit backend to each enabled
source's existing queued API. The default invocation is unchanged. Its `QUEUED`
output means tasks were submitted, not that offsite coverage or physical
measurement completed; it does not create a scheduled daily pilot evidence row.

## Owner-only Drive authorization

The mounted Google Drive keeps the current backup path working, but its GNOME
login is not an rclone configuration. No Restic backend is registered until the
dedicated rclone remote is authorized, so the scheduler cannot run an incomplete
pilot against it.

Use the [rclone Drive client guide](https://rclone.org/drive/#making-your-own-client-id)
to create or reuse a personal Google OAuth **Desktop app** client with Drive API
enabled. The new repository uses the narrow `drive.file` scope (files created
by this app), not full-account Drive access. Use the existing backup Google
account during consent. For a personal external app, rclone's guide recommends
publishing it rather than leaving it in Testing, whose grant expires after a
week. Do not enable billing or increase quotas without a separate decision.

Run this command yourself in a private terminal on the backup host. The script
asks for the client ID and secret with hidden input, then opens rclone's Google
consent flow. Do not put those values, a token, or the config contents in chat,
shell arguments, task records or screenshots.

```bash
cd /srv/workspaces/projects/summitflow
bash scripts/authorize-backup-drive.sh
```

When rclone asks whether to use a local browser, choose **Y**. Do not choose
the headless **N** path: its suggested command can include the client secret.
If the browser cannot open on this host, stop and ask for a safe headless path.

The script keeps the mode-600 rclone config inside the canonical private
backup-key directory and checks that authorization can list the
app-visible Drive root without printing filenames. It does not create a backup
backend, repository or Drive folder, or change the default. When it prints
`AUTH_READY`, report only the remote name and config path. If consent was
interrupted, run the same script again in your private terminal. It will reuse
the private dedicated config, clear inherited tool overrides and repeat its
permission/access checks. The later pilot will generate independent repository
passwords without displaying them; offline custody of those passwords and
this config is still required before cold recovery qualifies.

The reserved pilot references are the new local repository at
`/media/kasadis/Backups/davion-gem/restic`, the new bounded Drive repository
`rclone:summitflow-drive:SummitFlow-Restic`, and separate password files named
`restic-local.password` and `restic-drive.password` directly inside the private
backup-key directory. These paths were available at preparation time; no
repository, password file or Drive folder is created by this document or the
authorization helper. The existing native backend remains default while the
pilot is seeded, recovered and measured.

Retention keeps daily recovery points for each source's configured 7/14/30-day
window. Preserve minimum-three, pins, last-good points and pending verification
protection. No global Drive cleanup, account-wide deletion or local purge is
part of this implementation. The separate offline offsite key escrow, cold
recovery and observation gates cannot be replaced with code or fixture success.

## Keep and exclude without removing originals

Preserve `.codex` and `.claude` conversations/transcripts, plans, skills, settings,
WIP and durable state. Register canonical configuration/skills separately and
capture `.claude.json` as an explicit regular file. Keep Git history, refs and
the exact staged index, alongside unstaged and untracked files. Exclude backup
private keys and rclone credential references from source captures; their
separate custody is a recovery prerequisite.

AfterTimes must retain source art, editable originals, source code, licensing,
manifests, import originals with unproven replaceability, and unfinished work.
Broad text/JSONL/manifest/asset exclusions cannot establish disposable output.
Downloaded caches, reproducible release packages and generated output can be
excluded using bounded paths. An exclusion changes future backup contents; it
does not authorize deleting local files or old archives.

## Read-only local inventory

Run the metadata inventory only with explicit narrow roots. It lists names,
`lstat` sizes, allocated blocks and modification ages. It never opens file
contents, traverses symlinks, reads credential-named entries or removes files.
Use private output storage because filenames can identify projects or sessions:

```bash
umask 077
python3 scripts/backup-cleanup-inventory.py \
  --root /home/kasadis/.codex \
  --root /home/kasadis/.claude \
  --root /srv/workspaces/projects/the-aftertimes \
  --older-than-days 30 \
  > /srv/private-review/backup-cleanup-inventory.json
```

The output parent must already exist. `--max-entries` bounds traversal; a
truncated or unreadable inventory has `complete: false` and a nonzero exit.
Allocated bytes count hard-linked inodes once, but filesystem compression,
reflinks and shared blocks can make this an estimate rather than reclaimable
space.

Protected transcripts, Git, durable state, originals and licensing take
precedence over cache/log/output path names. Unknown files remain protected.
`review-generated`, `review-diagnostic-log` and `review-release-status` are
review queues. File age does not establish inactivity. Use the managed service
release inventory to identify current/previous/installed releases; pass known
active or retained paths with `--protected-path` so the report preserves them.
Inactive downloaded release packages, caches, diagnostic logs and temporary
output remain candidates only after that separate review.

The tool has no deletion mode. A later cleanup needs explicit targets,
replaceability evidence and separate authorization. It does not inspect Veeam
repositories or infer which image points can be discarded.
