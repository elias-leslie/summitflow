# SummitFlow system monitor: evidence and implementation record

Task `task-ea952b00a68b4940`. Checked on Ubuntu 24.04.5 with TMOG 1.0.0 installed. Raw local screenshots and process profiles are retained under `/home/kasadis/.local/share/summitflow/evidence/task-ea952b00a68b4940/` with owner-only permissions; they contain host details and are not committed. Statements below distinguish inspection, measurement, and planned behavior.

## Existing SummitFlow surface (inspected)

- `backend/app/services/resource_monitor.py` collects psutil host CPU, memory, disk and NVIDIA data. `backend/app/api/system.py` exposes current system stats. The reported response timestamp is not a source measurement timestamp; `get_cpu_usage` has a blocking one-second psutil call.
- `backend/app/services/runtime_metrics_sampler.py` samples managed service CPU/memory every 300 seconds by default and retains 14 days in PostgreSQL. FastAPI lifespan owns this sampler. `GET /api/docker/metrics` also writes a sample while serving live metrics. The systemd provider in `backend/app/api/docker/_metrics_collection.py` measures the main PID rather than a cgroup total.
- `backend/cli/commands/runtime.py` exposes `st runtime metrics` from the PostgreSQL store. `st logs` offers bounded service aliases but does not provide journal cursor/provenance or explicit source failures. Neither is an independent outage history path.
- `frontend/app/(app)/runtime/page.tsx`, `ServiceGrid`, and `ServiceMetricTimeline` already offer health cards and service CPU/memory history. `backend/app/access_control.py` restricts general APIs to the owner, but sensitive monitor endpoints should also declare `require_owner` themselves.
- The backend and frontend run as managed user services; the owner user manager has lingering enabled. The current account belongs to `adm` and `docker`, so its successful reads do not establish ordinary-account coverage. The `st` command currently resolves through the backend virtualenv and needs a stable monitor dispatch to survive a broken backend environment.

## Build-versus-adopt decision

Build a small, local SummitFlow-owned collector/store/query model. It directly fits owner-only `st` access, backend-independent history, managed-service identity, and Runtime UI reuse. Profile adopt candidates where isolated execution is practical; do not claim measured comparative overhead for those not run. [Glances](https://github.com/nicolargo/glances/blob/b3f1cf008e9ad28eb02e1bb63d74f980683fedf6/pyproject.toml) (LGPL-3.0-only) is the strongest ready-made agent/API collector but still needs our history/auth/correlation layer. [node_exporter](https://github.com/prometheus/node_exporter/tree/60ce437b9c737c3b9a9619df457ae68a067d3cfc) (Apache-2.0) supplies host counters but not process/log investigation or history by itself. [Netdata Agent](https://github.com/netdata/netdata/blob/d587983ee11c8994bad39682dcf28631c3000a69/REDISTRIBUTED.md) (GPL-3-or-later) and its [separately licensed UI](https://app.netdata.cloud/LICENSE.txt) add an independent stack. [btop](https://github.com/aristocratos/btop/tree/7b1f128e511ff5901dfba44dcd5f37236e7cb403) (Apache-2.0) is a UI reference, not the shared query system.

TMOG's [official RTM page](https://www.tmog.org/rtm/) and [release notes](https://tmog.org/release-notes.html) describe the product; the installed Free views were observed, while Pro was available only as previews. The [feedback repository](https://github.com/PlummersSoftwareLLC/tmog-feedback/blob/72c6607244287ba77e147a180a28e2a5c6ffeec3/README.md) explicitly says product source is private. Its creator's separate [Windows console `tm`](https://github.com/PlummersSoftwareLLC/tm/tree/5fd5552c2c80bd4e08a862a4ccea9592abd928f8) has no license; do not reuse its code. The unaffiliated [evildojo-tmog](https://github.com/mikedesu/evildojo-tmog/tree/d63110ae031c1c220682e947215b12f7cab7c845) is MIT licensed and may inform ideas or fixture design with attribution. No TMOG proprietary implementation was inspected or copied.

### TMOG diagnostic capability map

| View | Evidence | SummitFlow target |
| --- | --- | --- |
| Summary, Performance | Installed Free screenshot | Host CPU/memory/disk/network/pressure/GPU timelines, source and freshness; build on existing Runtime cards. |
| Processes | Installed Free screenshot | Tree/list, identity-safe sorting/filtering, leaders in baseline and all visible processes during detail; guarded `st` owns control. |
| System Info | Installed Free screenshot | Static hardware/software/provider capabilities with explicit unavailable fields. |
| Startup apps, Users, Services | Installed Free screenshots | Read-only inventory, service event/resource history and user sessions; state-changing controls stay in existing guarded workflows. |
| Power & Freq | Installed Pro preview | Optional hwmon/cpufreq/powercap telemetry, reporting permission or hardware limits. |
| Flight Recorder | Installed Pro preview | Bounded capture intervals, linked replay and export of our documented format; show baseline/detail gaps. |
| Connections | Installed Pro preview | On-demand socket endpoints and owning processes where permitted; no packet capture. |
| Installed Apps, Drivers | Installed Pro previews | On-demand package/desktop-app and kernel-module inventories. |
| Disk Space | Installed Pro preview | Explicit scoped and cancellable space attribution scan; never an always-on filesystem walk. |
| Benchmarks | Installed Pro preview | Explicitly invoked, bounded CPU/GPU/disk and configured-endpoint network measurements, with self-cost and result provenance. |

Agent needs beyond these views include PSI and whole-service cgroup accounting, journal and application-event correlation, precise time windows, source freshness, compact pagination, and explicit statements when history cannot answer a question. Treat [TMOG Linux close/reopen issue #1067](https://github.com/PlummersSoftwareLLC/tmog-feedback/issues/1067) as our reproduced UI lifecycle lesson, not an internal-design clue. Other TMOG user reports about [power access](https://github.com/PlummersSoftwareLLC/tmog-feedback/issues/1054), [CPU overhead](https://github.com/PlummersSoftwareLLC/tmog-feedback/issues/1049), and [history gaps](https://github.com/PlummersSoftwareLLC/tmog-feedback/issues/981) motivate measurement and failure-state tests; they are not independently verified product behavior.

## Collector comparison (measured prototypes)

The common contract is in `prototype-contract.md`; three local prototypes use psutil 7.2.2, gopsutil v3.24.5, and sysinfo 0.39.6 plus Linux proc/sys sources. Three balanced sequential rounds sampled a known SummitFlow service cgroup and about 695–712 visible processes in the corrected run. Values are median of runs, from `/tmp/sf-monitor-comparison-20260926-2/comparison.json` and protected retained evidence. Warm CPU uses cumulative process CPU changes between emitted samples, excluding startup.

| Mode | Python CPU / RSS | Go CPU / RSS | Rust CPU / RSS |
| --- | --- | --- | --- |
| Baseline, 5-second cadence | 1.00% of one core / 19.1 MiB | 0.36% / 9.6 MiB | **0.24% / 3.0 MiB** |
| Detail, 1-second cadence | 5.00% / 20.1 MiB | 1.67% / 9.7 MiB | **1.33% / 4.3 MiB** |

Sample-plus-common-SQLite-commit p95 was about 53/18/15 ms baseline and 53/18/15 ms detail for Python/Go/Rust. All three exposed the same ~38% per-process I/O coverage in detail because this host denies many `/proc/<pid>/io` reads; all retain those processes with null I/O. A semantic check fixed an early Python omission of denied rows and Rust loop-device double counting **before** the corrected comparison. Rust's cgroup units/keys were fixed and validated on the known service path. The common writer produced about 123 KiB of JSON per detailed sample and roughly 3.9 MiB of physical writes for ten detailed samples, including the raw NDJSON evidence file. This does not predict production write volume; continuous raw 1 Hz detail is incompatible with a small bounded store.

**Decision:** Rust is the selected production-storage prototype because it preserves tested field coverage and wins CPU, RSS, and sample latency against Go in the corrected runs. This is not a deployment approval. The production service must still pass whole-process CPU/RSS, compressed persistence, write rate, retention, query, outage, and failure tests. [sysinfo](https://github.com/GuillaumeGomez/sysinfo/blob/5bb745b85474c58a2435621b13ddbd491d63d58d/Cargo.toml) is MIT; prospective [rusqlite](https://github.com/rusqlite/rusqlite/blob/91f876c80114122670f455190d03c81d1f78b0af/Cargo.toml) is MIT and [flate2](https://github.com/rust-lang/flate2-rs/blob/fcc804306677bf8cfde2250bf0472d61b75d1c45/Cargo.toml) is MIT OR Apache-2.0. Audit exact resolved dependencies before reuse.

## Security and platform boundary

Use the current owner identity for the managed non-root user service, with owner-only state/socket access and no collector network listener. That identity still has consequential group privileges; do not expose arbitrary SQL, filesystem paths, shell commands, or journal arguments. Keep environment, secrets, raw logs and full argv out of routine history. Make potentially destructive controls separate existing `st` workflows. Owner-only backend authorization is required even when Cloudflare Access fronts the UI.

Linux [proc visibility](https://www.kernel.org/doc/html/latest/filesystems/proc.html) and per-file permission checks limit other-user detail; [PSI](https://www.kernel.org/doc/html/latest/accounting/psi.html) and [cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) expose useful pressure and service counters when configured; journal access is separately gated by [journal file permissions](https://www.freedesktop.org/software/systemd/man/latest/systemd-journald.service.html). [SQLite WAL](https://www.sqlite.org/wal.html) permits one writer and concurrent readers but needs short read transactions and explicit checkpoint/failure handling. Feature-detect all optional providers.

Basic cross-platform counters may reuse library abstractions. macOS and Windows require separate service managers, logging, process identity, sensor/power, startup, socket-ownership, packaging and permission providers. Keep Ubuntu as the verified first platform; estimate further platform work from provider spikes and actual Ubuntu implementation effort, not a calendar guess.
