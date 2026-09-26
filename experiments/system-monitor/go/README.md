# Go host collector fixture

Linux-only finite NDJSON collector using Go 1.22 and gopsutil v3.24.5. Build once with `./build.sh`, then run `./run.sh --mode baseline --samples 2 --interval-ms 100`. The runner rebuilds only when source or module files change and then execs the binary. Build time and generated `.build/collector` are separate from warmed runtime cost.

## Sources

| Output | Source |
| --- | --- |
| Aggregate CPU busy percentage | `/proc/stat` idle and total tick deltas; first sample null |
| Memory total/available, swap used | gopsutil `mem.VirtualMemory`, `mem.SwapMemory` (`/proc/meminfo`) |
| Root disk total/free | gopsutil `disk.Usage("/")` (`statfs`) |
| CPU/memory/IO pressure some avg10 | `/proc/pressure/{cpu,memory,io}` |
| Non-loopback RX/TX counters | gopsutil `net.IOCounters(true)` (`/proc/net/dev`), excluding `lo` |
| Whole-device disk read/write counters | gopsutil `disk.IOCounters` (`/proc/diskstats`, sectors × 512 bytes) restricted to exact device names in `/sys/block`, excluding names beginning with `loop` or `ram` |
| Process identity, CPU time, RSS | `/proc/<pid>/stat`; CPU ticks converted using `sysconf(_SC_CLK_TCK)`; RSS pages use `os.Getpagesize` |
| Process read/write bytes | `/proc/<pid>/io` |
| Service CPU, memory, IO | cgroup-v2 `cpu.stat`, `memory.current`, `io.stat`; IO sums per-device `rbytes`/`wbytes` |

Unavailable source fields are JSON null with deduplicated `{source,code}` errors. A process with readable `stat` but denied `io` remains visible with null IO counters and contributes to the denied count. Exited processes are never synthesized as zero. `processes_seen` counts numeric `/proc` entries; `processes_permission_denied` and `processes_exited` count source failures, which can each occur during a single process scan. Baseline leaders are selected from same-identity interval deltas and RSS; detail emits every readable process.

The collector reads the caller-visible procfs and cgroup mounts. Container mounts, namespace visibility, and virtual block devices affect coverage. The network counter is the sum of all non-`lo` interfaces, including virtual interfaces. Disk counters are summed for exact `/sys/block` names only, so partition rows such as `sda1` are excluded. On the smoke host `/sys/block` contained `sda`, `nvme0n1`, and loop devices; only `sda` and `nvme0n1` contributed. Stacked whole devices can still overlap when present. Service `io.stat` may omit a field when no device line reports it; that field stays null. Error entries are deduplicated by source and code, so they do not encode the number of affected PIDs.
