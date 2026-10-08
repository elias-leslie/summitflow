# Shared transient-work admission

Canonical ST quality tools, local security candidate preparation, outgoing
publication history/scans, and managed dependency/build subprocesses share one
same-user Linux admission lane. Queue waits print a plain message; admission
storage failures fail closed. No tool, required gate, or tool timeout is skipped
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
