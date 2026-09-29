# Backup optimization rollout and inventory

Native encrypted age archives remain the production default. Restic is an
explicit pilot until qualification and measured observation pass. Retain legacy
archive readers, retained ciphertext and keys. Preserve the existing Veeam
seven-point image policy; Veeam's role in a future recovery design needs review
before any policy change.

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
3. A fresh-OS recovery succeeds from Drive alone, with no local repository or
   surviving SummitFlow database/API, and recovers essential sources/state with
   the agreed critical functions validated within four hours. File extraction
   alone does not pass. Use the [offline repository procedure](local-first-recovery.md#repository-payload-recovery).
4. After the cold-recovery gate, separately qualify offsite retention/prune and
   authorize its bounded policy. This can precede default cutover so maintenance
   traffic is included in observation. Prune qualification is not cutover.
5. Observe at least seven post-seed days with every enabled source's daily
   offsite coverage, daily transfer/structure checks, deterministic monthly
   payload coverage over 30 successful runs, and weekly critical recovery tests.
   Include metadata operations, payload scrub reads, critical restore downloads,
   retention and prune in actual total backup WAN bytes, both upload and download.
6. Switch the default only after that total averages at most 17.9 GiB/day,
   at least 50% below the audited 35.8 GiB/day baseline, and all recovery/coverage
   gates pass. Keep failed or interrupted runs and their traffic in the evidence.

`new_object_bytes` measures a repository inventory delta. It is not network
traffic and cannot qualify the reduction. Record actual transferred bytes in
both directions across every backup operation, including rclone/HTTP metadata
and maintenance. Missing traffic measurement leaves the cutover gate open.
Record the baseline scope, observation interval and attribution method so
unrelated host traffic is not silently compared with backup-only traffic.

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
