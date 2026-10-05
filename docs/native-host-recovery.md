# Linux recovery and portable project backups

Linux host recovery uses native Btrfs points replicated by btrbk. Windows retains
its separate Veeam backup. Portable project/configuration backups use the existing
Restic repositories and Google Drive; enable the four-hour cadence for each source
with its qualified Restic backend. Schema migration preserves existing schedules
so unqualified archive sources cannot start frequent full captures. Git checkpoints and local saved-work snapshots serve code
recovery between host backups.

## Current qualification

`st backup host status` reports installation, explicit coverage, admission,
latest capture and its evidence. **Ready to capture** does not establish a tested
restore. `st backup host run --dry-run` performs preflight without capturing.
The adapter stays disabled until `BACKUP_BTRBK_ENABLED=true` is deliberately
configured after the storage cutover and recovery checks.

The reviewed root-owned nonsecret configuration belongs at
`/etc/btrbk/summitflow.conf`, readable by the service user with mode `0644`.
Start from `scripts/systemd/btrbk.conf.example`. Keep the package's standalone
timer disabled: SummitFlow's existing backup orchestration runs the daily host
capture. The destination must be an independently mounted, unlocked Btrfs
filesystem with compression enabled. Snapshot directories must already exist.
Validate the configured source/target relations and a dry run before enablement.

Explicit host coverage includes `/`, `/home`, `/srv/workspaces`, `/var/lib/docker`,
`/srv/models` and `/var/log`. Every additional durable nested subvolume requires
its own section because Btrfs snapshots are not recursive. Managed work points
are excluded as nested snapshot boundaries. External PostgreSQL remains external;
application recovery uses associated verified portable database dumps.

The configuration keeps seven daily destination points and necessary source
incremental parents. Each capture carries matching boot/EFI files, observed disk
layout and a receipt. Retirement of matching boot files follows the native points,
not an unrelated folder age. Failed deletion retains its receipt and error.
Admission uses the existing host pressure policy and measured physical capacity;
an unqualified target or insufficient headroom prevents capture.

Initial admission conservatively reserves a full source-filesystem footprint,
matching boot allocation and the existing 25 GiB reserve for every run. This is
full-reseed headroom, not a measured incremental-growth forecast. Before final
sustainability acceptance, qualify actual incremental peak growth on the final
destination, keep full and incremental measurements separate and revalidate
incremental parents under the operation lock. Missing parents require full
admission or refusal. Independently previewed native expiry must remain available
when a capture cannot fit. Do not weaken this guard using a small fixture result.

Ubuntu Noble's packaged btrbk 0.32.5 uses the standard send protocol; destination
compression and native incremental sharing still apply. Its behavior must be
qualified on the installed kernel/tools. A later compressed-stream configuration
requires a separately verified btrbk version supporting those options.

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

Before Windows resizing, retain a fresh verified native Linux point, the matching
boot/layout evidence, portable SQL recovery and independent recovery access.
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
encrypted Btrfs layout, preserving NTFS when practical. Existing retained files
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
