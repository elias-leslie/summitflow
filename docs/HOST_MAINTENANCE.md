# Host maintenance and recovery boundary

Host-level checks and maintenance belong to Nightshift (the host steward):
disk and Btrfs health, allocation headroom, SMART and NVMe self-tests, Btrfs
scrubs, core-container checks, Docker/cache/journal housekeeping, and journald
retention. See the Nightshift project for their units, schedules, and alerts.

`scripts/install-host-infra.sh` installs only SummitFlow-specific host pieces:
the backup storage write window (`summitflow-backup-window` and its guard
timer), btrbk log rotation, Docker container log limits, and the
`summitflow-infra-reconcile` user unit that brings up shared Compose
infrastructure without `st` or API dependencies.

## SummitFlow-owned layer

SummitFlow remains responsible for application-aware concerns:

- backup source schedules and retention with minimum restore-point safeguards;
- Veeam job policy and restore-point reporting;
- verified infrastructure/project archives and restore drills;
- PostgreSQL bloat analysis and targeted `VACUUM ANALYZE`;
- application health, runtime hygiene, dashboards, and notification records.

Nightshift may observe and restart foundational services, but it does not
query SummitFlow's database or call its API.

## Schedule

| Control | Schedule |
|---|---|
| Veeam system image | daily at 02:00 |
| SummitFlow daily maintenance | daily at 04:00 |
| Managed restore tests | Sunday at 06:00 |

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
Journal retention is the host policy owned by Nightshift; Codex sync adds no
separate retention policy, daemon, or scheduler.

The legacy `~/.codex/session-integrations/codex-session-sync.log` is preserved
in place and is no longer appended to. Keep it available for diagnostic recovery;
this change does not rotate or delete existing history.

`codex-session-sync.timer` scans every 2 minutes (`--scan`), and
`codex-session-close-inactive.timer` runs `--scan --close-inactive` every
5 minutes. Both services are optional workers, so `st service rebuild summitflow`
renders their `__SUMMITFLOW_ROOT__`. Timers are installed from
`scripts/systemd/*.timer` into `~/.config/systemd/user/`. Change their cadence in
the template, not in a drop-in. An override that sets `OnUnitActiveSec=` to empty
also clears `OnBootSec=`. A monotonic `OnUnitActiveSec=` has no base until the service runs in the current boot, so these timers also use `OnCalendar=`.
`btrfs-autosnapshot.timer` uses `OnCalendar=*:0/30` with `Persistent=true`
for the same reason.

```bash
journalctl --user -u codex-session-sync.service --since '10 days ago'
```

```bash
systemctl list-timers 'summitflow-*'
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
