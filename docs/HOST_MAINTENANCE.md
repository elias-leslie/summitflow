# Host maintenance and recovery boundary

The host uses two deliberately separate maintenance layers.

## Native, independent layer

These controls must continue to work when SummitFlow, PostgreSQL, Hatchet, or
Agent Hub is unavailable. `scripts/install-host-maintenance.sh` installs a copy
of the standard-library-only guardian into `/usr/local/libexec` and installs
native systemd timers for:

- 15-minute disk (root, workspaces, backup drive, native btrbk target), Btrfs device-error (all three Btrfs filesystems), SMART, Veeam, Docker, PostgreSQL, and core-container checks;
- direct Docker Compose reconciliation of shared infrastructure, without `st` or API dependencies;
- daily age-gated Docker/cache/log maintenance;
- weekly/monthly NVMe self-tests;
- monthly Btrfs checksum scrubs, staggered per filesystem and serialized by a shared lock;
- bounded journald and Docker log growth.

Current state is written atomically to
`/var/lib/summitflow-host-guardian/status.json`. State transitions are appended
to `events.jsonl` as a durable record that survives a database or network
outage.

## SummitFlow-owned layer

SummitFlow remains responsible for application-aware concerns:

- backup source schedules and retention with minimum restore-point safeguards;
- Veeam job policy and restore-point reporting;
- verified infrastructure/project archives and restore drills;
- PostgreSQL bloat analysis and targeted `VACUUM ANALYZE`;
- application health, runtime hygiene, dashboards, and notification records.

The native guardian may observe and restart foundational services, but it does
not query SummitFlow's database or call its API. SummitFlow may consume the
guardian's JSON status, but native maintenance never consumes SummitFlow.

## Schedule

| Control | Schedule |
|---|---|
| Host guard and core reconcile | every 15 minutes |
| Host retention maintenance | daily around 05:15 |
| Veeam system image | daily at 02:00 |
| SummitFlow daily maintenance | daily at 04:00 |
| Managed restore tests | Sunday at 06:00 |
| Btrfs scrub `/` | first Sunday around 08:00 |
| Btrfs scrub `/srv/workspaces` | second Sunday around 08:00 |
| Btrfs scrub native target `/mnt/summitflow-native` | third Sunday around 08:00 (skipped when the drive is absent) |
| NVMe short self-test | Saturday around 03:00 |
| NVMe extended self-test | first Saturday around 00:30 |

## Capacity and retention policy

- `SummitFlowSystemImage` keeps 7 Veeam restore points. The 1.9 TB backup target
  is shared with managed project archives, and recent system-image increments
  are large enough that the former 14-point target did not leave safe headroom.
- Veeam chain files are retired only by Veeam's supported retention pass. A
  policy change may spend hours merging a forward-incremental chain even after
  `df` shows that old chains have already been reclaimed.
- SummitFlow's daily maintenance removes Btrfs `.veeam_snapshots` only after 6
  hours and skips the cleanup while a Veeam session is active. These temporary
  snapshots can pin otherwise-deleted root filesystem blocks.
- Unreferenced anonymous Docker volumes retain a 48-hour grace period. Do not
  bypass it during active agent work merely because a volume currently appears
  dangling.

## Operator commands

Codex session sync writes one status summary per scan to stdout, and warnings
and errors to stderr. `synced` counts successful session operations (including
heartbeats); `warnings` counts warnings emitted during the scan. The periodic
user service sends both streams to the journal without per-session verbose
output. Direct CLI calls can add `--verbose` for per-session success details.
The existing host journal policy (`20-storage-guardrails.conf`) limits journals
to 500 MB, keeps 5 GB free, and retains entries for at most 14 days; Codex sync
adds no separate retention policy, daemon, or scheduler.

The legacy `~/.codex/session-integrations/codex-session-sync.log` is preserved
in place and is no longer appended to. Keep it available for diagnostic recovery;
this change does not rotate or delete existing history. This auxiliary unit is
outside the project's declared managed service set, so a managed project rebuild
alone does not update it. Owner-authorized adoption must render the service
template's `__SUMMITFLOW_ROOT__` to the checkout root in the installed user unit
and reload the user systemd manager. The next timer tick uses the new arguments
without restarting the timer. The checkout-backed script uses journal-compatible
streams immediately; until template adoption, the installed service still
requests per-session output.

```bash
journalctl --user -u codex-session-sync.service --since '10 days ago'
```

```bash
sudo systemctl start summitflow-host-guardian.service
sudo systemctl start summitflow-host-maintenance.service
sudo systemctl start summitflow-btrfs-scrub.service
cat /var/lib/summitflow-host-guardian/status.json
systemctl list-timers 'summitflow-*'
journalctl -u summitflow-host-guardian.service -n 100
st backup veeam status
st backup veeam start --wait
```

Do not manually delete Veeam chain files, named Docker volumes, PostgreSQL data,
or Btrfs snapshots. Use the owning retention/recovery workflow.

## Backup accident guards

These guard against mistakes (an agent's stray command or a bad retention
setting), not against a hostile root user.

- **T7 read-only outside backup windows.** `/media/kasadis/Backups/davion-gem`
  (restic repository, native archives) and `/mnt/summitflow-native` (btrbk
  target) are read-only except while a backup job writes. Jobs open the window
  through the root-owned `/usr/local/sbin/summitflow-backup-window`
  (`open|close NAME PID`, `run NAME -- CMD`, `status`, `guard`);
  `summitflow-backup-window-guard.timer` returns storage to read-only every five
  minutes once no live holder remains, so a crashed job cannot leave it
  writable. Only the per-mount flag changes; the filesystems stay mounted.
- **Deletion circuit breaker.** Local and offsite restic retention, native
  archive cleanup, native Drive retention and btrbk target expiry refuse any
  run that removes more than normal retention (by default more than 25% of all
  points or 50% of one source; btrbk: more than a third). The points are kept,
  backups continue (btrbk runs with `--preserve-backups`), and a SummitFlow
  notification is raised. Prune is skipped when snapshots disappeared outside
  retention, keeping their data recoverable. After checking the cause, allow
  one run with `st backup storage approve-deletion <kind> --reason "..."`.
- **Drive deletes go to trash.** Offsite restic prune and native Drive expiry
  use the Drive trash (30 days) instead of permanent deletion.
- **Append-only PVE copy.** CT 160 on davion-gem holds a third copy of the
  local restic repository; the workstation key can add snapshots but not
  delete them, and retention runs only on PVE. It is the first thing to remove
  when davion-gem needs space: see `scripts/pve-restic-append/README.txt`.
- **Health.** Every scheduler tick re-reads the daily rotating
  `restic check --read-data-subset` results (failed or older than three days
  raises an alert). Weekly: snapshot-count and repository-size drops and a test
  restore from the PVE copy.
- **T7 stays mounted.** The read-only overlay on `davion-gem` keeps the NTFS
  partition busy, so its automount no longer idle-unmounts after ten minutes.

Status for watchers (Nightshift): `~/.local/state/summitflow/backup-safety/status.json`
(`st backup storage safety`). Top-level `status` is `ok` or `alert`; `alerts`
lists each active condition with `key`, `kind`, `message` and `since`.

`/srv/workspaces` and `/srv/scratch` share one Btrfs filesystem and no longer
mount with `user_subvol_rm_allowed` (effective from the next full mount, i.e.
reboot); owners remove writable subvolumes by emptying them instead.
