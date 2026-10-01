# Managed Codex sessions: Architecture D

SummitFlow owns explicitly launched App Server processes, transport and the private
local delivery copy. Agent Hub owns protocol qualification, durable receipts,
normalization, model evidence, reconciliation, checkpoints and canonical activation.
The existing host rollout collector remains enabled for managed and independently
launched sessions. No new service or parallel normalization store is introduced.

## Owner configuration and controls

`st sessions managed-codex` starts native stdio App Server for a controlling client
in its registered project. It is not a TUI launcher. Code defaults capture off;
without `SUMMITFLOW_CODEX_MANAGED_CAPTURE=1`, it executes native App Server directly.
Approved host settings use the existing private `~/.env.local` and optional managed
service EnvironmentFile; explicit process environment values take precedence.

| Variable | Contract |
| --- | --- |
| `SUMMITFLOW_CODEX_MANAGED_CAPTURE` | Exactly `1` opts managed launches into capture. |
| `SUMMITFLOW_CODEX_OUTBOXES_JSON` | Trusted mapping of registered project IDs to distinct absolute private SQLite paths; never accepted from HTTP. |
| `SUMMITFLOW_CODEX_OUTBOX` | Legacy single-spool path, used when the mapping is absent. |
| `SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES` | Positive logical raw/catalog/metadata quota. Approved host policy is `268435456` (256 MiB) per spool. SQLite pages/indexes add fixed overhead. |
| `SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS` | Nonnegative accepted raw retention. Approved host policy is `0`, which removes accepted local payloads immediately. |
| `AGENT_HUB_API` | Existing Agent Hub API location. |
| `INTERNAL_SERVICE_SECRET`, `SUMMITFLOW_CLIENT_ID` | Existing owner service credentials, read privately. Never put values in operational logs or examples. |

Each configured project has its own process fence, producer/epoch, quota, delivery
lease, runtime selection and capture switch. Default status selects `agent-hub` when
configured, otherwise the first sorted project. Project controls require the exact
configured and durably bound project; a mixed or mismatched spool fails closed.
The existing `codex-session-sync.service`/timer drains every configured spool
independently, including while capture is off. A failing spool does not prevent the
other project's delivery or ordinary rollout ingestion.

CLI controls are `--status`, `--drain`, `--disable-capture`, `--enable-capture` and
`--update-action`. The existing authenticated owner interface also exposes
`GET /api/projects/managed-codex?project_id=...` and
`POST /api/projects/{project_id}/managed-codex/{action}`. Mutations require the active
owner and same origin; forwarded local-bypass identities cannot grant access. Status
returns configured project IDs, content-free health, counts, versions and supported
actions; it never returns filesystem paths, prompts or credentials. Agent Hub links
use its registered frontend. `promotion_state=agent_hub_controlled` delegates
canonical authority honestly to Agent Hub rather than claiming a local projection
mode.

## Process lifecycle and transport

Only the process started by this owner is supervised. A lifetime lease rejects a
competing launch; independent App Servers and external thread IDs are never attached
or signalled. The controlling client supplies `initialize`/`initialized`, turn
operations and every approval decision. Initialization must complete before owned
operations. The supervisor never replays a turn or approval decision.

Owned child provenance permits an internal `thread/resume` subscription. Internal
responses stay private to the transport; snapshots retain their stored origin and
parent provenance. Subscription does not fabricate omitted child notifications.
The controller remains the approval authority for parent and child requests.

For owned `turn/start` and `turn/steer`, the supervisor adds an opaque
`clientUserMessageId` only when absent and preserves caller-supplied IDs. The native
`userMessage.clientId` response provides exact correlation across provisional
`item-*` and UUID representations. Agent Hub alone decides canonical aliases;
missing correlation stays unresolved. This transport correlation is not a canonical
cursor and does not alter independent clients.

Restart starts another owned process. The controller explicitly resumes an owned
thread; producer/epoch and per-source positions persist. A durable live gap records
that snapshots cannot reconstruct missed notifications or pending approvals.
Disable retains pending evidence and forwards the same connection. Re-enable
preserves source positions, clears stale approval correlations and records the
uncaptured interval before capturing subsequent messages. Neither action executes
stored decisions.

## Durability and delivery

Private directories are owned mode0700, SQLite/locks mode0600, with no symlink
DB/lock targets. SQLite FULL commits precede forwarding retained native evidence
or an approval response. Atomic `BEGIN IMMEDIATE` schema migration recovers old or
interrupted legacy event tables without dropping pending raw evidence. Concurrent
initializers share the same migration fence.

Original envelopes and immutable producer/epoch/source positions survive restart
and lost acknowledgements. Protocol updates create explicit successor generations
with the exact predecessor source; pending older generations deliver first. The
independent rollout source keeps its original stable registration profile. Agent Hub
owns rollout rewrite/reset lineage and canonical checkpoints.

Only Agent Hub's exact durable disposition for the sent position advances the local
delivery copy. Registration and future server checkpoints cannot acknowledge an
unsent local row. Conflicts retain their raw envelopes. Quarantine uses truthful
project/producer/epoch/connection provenance and its own per-source positions, with
no fabricated thread/session. A lost quarantine acknowledgement replays the exact
original receipt; fresh `quarantined` acceptance removes it according to retention.
Legacy unbound rows without truthful registration stay pending for explicit review.

Quota exhaustion never evicts pending or conflicted evidence. Unsupported versions,
shapes, policy/storage failures and oversized frames report content-free health and
preserve native execution with rollout recovery. A storage failure may also prevent
the gap marker itself; stderr then states that limitation. Project binding mismatch
and competing ownership remain hard errors. Accepted expiry uses secure deletion
and incremental vacuum to reclaim physical pages, not just logical row accounting.
Backups and filesystem snapshots have their own retention policy.

## Frequent updates and rollback

Bundled tested profiles retain `codex-cli 0.159.2` and `0.159.3`. Actual version,
generated schema fingerprint and binary identity are checked and cached before
capture. Unknown versions require an Agent Hub approved profile; changed schemas
fail capture and use native/rollout fallback.

Owner actions form a concrete update path:

1. `check-update` reads the official npm registry version without installing.
2. `stage-update` explicitly installs that exact version into a private temporary
   prefix, with lifecycle scripts disabled. It pins the native executable and its
   adjacent vendor resources; it never modifies the global Codex installation.
3. `qualify-update` runs the full installed-runtime canary in `unshare -Urn`, with
   only loopback and a scripted local provider, isolated HOME/CODEX_HOME and no
   account traffic. An unknown version must have an exact known compatible schema.
   Agent Hub validates and durably approves the complete receipt before the local
   candidate becomes qualified. Changed protocol shapes need an updated tested
   public profile; qualification cannot invent one.
4. `promote-update` selects the qualified private runtime for future launches.
   `rollback-update` selects the preserved previous runtime. Retried promotion or
   rollback is idempotent and retains the original rollback target.

Private runtime identities hash deterministic resource paths, executable modes and
bytes, not just the executable. Copy validation detects concurrent changes and
selection verifies the entire tree. The local context wrapper resolves to its
actual native package before pinning. Running processes hold independent filesystem
runtime leases, so SQLite quota/marker failure cannot let cleanup remove live
resources. Cleanup runs under the owner update lease on launches and successful
update actions; it retains active, candidate, previous and running references and
prunes only unreferenced unlocked content-addressed trees. Thus weekly updates do
not retain every historical runtime indefinitely. Active sessions keep their pinned
runtime and resources across promotion; no running session is upgraded in place.

## Verification

All project checks run through ST. The permanent canary exercises initialization,
commands, controlling-client approvals, interruption, read/resume/compaction/fork,
ownership fencing, external rejection, child subscription, usage, durable restart,
disable/re-enable, quota fallback, exact client message identity and actual private
runtime/resource promotion and rollback. It records provider request counts,
content-free gap reasons and unbound methods. Deliberate restart/disable intervals
and native warnings before child ownership remain explicit capture limitations;
passing case flags do not claim uninterrupted live capture.

```sh
st check cleanroom --env CODEX_REAL=/home/kasadis/.local/bin/codex-real -- \
  unshare -Urn /srv/workspaces/projects/summitflow/backend/.venv/bin/python \
  scripts/codex-managed-canary.py --project agent-hub \
  --output /tmp/architecture-d-canary.json \
  --evidence-directory /tmp/architecture-d-private

st check pytest -- tests/unit/test_codex_managed_capture.py \
  tests/unit/test_codex_managed_update.py tests/unit/test_codex_managed_projects.py \
  tests/unit/test_codex_managed_operator_api.py \
  tests/unit/test_codex_session_sync_entrypoint.py \
  tests/unit/test_codex_session_sync_service.py tests/unit/test_codex_sync_runner.py \
  tests/unit/test_codex_sync_transcripts.py -q
```

`--project` defaults to `canary`. A registered project argument truthfully binds the
toy fixture for later owner-authorized local Agent Hub delivery outside the network
namespace. Private exports contain only toy outbox/rollouts with mode0700/0600;
remove them after integration checks. Deployed acceptance, canonical activation,
service rebuilds and production host configuration are separate managed operator
steps. See Agent Hub's `native-observation-v1.md` for its receipt, alias, profile and
canonical projection contracts.
