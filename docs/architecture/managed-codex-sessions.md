# Managed Codex sessions: Architecture D shadow rollout

SummitFlow owns a process and transport, not normalization. Agent Hub is the sole
receipt, reconciliation, checkpoint and query authority. The existing host rollout
collector stays permanently enabled for managed and independently launched sessions.
No downstream consumer changes or new services are required.

## Operation

`st sessions managed-codex` is a native stdio App Server entrypoint for a controlling
client. It starts its own process and requires the current directory's registered
project identity. The client supplies initialize, thread/turn operations and approval
decisions. This command is not an interactive Codex TUI launcher or a passive
observer of another App Server. Ordinary independently launched Codex is unchanged.

Managed capture is default-off. Without `SUMMITFLOW_CODEX_MANAGED_CAPTURE=1`, the
entrypoint immediately executes native `codex app-server --listen stdio://` without
an outbox, schema probe, SDK call or Agent Hub dependency. To opt into shadow capture,
set the following in the existing managed operator environment:

| Variable | Contract |
| --- | --- |
| `SUMMITFLOW_CODEX_MANAGED_CAPTURE` | Exactly `1` enables managed capture; absent/other values use rollout only. |
| `SUMMITFLOW_CODEX_OUTBOX` | Explicit private SQLite path, one owner per outbox. |
| `SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES` | Explicit positive logical raw-payload plus immutable catalog quota. SQLite fixed pages, indexes and journals add overhead. |
| `SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS` | Explicit nonnegative acknowledged raw retention; zero clears accepted payloads immediately. |
| `AGENT_HUB_API` | Existing Agent Hub API location, default `http://localhost:8003/api`. |
| `INTERNAL_SERVICE_SECRET`, `SUMMITFLOW_CLIENT_ID` | Existing approved service credentials; loaded privately from process environment or `~/.env.local`. Never put values in command examples/logs. |

The existing `codex-session-sync.service`/timer runs through SummitFlow's managed
Python environment, including the bundled public Agent Hub SDK. Its approved
EnvironmentFile is optional. The existing sync service is declared an optional
worker; its existing timer stays active independently. Timers are not collector
service entries. Managed rebuild refreshes the service template and retains
active/inactive worker policy.
No rollout polling or reconciliation depends on successful capture or delivery.
Before normal transcript ingestion, sync tries managed source registration; afterwards
it drains durable pending receipts. Either failure preserves rollout operation. The
same timer retries after Agent Hub recovery. `st sessions managed-codex --drain`
performs an explicit bounded delivery pass, including when capture is disabled.

Installed support is `codex-cli 0.159.2`, stdio JSON-RPC and schema fingerprint
`6f7a929fad56ae9fc103a8364f0a7f51bd520c007b826d8e3edf5fe167c253e2`.
Version/schema are probed from the installed executable before startup and recorded
in each source registration. Notification/request shapes are checked as captured;
unsupported raw evidence remains retained or quarantined without an invented subject.
Legacy approval requests lacking an exact modern turn/item subject are explicitly
quarantined and fail capture; they are never silently treated as global messages.
Unsupported startup fails clearly with content-free local health. Unsupported live
capture, storage failure or oversized frames preserve the native connection and
explicitly fall back to rollout. A live child requires client subscription/resume;
spawn ownership alone is not proof of captured child notifications.

## Delivery and health

Private directory mode is 0700, database/locks 0600, no symlink database/lock targets.
SQLite FULL commits precede forwarding native events or an existing authority's
approval response. Original envelopes, producer UUID, epoch UUID and source positions
survive restart. Process and delivery leases fence local concurrent owners. Pending
evidence is never evicted; quota exhaustion stops capture and records a gap if storage
permits. Acknowledged rows expire on capture, delivery or status according to configured
retention using SQLite secure deletion. Unbound quarantine remains pending until
explicit forensic association; quota still bounds it. Canonical receipts/issues stay
in Agent Hub, not the local delivery copy. Database page high-water storage is reused;
logical expiry does not claim filesystem snapshots or storage backups were erased.

Only Agent Hub's exact durable receipt disposition and contiguous checkpoint permit
local acceptance. Registration cannot acknowledge an unsent local row. Conflicts,
stale acknowledgements and gaps remain pending, with content-free delivery health.
Restart reconnects by starting another owned process and the controlling client
explicitly resuming an owned thread. It retains the same epoch/position sequence,
records a live gap, and never reconstructs missed approvals or turns from snapshots.
Raw payloads can contain sensitive session data and are never operational logs.

Use `st sessions managed-codex --status` for local health/pending counts. Agent Hub's
project-authorized `GET /api/session-ingestion/sessions/{thread}/native-capture`
reports durable sources, positions, receipt/issue counts, missing prefixes and capture
health without contacting a native process. Internal owner-only receipt/issue query
routes retain evidence access; approval subjects distinguish source/connection/request
position/turn/item. Usage remains snapshots, not duplicated accounting. Requested
and configured model values never imply observed delivery; absent attributable runtime
delivery evidence, the delivered model remains unknown.

## One-step rollback

Run `st sessions managed-codex --disable-capture` in the managed project with its
outbox configured. The running proxy observes the durable switch on its next protocol
message, retains a disabled marker, and forwards the same native connection without
capture. Pending delivery and rollout remain available. Future launches using that
outbox immediately execute native App Server. Separately unset/set the enable flag to
`0` to make all future launches rollout-only. No deletion, receipt rewind, service
restart or approval replay is involved. There is no automatic re-enable of the
durable disable switch; a future reviewed re-enable procedure must preserve its epoch
and pending evidence. Do not delete an outbox with pending/quarantined evidence.

## Verification and remaining stages

The content-free [installed-runtime canary receipt](evidence/managed-codex-canary.json)
records the pinned runtime and exercised cases. The canary runs under `unshare -Urn`,
checks that loopback is the only interface, uses a scripted local Responses provider,
and isolates HOME/CODEX_HOME without credentials. No external or target traffic occurs.

```
st check cleanroom --env CODEX_REAL=/home/kasadis/.local/bin/codex-real -- \
  unshare -Urn /srv/workspaces/projects/summitflow/backend/.venv/bin/python \
  scripts/codex-managed-canary.py --output /tmp/architecture-d-release-canary.json \
  --evidence-directory /tmp/architecture-d-release-private
```

The evidence-directory option exports only toy outbox/rollouts with private permissions
for Agent Hub's actual isolated PostgreSQL acceptance; omit it for ordinary conformance.
Remove the private toy export after those tests. The local launcher path above is
host-specific; verify its native binary mapping when running elsewhere.

```
# Agent Hub, isolated migration-owned PostgreSQL schema:
ARCHITECTURE_D_CANARY_EVIDENCE=/tmp/architecture-d-release-private st check pytest -- \
  tests/services/session_ingestion/test_native_observations.py \
  tests/services/session_ingestion/test_native_sdk.py \
  tests/api/test_session_ingestion.py --run-integration -q

# SummitFlow:
st check pytest -- tests/unit/test_codex_managed_capture.py \
  tests/unit/test_codex_session_sync_entrypoint.py \
  tests/unit/test_codex_session_sync_service.py tests/unit/test_codex_sync_runner.py \
  tests/scripts/test_workspace_package_selection.py -q
```

The PostgreSQL suite passed 22 tests, including atomic rollback, concurrent receipt
replay and actual canary evidence with registration before/after rollout ingestion.
The SummitFlow focused suite passed 64 tests. All 50 collector Rust tests passed,
including a real registry-load regression that reproduced and fixed an invalid
`.timer` worker entry before deployment. The focused suite covers durability,
ownership fencing, quota, Agent Hub downtime,
lost acknowledgements, approvals, explicit rollback and unsupported evidence tests.
The runtime canary passed nine cases, including live rollback. These are isolated
tests, not proof of deployed real-service outage recovery or physical disk durability.

Promotion is **shadow**, default-off. Command entities reconcile matching durable
thread/turn/item identities and multiple receipts; rollout remains the timeline and
usage authority. Provisional `item-*` snapshot/live receipts remain unresolved until
the runtime supplies an attributable durable-ID mapping. Content/position similarity
is not such evidence. Live-first timeline sequence allocation, non-command canonical
projection, production comparison rates/latency, deployed outage/hard-kill/storage
fault recovery and source rotation remain unproven. There is no promotion flag that
bypasses these acceptance gaps. Extend Agent Hub's existing projection contract and
prove these cases before changing authority; downstream availability must remain
independent of App Server. See Agent Hub's `native-observation-v1.md` for the exact
envelope, acknowledgement, identity and reconciliation contracts.
