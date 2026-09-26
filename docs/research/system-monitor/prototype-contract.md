# Host collector comparison contract

Task: `task-ea952b00a68b4940`. This contract applies to the Python, Go, and Rust Linux prototypes. The prototypes are measurement fixtures, not production services.

## Runner and ownership

Each prototype owns only its directory under `experiments/system-monitor/{python,go,rust}` and provides `run.sh`. The parent owns this contract and the benchmark harness. `run.sh --mode baseline|detail --samples N --interval-ms M [--service-cgroup PATH]` emits exactly one compact JSON object per sample to stdout. Diagnostics go to stderr. `--samples` is finite and the default interval is 5000 ms for baseline and 1000 ms for detail. No root calls, environment capture, command lines, journal reads, outbound network, or persistent writes are permitted in prototypes. A missing or denied source is represented as unavailable, never as numeric zero.

## Equivalent observation

Each sample has `schema: 1`, UTC `sampled_at`, monotonic `elapsed_ns` since the previous sample (null first sample), `mode`, `provider`, `duration_ns`, `host`, `service` (or null), `processes`, `processes_seen`, and `errors` (array of `{source,code}` objects). All counters are cumulative unless labelled percent or bytes of current state. The first CPU percentage is null because there is no interval.

`host` includes aggregate `cpu_busy_pct` (0–100, based on `/proc/stat` idle/total deltas), `memory_total_bytes`, `memory_available_bytes`, `swap_used_bytes`, root filesystem `disk_total_bytes` and `disk_free_bytes`, CPU/memory/IO PSI `some_avg10_pct`, non-loopback `net_rx_bytes` and `net_tx_bytes`, and whole-device `disk_read_bytes` and `disk_write_bytes`. Providers may use their library or Linux proc/sys files, but must document which source supplies each field. Rates are calculated by the harness from counters and monotonic elapsed time.

Every visible process is inspected for `{pid,start_ticks,name,cpu_user_ns,cpu_system_ns,rss_bytes,read_bytes,write_bytes}`. `start_ticks` comes from `/proc/<pid>/stat` and is combined later with boot ID for identity; memory is RSS, not virtual size. Permission-denied and exited-during-scan counts are reported separately. `detail` outputs all successfully observed processes. `baseline` performs the same lightweight scan but emits the union of the top ten by interval CPU, top ten by RSS, and top ten by interval I/O; first-sample CPU and I/O leaders are absent because deltas are unavailable. Each emitted row carries the leader reasons. Sorting is deterministic by metric then PID/start ticks. A process that disappears between samples is not reported as zero.

When `--service-cgroup` is supplied, read cgroup-v2 `cpu.stat` `usage_usec`, `memory.current`, and `io.stat` read/write bytes for that whole service. Include `service.source: cgroup2`; report unavailable fields explicitly. The service path is passed by the harness from a known managed unit, not discovered through arbitrary command execution.

## Benchmark and decision

The parent runs each finite collector under the same host workload and common NDJSON-to-SQLite writer so collection cost and end-to-end cost can both be reported. Collect `time`/`/proc` CPU, peak RSS, `rchar`, `syscr`, `read_bytes`, `write_bytes`, elapsed time, missed sample deadlines, output bytes, processes seen, field availability, and SQLite DB/WAL growth. Include compiler/build time separately from runtime; include child processes in production cost. Compare idle, load, process churn, source denial, baseline, and detail. Repeat runs until ranking is reproducible and record raw values, machine state, versions, and errors. The selected candidate receives a production storage prototype and is profiled again before deployment.

Correct coverage and reliability are gates. Python is the integration default if it meets the resource budget frozen before results. A compiled alternative replaces it only when both steady CPU and peak RSS improve by at least 25% with no I/O or reliability regression. If Python fails, choose the passing compiled candidate with lower CPU, then RSS, then simpler deployment. If no candidate passes, reduce fields/cadence and rerun. The eventual budget and any change to this contract must be recorded before looking at comparative results.

Initial production acceptance budgets, frozen before the first comparative run: baseline average CPU at most 1% of one logical core and collector-family peak RSS at most 100 MiB; detail average CPU at most 5% and peak RSS at most 150 MiB; p95 sample plus commit at most 500 ms; p95 bounded local history query at most 250 ms; cold local status query at most 1 second; physical writes at most 1 GiB/day in a representative mix; DB, WAL, and temporary state together at most 512 MiB with 1 GiB free filesystem headroom. These are design gates to test, not measured facts. A failed gate requires lowering work or revising the budget with evidence before selection.
