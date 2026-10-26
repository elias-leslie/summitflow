# Host maintenance and recovery boundary

Host-level checks and maintenance belong to Nightshift (the host steward):
disk and Btrfs health, allocation headroom, SMART and NVMe self-tests, Btrfs
scrubs, core-container checks, Docker/cache/journal housekeeping, and journald
retention. See the Nightshift project for their units, schedules, and alerts.

`scripts/install-host-infra.sh` installs only SummitFlow-specific host pieces:
the backup storage write window (`summitflow-backup-window` and its guard
timer), the host backup timer (`summitflow-host-backup.timer`), btrbk log rotation, Docker container log limits, and the
`summitflow-infra-reconcile` user unit that brings up shared Compose
infrastructure without `st` or API dependencies.

## SummitFlow-owned layer

SummitFlow remains responsible for application-aware concerns:

- the host backup: btrbk points on the T7 every 4 hours and one daily restic copy
  of those snapshots into Google Drive, both started by
  `summitflow-host-backup.timer` (see [host recovery](native-host-recovery.md));
- the hourly backup health check that raises an alert only for a recovery point
  that is really missing or a failed Drive check;
- PostgreSQL bloat analysis and targeted `VACUUM ANALYZE`;
- application health, runtime hygiene, dashboards, and notification records.

Nightshift may observe and restart foundational services, but it does not
query SummitFlow's database or call its API.

## Schedule

| Control | Schedule |
|---|---|
| Host backup: btrbk to the T7 | `summitflow-host-backup.timer`, 02:30 and every 4 hours after |
| Google Drive copy (restic) | once a day, in one of those runs; a missed day is made up at the next run |
| Drive read-back (check, test restore, cleanup) | `summitflow-host-verify.timer`, Sundays 05:00, each step stopped at its own time limit |
| Backup health check | hourly, at :30 |
| Project autosnapshots | every 30 minutes |
| SummitFlow daily maintenance | daily at 04:00 |

## Capacity and retention policy

- btrbk keeps the latest point on each source and 7 daily points on the T7
  (`/etc/btrbk/summitflow.conf`). The Drive repository keeps 7 daily, 4 weekly
  and 3 monthly snapshots per job. A separate weekly job
  (`summitflow-host-verify.timer`, low priority, never inside the backup unit) reads
  back a random 500 MB of the stored data, streams out the newest PostgreSQL dump,
  restores a few project files, and prunes in small repacks. Each step stops at a
  wall-clock limit (15, 20, 10 and 30 minutes) and records "partial" instead of
  failing; the next week continues. Drive's speed therefore never delays a backup.
- Veeam is not installed. Its old chain on the T7 (`VeeamBackup/`) is the
  owner's to keep or delete; nothing reads or prunes it.
- Docker pruning is Nightshift's weekly stack prune (stopped containers older
  than 48 hours, build cache older than 7 days, dangling images). SummitFlow
  does not prune Docker and has no Docker retention settings. Named and
  anonymous volumes are never pruned automatically.
- Project autosnapshots are whole-`@workspaces` points, so retention is per
  point: every point from the last 6 hours, one per hour to 24 hours, one per
  day to 3 days (btrbk keeps the off-machine dailies). Pins, active recovery
  copies and unclassified state hold a point; a deleted project keeps its
  newest point 14 days. `st autosnap prune` deletes at most 15 points per run,
  oldest first, pausing between batches of 5, and exits 1 when any deletion is
  deferred. `--pressure` keeps only the newest 3 points; `--max-deletes N`
  changes the cap. It also reaps old unrecorded read-only points in the store.
  A directory the sweep cannot read is skipped unless it is the project, inside
  it or above it; then only that project fails. Each sweep writes
  `~/.local/share/st/snaps/autosnap-state.json` (`last_sweep_at`,
  `last_sweep_result`, `newest_point_at`, per-project newest point,
  `stale_after_hours`), which the Backups page and Nightshift's stale-snapshot
  alert read.
- Host maintenance checks pressure on `/` and on the scratch filesystem. When
  scratch is under pressure it runs `st cleanup reclaim` steps at once: `uv
  cache prune`, `pnpm store prune`, Hugging Face repos unchanged for 30 days,
  then the weekly scratch retention (7-day age,
  `SF_HOST_RETENTION_SCRATCH_PRESSURE_MAX_AGE_HOURS`) without waiting for the
  week, so idle owner work in scratch is not cut short. The cache roots under
  `/srv/scratch/cache` stay. `st cleanup reclaim --filesystem /srv/scratch
  --target-free-gib N` runs the same steps on demand and stops at the target.
- Backups publish `~/.local/state/summitflow/backup-freshness/sources.json`
  after each backup run and health check: active alert conditions, whether
  capture is refused for disk space (and since when), and the freshness of the
  btrbk layer, the Drive layer and each Proxmox job.

## Operator commands

Codex session sync and the inactive-session closer belong to Agent Hub
(`codex-session-sync.timer`, `codex-session-close-inactive.timer`, installed by
`st service rebuild agent-hub`). Their scan window and the close switch are
Agent Hub session close settings (Sessions page, Closing). See Agent Hub's
`scripts/codex-session-sync.py`.

The optional SummitFlow managed Codex recorder and outbox drain are retired.
They are no longer installed by `st service rebuild summitflow`. Retain existing
outboxes, private staged runtimes and history until the owner has checked pending
delivery and preserved any undelivered evidence. See
[the retirement boundary](architecture/managed-codex-sessions.md).

A monotonic `OnUnitActiveSec=` has no base until the service runs in the current
boot, so host timers use `OnCalendar=`.
`btrfs-autosnapshot.timer` uses `OnCalendar=*:0/30` with `Persistent=true`
for the same reason.

```bash
systemctl list-timers 'summitflow-*'
st backup status
st backup host status
st autosnap sweep
```

Do not manually delete Veeam chain files, named Docker volumes, PostgreSQL data,
or Btrfs snapshots. Use the owning retention/recovery workflow.

## Backup accident guards

These guard against mistakes (an agent's stray command or a bad retention
setting), not against a hostile root user.

- **T7 read-only outside backup windows.** `/mnt/summitflow-native` (btrbk
  target) and the old restic repository under `/media/kasadis/Backups/davion-gem`
  are read-only except while a backup job writes. The host backup opens the window
  through the root-owned `/usr/local/sbin/summitflow-backup-window`
  (`open|close NAME PID`, `run NAME -- CMD`, `status`, `guard`);
  `summitflow-backup-window-guard.timer` returns storage to read-only every five
  minutes once no live holder remains, so a crashed job cannot leave it
  writable. Only the per-mount flag changes; the filesystems stay mounted.
- **Deletion circuit breaker.** btrbk target expiry refuses any run that removes
  more than normal retention (more than a third of the points, by default). The
  points are kept, backups continue (btrbk runs with `--preserve-backups`), and
  a SummitFlow notification is raised. Fix the retention setting so the next run
  stays within normal retention. An oversized run stays blocked until the owner
  approves it in chat; the agent then runs
  `st backup approve-deletion <kind> --target <target> --owner-approved "<owner's words, date>"`
  (kind and target from `st backup safety`), which lets the next run of that kind
  and target through once (no bigger than the refused plan, within 48 hours). The
  approval is spent on use and recorded in the safety status (`approval_log`) and
  in a notification. No Nightshift step is involved.
- **Drive deletes go to trash.** The Drive job's forget and prune use the Drive
  trash (30 days) instead of permanent deletion. Its retention is fixed in code
  (7 daily, 4 weekly, 3 monthly).
- **Old backups.** The restic repository on the T7 and the per-project snapshots in
  Drive from before the daily job are no longer written to. The Drive ones age
  out after 30 days once the daily job has run well for a few days; the T7
  repository is the owner's to delete (`st backup old list --where local` shows
  its path and size). CT 160 on davion-gem still holds the append-only copy of
  that old repository; nothing new goes into it. It is the first thing to remove
  when davion-gem needs space: see `scripts/pve-restic-append/README.txt`.
- **Proxmox captures use their own key.** The `proxmox://` sources (cluster
  config, guest files, host files) are jobs of the daily Drive run. They reach
  davion-gem only with `pve-backup.ed25519` in the backup key directory, bound
  to the fixed dispatcher `/usr/local/sbin/summitflow-pve-backup` (verbs
  `guests`, `thinpool`, `sources`, `capture SOURCE DIGEST`). What each source
  captures is the list root installs on PVE, so adding or changing a
  `proxmox://` source needs `sudo scripts/pve-backup/install.sh` before it runs.
  The installer shows the committed dispatcher's sha256 and the list against the
  installed one, and installs nothing until confirmed: `y` at a terminal, or,
  with no terminal, a re-run with `--yes DIGEST`, where DIGEST is the
  `Approval digest` the first run printed for exactly that dispatcher and
  list. The config dump leaves out `priv/` and every `*.key` file; PVE
  regenerates them on restore. Host paths must be exactly one of
  `/vault/identity`, `/vault/meta/recovery-key.json`,
  `/etc/pve/qemu-server/120.conf` and the two
  `/var/lib/vz/snippets/neri-120-*.yaml` files; any other host path needs a
  dispatcher release (`HOST_PATHS`). The
  dispatcher still refuses `*.key` files and anything under config.db, the
  `/etc/pve` priv directories, `/root`, `/etc/ssh` or `/etc/corosync`, and it
  never captures CT 150 (OmniNull) or CT 160 (append-only restic). Guest
  files are read only through the dispatcher (`via=pct` or `via=agent`),
  never over an ssh alias.
- **Health.** The hourly check raises an alert for a missing local point (none
  in 26 hours), a missing Drive copy (none in 48 hours), two failed weekly data checks
  or test restores in a row, or a Drive cleanup that has failed for three weeks. A slow or retried run is not an alert. `st backup status` shows
  the same list.
- **T7 stays mounted.** The read-only overlay on `davion-gem` keeps the NTFS
  partition busy, so its automount no longer idle-unmounts after ten minutes.

Status for watchers (Nightshift): `~/.local/state/summitflow/backup-safety/status.json`
(`st backup safety`). Top-level `status` is `ok` or `alert`; `alerts`
lists each active condition with `key`, `kind`, `message` and `since`.

`/srv/workspaces` and `/srv/scratch` share one Btrfs filesystem and no longer
mount with `user_subvol_rm_allowed` (effective from the next full mount, i.e.
reboot); owners remove writable subvolumes by emptying them instead.
