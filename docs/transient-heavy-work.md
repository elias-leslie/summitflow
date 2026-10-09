# Shared transient-work admission

Canonical ST quality tools, local security candidate preparation, outgoing
publication history/scans, and managed dependency/build subprocesses share one
same-user Linux heavy admission lane. One separate light slot is reserved for
the direct managed Ruff adapter (`name=ruff`, `binary=ruff`). Configured wrappers,
unknown tools, tests, native stages, builds, installs, scans and composite
cleanrooms remain heavy. `--quick` selects stages; only its Ruff stage is light.
A light context cannot implicitly upgrade to heavy, including in descendants.
Ruff nested under a verified heavy owner reuses that heavy admission.

Independent arrivals register private ordered waiter files under a short
`queue.lock` metadata lock. Only the earliest live record in its class may try
the capacity locks. This includes an owner that releases and immediately queues
again. Waiting does not hold the metadata lock. Cancellation removes only that
waiter's record; abandoned records are reclaimed using their kernel file-lock
ownership and verified PID/start identity, including zombies and PID reuse.
There is no TTL. Capacity and depth lock files are never unlinked or reset.
Verified descendants retain the established depth/sibling admission semantics.

Wait messages are bounded and report class and wait age every five seconds.
Holder operation/project names, PID and active age appear only after verifying
the recorded process identity, activity inode/shared lock and generation.
Legacy owners and surviving descendants without verified holder metadata are
reported as unknown. Records contain operation/project names, not commands,
arguments, credentials or environment dumps. Direct managed tool results report
queue and execution milliseconds separately; tool timeouts still start at launch.

Transition preserves the existing `admission.lock`, `activity.lock` and
`depth-*.lock` inodes. New metadata and `light-*` files are created alongside
them; no migration/reset of `/tmp/st-heavy-<uid>` is needed or permitted. Older
processes still enforce the heavy capacity lock but do not join the FIFO queue.
FIFO therefore applies to updated callers; full ordering requires existing
processes to drain and new CLI/worker code to be loaded through the normal
owner-authorized service rollout. Do not interrupt jobs to make this transition.
Old code cannot understand light lease markers; do not mix old descendant code
under a light context during rollout.

Admission storage failures fail closed. No tool, required gate, or tool timeout is skipped
or shortened. Runtime services, systemctl, ordinary inspection and the resident
API/task workers are not reniced or admitted into this lane.

`st check cleanroom` also acquires admission before materializing its isolated
checkout and running the supplied command. This specialized validation/install
route preserves its environment isolation, return code and cleanup behavior;
its child receives the same lower priority and bounded worker settings. Nested
canonical checks inherit admission rather than deadlocking. It is not a route
for ordinary status or source inspection.

Cleanrooms use the caller's explicit `TMPDIR` as their checkout parent, even if
Python previously cached another temporary directory. Without that setting,
the mounted host `/srv/scratch` takes precedence through a private
`st-cleanrooms-<uid>` directory. Scratch must be a real mount, without symlinks
or group/other write access; its per-user directory must be owned by that user
with mode `0700`. A present but unmounted or unsafe scratch path fails before
copying the checkout. Hosts without `/srv/scratch` retain Python's portable
temporary-directory selection. Explicit `TMPDIR` must be an existing absolute,
owner-controlled directory without symlinks; shared namespace directories such
as `/tmp` must have the sticky bit.

Each job places its repo, isolated home/cache and child `TMPDIR` under the owned
cleanroom directory. `--env TMPDIR=...` still overrides the child's selection.
Normal completion, a nonzero command exit, and preparation/launch exceptions
remove the owned directory; `--keep-dir` retains it and reports its path. This
routing applies only to newly created cleanrooms. It does not move existing work
or durable artifacts. On the managed host, `/srv/scratch` is the disposable
mount excluded from backups; admission locks remain at their fixed `/tmp` path.

Future repository recovery materialization, weekly mapped configuration trees,
encrypted-archive plaintext and infrastructure drills require that same mounted
scratch root through `app.utils.transient_scratch`. Restore work uses a private
`st-restores-<uid>` parent and a separate `0700` directory per attempt. Unlike
portable cleanrooms, restores refuse missing, unmounted or unsafe scratch and do
not follow an inherited `TMPDIR` onto the root volume. This changes future
attempts only; it does not relocate or interrupt an already running restore.

Capacity checks use free bytes on the actual scratch destination and the
existing `HostRetentionPolicy.pressure_min_free_gb` reserve (25 GiB by default).
Repository recovery accounts for known materialized payloads, simultaneous
archive copies and retained mapped trees; measured payload/archive sizes are
checked again at phase boundaries. Drill admission counts extracted tar members
and the additional Redis data copy. Ciphertext size is only a lower bound for
plaintext staging. During the infrastructure drill, the existing bulk-work
polling loop also checks that scratch still has the same reserve. Crossing it
raises a capacity error, stops the owned process group and cleans up its
disposable containers/data. PostgreSQL restore expansion, filesystem overhead
and writes from unrelated jobs are not bounded by the initial size estimates.
Polling is not a disk quota or a guarantee against writes consuming space
between checks.

The drill binds the entire disposable PostgreSQL data directory and Redis data
directory beneath its owned scratch job, using the caller's UID/GID. PostgreSQL
runtime sockets and temporary files use container tmpfs. The Redis RDB is copied
into its writable scratch data directory; the recovered original is preserved.
The existing prepared images run with no network and no image pull. The script
requires the validated private job supplied by SummitFlow. Its normal exit
cleanup and the Python owner's final cleanup remove only that attempt's named
containers, including on timeout or cancellation, before removing plaintext
staging. The established 600-second drill timeout uses the existing bulk
process-group owner; normal capture/transfer calls retain their unbounded wait
behavior. Cleanup errors remain visible without replacing a primary cancellation.

The private `/tmp/st-heavy-<uid>` directory is independent of project and HOME.
Owner, type, mode, link and symlink checks protect its lock files. There is no
daemon, environment bypass, per-project policy store or new service. A live
ancestor's descriptor/inode/lock provenance validates descendant reentry; a
copied marker alone is insufficient. Same-thread nesting reuses its context,
while inherited sibling threads/processes serialize at the next nesting depth.
Forked children cannot reuse copied thread-local ownership. Descendant activity
holds admission even when its owner exits abruptly.

Owned transient children run at lower CPU priority and best-effort idle I/O
priority without changing their parent. Native worker environment settings
limit supported pools to two, preserving explicit smaller values. Vitest uses
one worker because its environment settings override project worker config.
Next's `CIRCLE_NODE_TOTAL=3` limits its **default** worker count to two; explicit
project `next.config` CPU settings still take precedence. This is not a hard
memory/CPU quota or a runtime-service limit.

CLI-owned child timeout/exception cleanup stops its original process group,
including pipe-holding children after the leader exits. Captured descendants
in separate sessions are additionally checked against their process start time
before signaling. Native scanner capture uses posix_spawn and explicit lease FD
actions, without Python fork, preexec hooks or parent-inheritable FD changes.
CLI capture delegates to the canonical `safe_subprocess.run_cli_owned` adapter;
that session-owning adapter is deliberately separate from the resident native
`run`/`run_inherited` paths and must not be used by ASGI/task callers.
Abrupt SIGTERM of an owner retains admission while surviving descendants hold
it; it does **not** promise a global signal handler or cancellation of arbitrary
already-reparented, detached sessions. Existing subprocess timeouts remain.
If an uncaptured detached session retains an output pipe, the final CLI drain is
bounded and owned capture handles close; cleanup does not expand its kill scope.

Acceptance fingerprints include the shared helper and native adapter bytes;
transient paths, process IDs, lease generations and queue state are not receipt
identity. These controls are advisory workstation scheduling, never security or
publication authorization. Focused fixtures cover real cross-process CLI races,
inherited siblings/threads, fork reentry, provenance, unsafe storage, owner exit,
timeout cleanup, descriptor cleanup and child-only priority.
