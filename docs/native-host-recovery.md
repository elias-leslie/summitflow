# Linux host recovery

btrbk is the only local backup. It snapshots six Btrfs subvolumes (`/`, `/home`,
`/srv/workspaces`, `/var/lib/docker`, `/srv/models`, `/var/log`) and sends them to
the plain Btrfs T7 every 4 hours. Seven daily points are kept, plus the newest.
The daily Google Drive copy reads those same snapshots; see the
[hard-loss runbook](disaster-recovery.md) and [cold recovery from
Drive](local-first-recovery.md). Windows keeps its own Veeam backup. Linux Veeam
is off: it cannot capture this host's compressed Btrfs layout. Git checkpoints
and `st snaps` cover code between host backups.

## What runs

`summitflow-host-backup.timer` (a systemd user timer, 02:30 and every 4 hours
after) starts `summitflow-host-backup.service`. One run takes the host backup
lock, runs btrbk, and, once a day, lets restic read the new snapshots into Drive.
`st backup run` starts the same unit now. The run stands down while the machine
is under memory pressure; the next slot does the work.

`st backup status` says whether the points are current. `st backup host status`
reports installation, coverage, admission, the latest capture and its evidence.
**Ready to capture** does not establish a tested restore. `st backup host run
--dry-run` does the preflight without capturing. The adapter runs only when
`BACKUP_BTRBK_ENABLED=true`.

The reviewed root-owned nonsecret configuration is `/etc/btrbk/summitflow.conf`,
readable by the service user with mode `0644`; start from
`scripts/systemd/btrbk.conf.example`. Keep the package's own btrbk timer
disabled: the SummitFlow timer is the only schedule. The destination must be an
independently mounted Btrfs filesystem with compression enabled, and the
snapshot directories must already exist. Validate the source/target relations
and a dry run before enabling.

## Coverage

Every durable nested subvolume needs its own section because Btrfs snapshots are
not recursive. Managed work points are excluded as nested snapshot boundaries.
A snapshot of PostgreSQL's data files is not a database backup: the daily Drive
job streams a `pg_dumpall` of the shared stack straight into the repository
(`st backup show postgres`).

Drive reads only `/srv/workspaces`, `/home` and the system folders of `/` (`/etc`,
`/root`, `/opt`, `/usr/local`, `/var/spool`). Docker images, `/srv/models` and
`/var/log` stay on the T7 only.

## Capacity

The configuration keeps seven daily destination points and the incremental
parents each source needs. Each capture carries matching boot/EFI files, the
observed disk layout and a receipt. Matching boot files are retired together with
their native points, not by folder age. A failed deletion keeps its receipt and
error.

Admission uses the host pressure policy and measured capacity. An unqualified
target or too little headroom prevents a capture. It also reads Btrfs device
allocation (`btrfs filesystem usage`) on every source and the target: free space
can hide exhausted metadata allocation, so a filesystem with under 8 GiB
unallocated, or a missing device, blocks the capture. Reclaiming allocation is
Nightshift's host maintenance, not the backup's.

Initial admission reserves a full source-filesystem footprint, the matching boot
allocation and the existing 25 GiB reserve for every run. That is full-reseed
headroom, not a forecast of incremental growth. Measure real incremental growth
on the final destination before relying on it, keep full and incremental
measurements apart, and revalidate incremental parents under the operation lock.
A missing parent needs full admission or a refusal. Previewed native expiry must
stay possible when a capture does not fit. Do not weaken this guard with a small
fixture result.

Ubuntu Noble's btrbk 0.32.5 uses the standard send protocol; destination
compression and native incremental sharing still apply. A compressed-stream
configuration needs a btrbk version that supports those options, verified on the
installed kernel and tools.

## Selective recovery

`st snaps` lists saved-work points. `st recover POINT --project PROJECT` opens a
read-only side copy and prints its actual location. Selected-file preview/apply
uses `st recover --help`: application requires an active owned claim, declared
paths, leases and unchanged preview digests. Git metadata and classified durable
data are excluded from source application. HTTP application is refused because
it cannot establish native coding-session ownership.

Releasing recovery protection makes the side copy eligible for the same pruning
lifecycle. A deletion failure remains visible and protects the source point.
Whole shared-workspace or production-root rollback is refused. Release rollback
uses an accepted application release compatible with the current database;
database restoration is separately authorized application recovery.

Project identity `storage.durable_data` and `storage.disposable_outputs` contain
specific relative roots. Unclassified data, assets and ignored work remain
preserved. Tracked fixtures override disposable defaults. Do not classify a
whole `data`, `artifacts` or asset directory by its name alone.

## Physical recovery and cutover

Before Windows resizing, retain verified independent native Linux recovery,
matching boot/layout evidence, portable SQL recovery and independent access.
The migration gate may use the verified native baseline plus independently
restored current-source, consistent database and durable-file supplements. Record
their source bindings and limits explicitly; that composite is not a new full
host point. Preserve its incremental source parents through permanent cutover.
In Windows, complete a fresh Veeam point in the existing Windows chain, verify
filesystem/BitLocker status and supported shrink geometry, then shrink only the
Windows system partition by about 250 GB. Leave the space unallocated and return
to Linux. Linux boot, swap, current Btrfs and Windows recovery partitions remain
untouched during that step.

Linux prepares a separate Btrfs `/srv/workspaces` filesystem at the same path.
Pause writers for the final consistent copy, verify content and metadata, switch
the mount, resume managed services and verify work recovery plus backup coverage.
Keep the original until those checks pass.

The external drive then receives the approved approximate 1 TB NTFS / 1 TB
plain Btrfs layout, preserving NTFS when practical. Existing retained files
must have independently verified staging before any destructive recreation.
The Windows chain remains protected until workspace expansion passes; finish
with a fresh Windows Veeam full and Linux native recovery qualification.

The owner's USB must be attached and identified before writing recovery media.
Check its device identity, preserve any still-needed recovery material and verify
boot/access against the actual physical host. The isolated UEFI clone boot test
does not replace a physical USB or blank-disk recovery test.

## Owner Btrfs qualification

Ordinary hermetic acceptance excludes exactly two physical snapshot cases and
records `owner-btrfs-snapshots` as not applicable. All saved-work unit tests remain
applicable, and unexpected skips still block acceptance. These physical cases
require a fresh owner-authorized Btrfs subvolume under
`/run/sf-recovery-source/snapshot-tests-release-*`, verified source filesystem
identity, and bounded deletion privilege for their isolated restore fixture.
They must never target existing workspaces or retained recovery points.

After preparing that fresh fixture, invoke both cases through ST (pytest node
paths are relative to its backend work directory):

```sh
ST_SNAPSHOT_TEST_ROOT=/run/sf-recovery-source/snapshot-tests-release-<unique> st check pytest -- tests/cli/test_saved_work_snapshots.py::test_native_btrfs_shared_capture_readonly_recovery_and_isolated_restore tests/cli/test_saved_work_snapshots.py::test_native_nested_saved_source_is_refused_and_disposable_tracked_fixture_preserved -q
```

Retain the two-case result, actual source HEAD and implementation hashes, then
remove only that operation's fixture subvolumes. The tests confine their smaller
free-space floor to the isolated source; production keeps its existing reserve.
The renewed `2566b89f5792` qualification passed both cases with unchanged
implementation hashes and verified cleanup; its retained receipt is
`~/.local/state/summitflow/recovery/backup-migration-20261005/snapshot-release-qualification/receipt.json`.
That hardware evidence is recorded separately from ordinary hermetic acceptance.
