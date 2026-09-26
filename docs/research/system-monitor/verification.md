# Host monitor delivery and verification

Task `task-ea952b00a68b4940`; verified on the Ubuntu desktop on 2026-09-26. The implementation is local and non-root. The collector, CLI reader, API, and Runtime Monitor tab share schema v1. Protected screenshots and raw profiles are under `/home/kasadis/.local/share/summitflow/evidence/task-ea952b00a68b4940/`; they contain local host details and are not committed.

## Installed architecture

```text
/proc + /sys + cgroup v2 + systemd user units
                  │
        Rust host-monitor (user service)
        5 s baseline; bounded detail lease
                  │
       0700 state / SQLite WAL / 0600 socket
                  │
      monitor_reader schema v1 + on-demand providers
          ┌───────┴────────┐
    standalone st       owner Runtime API → Monitor UI
```

The collector is the sole writer. It persists source timestamps, gaps, error codes, service state, process identity `(boot_id,pid,start_ticks)`, baseline leaders and leased process detail. It stores neither argv/environment nor raw logs. On-demand journal, sensors, inventory, connections, scoped disk attribution and bounded probes do not become routine history. The standalone `st` launcher selects the accepted monitor release and still reads committed SQLite when the FastAPI/PostgreSQL import graph is unavailable. The managed unit uses systemd sandbox settings and has no network listener.

The managed release from commit `0107276c67299b25d194f528c19b6747e15664ae` succeeded with job `c0cec8525bf94917a8ed59a811c9d307`. Its full acceptance receipt is `.git/st/acceptance/eb2c3caa35c88f374eae14669501a2cc28870b23aa1e82ba4817084a06ea19ff.json`: 3,616 Python tests passed, 2 skipped, 229 frontend tests passed, and Ruff, types, Biome, TypeScript, gitleaks, Semgrep and OSV passed. Rust collector tests (19), format and release build passed. The release restarted backend, frontend, Hatchet worker and monitor; managed health passed.

## Measured installed cost

`experiments/system-monitor/profile-managed.py` measured the installed service in two 60-second baseline plus 30-second leased-detail runs. The corrected raw result is `managed-profile-corrected.json`; the earlier `managed-profile.json` is retained as first-run evidence with its pre-write timing label superseded. The cgroup exposed CPU and memory but not `io.stat`, so I/O is from the single collector PID's `/proc/<pid>/io`, not a whole-cgroup device total. Writes are short-window extrapolations, not a steady-state guarantee.

| Signal | Baseline | Leased detail |
| --- | ---: | ---: |
| CPU, percent of one core | 0.376% | 2.528% |
| Cgroup memory median / sampled maximum | 5.742 / 5.996 MiB | 6.852 / 7.668 MiB |
| Physical write bytes over phase | 630,784 | 749,568 |
| Write extrapolation if mode were continuous | 0.907 GB/day | 2.158 GB/day |
| SQLite DB+WAL+SHM growth over phase | 0 bytes | 0 bytes |
| Observed sample commits / sample-plus-commit p95 | 12 / 47.216 ms | 6 / 56.975 ms |

The socket records sample-plus-commit latency; SQLite `samples.duration_ns` stops before persistence and is labelled pre-commit collection time in raw evidence. The 18 baseline database rows span both phases, since baseline persists during detail. Zero file-size growth in the corrected run means existing SQLite pages/WAL space were reused, not that no storage writes occurred. CLI p95 over 20 validated local responses each: status 101.416 ms, processes 41.557 ms, series 45.411 ms, including process startup and JSON parsing. The earlier run extrapolated 1.003 GB/day baseline and 2.347 GB/day detail, showing short-run variance. **The original ≤1 GiB/day representative-mix write gate is not yet proven.** Leases expire, but repeated leases and sustained triggers can keep detail active; a longer mixed-load and churn run must define the duty cycle and measure the budget. The configured 512 MiB total size and 1 GiB free-headroom guards have unit/headroom tests, but a hard size ceiling under sustained WAL pressure has not been verified.

## Live routes and recovery

- The installed `st monitor status` returned schema 1, `ok` sample and `ok` collector. One live snapshot had 696 processes seen, zero unreadable process stat files and 695 unreadable per-process I/O files. Rows remain visible with null I/O; the UI reports the two denial counts separately. The owner belongs to `adm` and `docker`.
- `plain-account-coverage.json` records the same binary running as `nobody` without owner groups in an isolated state directory. It saw 687 processes, zero denied stat reads and 686 denied process I/O reads. Host CPU became available after the second sample; memory, all three PSI proc files, `/proc/net/dev`, `/proc/diskstats`, and 11 hwmon temperature inputs were readable. The owner's system/user journals and SummitFlow user service query failed. This is a real UID separation test, but `nobody` is a service account without a desktop session; a logged-in plain user may have additional user-session sources.
- The installed Runtime Monitor tab showed derived memory used, host timeline, four managed services, process pagination, source events and on-demand diagnostic tabs. Detail capture switched the collector to detail, and Flight Recorder pagination advanced to page 2. Navigating away and reopening Runtime/Monitor loaded current data and controls. Browser checks passed. Protected final screenshots: `live-monitor-final.png`, `live-monitor-processes.png`, `live-monitor-diagnostics.png`, `live-monitor-benchmarks.png`, and `live-monitor-flight-recorder.png`.
- `isolated-recovery.json` records two independent collector starts into the same temporary store. After each collector stop, standalone `st monitor status` read one committed sample with `collector_stopped` and an intentionally invalid PostgreSQL connection setting; sample counts progressed 1 → 2 and SQLite `quick_check` was `ok`. A held WAL reader kept its two-row snapshot while a third collector start committed in 70 ms; a new read saw three rows. An isolated collector was then killed with SIGKILL after its fourth committed row; the stopped reader still returned history, restart committed a fifth row, and SQLite integrity remained `ok`. Rust store tests also exercise a forced insert failure, headroom rejection, retention and rollup restart backfill. These are controlled isolated tests, not an outage of the shared backend or PostgreSQL service.
- State directory permissions are `0700`; SQLite, socket and policy snapshot are `0600`. Direct backend loopback monitor reads work for the local development owner bypass. A forwarded LAN client header returned 403. A request originating from the host LAN address through Caddy returned 403 even with a forged loopback forwarding header; the public Cloudflare Access URL redirected an anonymous request to login. The backend/frontend bind `127.0.0.1`.

## Capability coverage and limits

The installed TMOG 1.0.0 Free views and Pro previews were captured under `tmog-1.0.0/`. The Benchmarks CPU Pro preview was recovered at `tmog-benchmarks-cpu-pro-preview/image.png`: its selector lists CPU, GPU, Disk, Internet and TMOG Score, with Start disabled in Free mode. Individual GPU/Disk/Internet/Score previews and a working Pro session were not observed. This matrix compares visible function names and public documentation, not TMOG internal code or performance.

| TMOG area | SummitFlow delivered | Remaining difference |
| --- | --- | --- |
| Summary, Performance | CPU/memory/disk/network/PSI host history, service timelines, freshness and source errors | GPU readings are on demand from NVIDIA, not a retained GPU timeline; aggregate network/disk counters are cumulative in this release. |
| Processes | Baseline leaders, leased all-visible detail, filter/sort/page, stable PID identity, state/PPID, CPU/RSS/I/O availability | No interactive graphical parent tree; rows with denied `/proc/<pid>/io` have null I/O. |
| Services | Managed user-unit state, cgroup CPU/memory/I/O where available, state events, journal query | Cgroup `io.stat` is unavailable on this host; no state-changing action in monitor. |
| System info, startup, users | Fixed-source OS/hardware, systemd and desktop autostart, local users/sessions | Inventory reflects visible/configured providers; it is not a universal package/session database. |
| Power & frequency | hwmon, cpufreq, power supply and NVIDIA query with provider coverage | Power-supply provider is unsupported on this desktop. |
| Flight Recorder | Paginated baseline/detail/event replay with process identity and process-query pointer | Export stores top-three RSS process context per replay page, not a full arbitrary-state UI recording. |
| Connections | On-demand socket states; addresses and owner process are opt-in | No packet capture. |
| Installed apps, drivers | Bounded Debian/desktop metadata and loaded kernel-module inventories | No Snap/Flatpak catalog or driver update workflow. |
| Disk space | Explicit bounded, metadata-only scan under owner home/registered project roots | Not a full-disk allocator view; symlinks/hidden/sensitive names are excluded. |
| Benchmarks | Opt-in bounded CPU hash and cached-file read probes | GPU and network return structured `unsupported`; the disk probe is not physical disk throughput. |

Agent-specific additions are compact JSON budgets (default 4 KiB, maximum 64 KiB), time windows, filter-bound cursors, rollups, process/service/source correlation, PSI, null-versus-zero semantics, error provenance, and readable history when app services are down. Examples:

```sh
st monitor status --max-bytes 4096
st monitor series cpu_busy_pct --since 1h --step 60 --limit 20
st monitor processes --sort cpu --limit 5
st monitor events --since 30m --severity warning --limit 10
st monitor logs backend --since 15m --priority 4 --limit 5
st monitor capture --ttl-seconds 30
st monitor export --since 2026-09-26T19:00:00Z --until 2026-09-26T20:00:00Z --limit 10
```

An agent investigating a slow backend can request status, a 20-point service CPU timeline, then five highest-CPU processes and a few warning events. A disk complaint can request root free space, pressure history and an explicit scoped `disk-space` scan. A suspected service outage can request service state/events and five redacted journal entries. Each step carries time, provider, coverage and errors; the agent follows a returned cursor only if the first page warrants it.

## Privacy boundary and remaining decisions

The collector, socket and store are owner-file-private and require no elevated service. The HTTP monitor routes require the existing SummitFlow owner principal and reject nonlocal forwarded bypass requests. However, SummitFlow's pre-existing localhost development bypass grants an owner principal to any local HTTP caller. TCP loopback cannot identify Linux UID. Another local account on a multiuser host could read sensitive monitor HTTP data (and other existing local APIs) until the application-wide bypass is replaced with authenticated local sessions. This is an explicit limitation of this Ubuntu single-owner desktop release; do not deploy its HTTP UI on an untrusted multiuser workstation. Cloudflare Access protects the public hostname, and the installed origin-LAN check above was verified. A monitor-only token would narrow direct routes but would not fix other local APIs that can act with the backend owner's authority.

No process kill, service restart, package installation, network benchmark, GPU workload or unbounded filesystem walk is part of observation. Existing guarded `st` operations own state-changing actions. The separate-UID experiment above establishes basic proc/sys visibility and denial behavior; a logged-in plain account is still needed for user-session and journal coverage. Longer mixed-load write profiling, quota pressure on the installed btrfs filesystem, alternate Linux desktops and Snap/Flatpak coverage are the smallest further experiments. Cross-platform work needs separate macOS/Windows service, log, process identity, sensor, startup, packaging, socket-permission and installer providers plus repeat profiling; the shared schema, pagination and UI can remain. Estimate each new OS after a provider spike, not by assigning a calendar duration now.

## Next execution slices and effort

The first vertical slice is installed: Rust baseline/detail collection, independent history, bounded `st` queries, shared owner Runtime views, and isolated restart/WAL checks. Its remaining acceptance gates are the representative mixed-write target, sustained storage-pressure recovery, a logged-in plain-user session check, and full functional parity with the Pro preview categories. The estimates below are focused engineering hours including verification, not elapsed-time limits or measured past effort. Independent provider and UI tasks can proceed in parallel.

| Slice | Estimate | Smallest decisive experiment or acceptance |
| --- | ---: | --- |
| Mixed workload and churn profile | 6–10 h | Measure a stated baseline/detail duty cycle, cgroup/PID I/O and valid query responses over enough rotation to compare with ≤1 GiB/day. |
| Storage, outage and lifecycle hardening | 8–16 h | Constrained-store and sustained WAL reader test, service-triggered detail, isolated app/DB loss and recovered UI, installed rollback. |
| Plain-account and diagnosis workflows | 6–12 h | Run same provider matrix under an actual plain login; capture three bounded agent transcripts and stale/denied/reopen UI states. |
| Authenticated local sessions, if multiuser desktop support is required | 12–24 h | Replace application-wide localhost owner bypass and test existing clients before claiming OS-user privacy through HTTP. |
| Parity extension: rates, retained GPU, process tree | 12–24 h | Confirm provider fidelity and additional collector cost, then add model/UI fields. |
| Meaningful disk/GPU/network benchmark providers | 20–40 h | Define workload, hardware/endpoint constraints, accuracy and self-cost; keep unavailable providers explicit. |

The remaining Ubuntu acceptance work is roughly 20–38 engineering hours if these experiments reveal no substantial defect. A macOS provider spike is roughly 6–10 hours and a Windows spike 8–12 hours; provisional current-scope ports are 80–140 and 100–180 hours respectively, including installers, IPC/permissions, providers and acceptance. These are assumptions to revise after running each spike and exclude unverified TMOG Pro equivalence and signing procurement. No calendar duration is imposed.
