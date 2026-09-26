# Python host collector fixture

Run `./experiments/system-monitor/python/run.sh --mode baseline --samples 2 --interval-ms 50` from the project checkout. `--mode detail` emits all readable processes. The runner uses `backend/.venv/bin/python` and psutil 7.2.2. It makes no persistent writes; stdout contains one compact JSON object per sample.

## Field sources

| Fields | Source |
| --- | --- |
| Host CPU busy | `/proc/stat` aggregate total and idle deltas; first sample is null |
| Host memory, swap | psutil `virtual_memory()` and `swap_memory()` |
| Root disk space | psutil `disk_usage('/')` |
| CPU, memory, I/O PSI | `/proc/pressure/{cpu,memory,io}` `some avg10` |
| Network counters | `/proc/net/dev`, summed for every interface except `lo` |
| Whole-device disk counters | `/proc/diskstats` sectors times 512 for names in `/sys/block`, excluding loop and RAM devices |
| Process identity, name, CPU counters | `/proc/<pid>/stat`; CPU ticks converted using `SC_CLK_TCK` |
| Process RSS and I/O counters | psutil `Process.memory_info()` and `Process.io_counters()` |
| Service | cgroup-v2 `cpu.stat` `usage_usec`, `memory.current`, and summed `io.stat` `rbytes`/`wbytes` |

`processes_seen` counts PIDs enumerated by psutil. `processes_permission_denied`, `processes_exited`, and `processes_unavailable` count affected PIDs during that scan. A readable process identity is retained when RSS or I/O access fails; those fields are null. Processes whose identity disappears during scanning are omitted. Missing host or service fields are null with a `{source,code}` entry in `errors`; the first CPU percentage and first `elapsed_ns` are naturally null without errors. A baseline row includes `leader_reasons` (`rss`, `cpu`, `io`); CPU and I/O ranking use only surviving process identities seen in the previous sample and I/O ranking requires available counters in both samples. Detail rows carry `leader_reasons: []`.

## Limits

Process I/O access can be restricted by Linux permissions, so I/O field coverage depends on the runner's user. A PID can disappear during scanning. Network totals include bridges and virtual interfaces, and disk totals may double-count stacked devices such as device-mapper over a physical disk. The service path must resolve under `/sys/fs/cgroup`; an absent or denied cgroup field is null. The fixture does not discover service cgroups.
