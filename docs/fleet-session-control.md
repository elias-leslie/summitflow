# Fleet session control

`st sessions start "short sanitized instruction"` registers an opaque `root-…`
handle in the existing events table and requests a root through Aico's private
GUI socket. The project root comes from the registered project, not a client path.
Use `--surface a-term` for the existing local A-Term owner HTTP route; unknown
surfaces are unsupported. The same role/lead/facet capsule goes to either owner.
The returned host descriptor is an Aico acknowledgment; it does not attest a
delivered model or a Codex queue delivery. An unavailable or uncertain launch is
retained. Retry with `--request-id ROOT` and the same capsule; do not recreate a
root after an uncertain response.

`st sessions send ROOT "instruction" --source-key REVISION --scope '{...}'`
retains the exact bounded sanitized instruction, digest and immutable scope for
the addressed root to consume through `wait`. It reports `capability=fleet-stream`,
`delivery=available-via-wait` and `native_capability=unavailable`. It never pastes
into a terminal or claims an accepted model queue. Initial create prompts remain
transient host input with retained digest/source references only.
Instructions must not contain credentials, private target data, or transcripts.
The sanitizer removes common credential forms and control characters, but does
not prove that arbitrary content is non-secret. The caller owns that content boundary.

For an existing ordinary Codex session, local owner CLI delivery is explicit:

```sh
st -P PROJECT sessions send EXACT_THREAD_UUID "short non-secret instruction" --delivery native-thread --source-key REVISION
```

This mode verifies the exact local native provenance and registered project root,
honors an existing immutable project binding, and reuses the synchronizer's
canonical Git/Aico owner mapping when no explicit binding exists. Unknown,
foreign, ambiguous, or spawned subagent identities are rejected. Offline threads
remain addressable when their retained header and project mapping are verified;
queued input can execute when that same thread resumes. It addresses the durable
thread, not an Aico/A-Term process generation, and does not change their owner
`send` endpoints. No Enter, terminal paste, or agent polling is required.

The existing events table retains a source-key/content reservation before the
single native `thread/queue/add` attempt. Only the reservation winner dispatches.
The reservation stores the instruction digest and exact destination, without a
second prompt copy; the native queue owns the submitted payload.
Native queue acceptance returns `delivery=queued`, a queue ID and a correlated
client message ID; `observed=false` means no consumption evidence was checked.
Retries with the same source key return the retained outcome without resending;
changed content conflicts. A crash or missing reply leaves `pending-or-uncertain`
or `uncertain`, including a lost acknowledgment after native acceptance. Do not
use a new source key to blindly replay an uncertain attempt. Native client IDs
are correlation identifiers, not a proven provider deduplication guarantee.
Reservations and receipts survive routine fleet retention to prevent replay.
This local owner operation requires access to the existing SummitFlow database
and native client; it is not a remote transport or an exactly-once claim.

`st sessions wait ROOT --cursor SEQUENCE` drains committed pages by exclusive
stream sequence. The default wait is 300 seconds. An empty timeout prints nothing
and creates no event. Cancellation also creates no event. Redis wakeups are
advisory. Wait drains PostgreSQL, subscribes to Redis, and rechecks after subscription
to cover a commit in that gap. A wake drains by durable sequence, never by the
advisory message payload. One deadline read recovers a failed publish, and a
30-second fallback read applies only while Redis is unavailable.
Use the returned cursor on the next wait, and use `st sessions show ROOT` for the
current capsule instead of replaying the entire history to refresh context.

Existing `show` and `close` accept opaque root handles, and `list --fleet` lists
fleet roots. Other session readers continue using their existing Agent Hub path.
`st sessions activate ROOT` uses the exact stored generation to show or reattach
the root. `st sessions position ROOT X Y WIDTH HEIGHT` arranges Aico roots with
validated bounds; A-Term positioning reports unsupported.
Close requests native End through Aico's existing private owner socket with the
stored exact widget identity and generation fence. An acknowledged End or an exact
matching provider-owned ended tombstone closes the allocation and releases its
facet. Missing, stale, or failed End
retains `close-uncertain`, which blocks replacement and cannot free native capacity.
A closed or uncertain root is never automatically relaunched.

Portfolio roots remain independent. A focus allocation adds one
`--role neri-target-root --scope '{"target":"…","claim":"…","run":"…"}'`
lead and bounded `--role neri-support-root --lead-root ROOT --facet REF` roots.
Support roots use the lead's exact target/claim/run scope and are offline by
default; each open facet is disjoint by exact reference. Capsules must supply
the source material needed for that facet. This linkage grants no target
authority or qualification for simultaneous live operators. Neri owns those
decisions. Closing a support lane permits a new opaque root for the same facet,
retaining the old lineage. Current role, lead, facet and scope survive restart in
retained lifecycle rows.

The owner-authenticated versioned endpoint
`POST /api/fleet/v1/roots/ROOT/events` accepts a compact sanitized source reference,
event type, stable source revision key and canonical content digest. External
extensions use `st_sdk.fleet.FleetClient.append`; it computes the SHA-256 digest
over canonical JSON `[event_type, attributes]`. Control events use their owning
commands. No full transcript or terminal output belongs in these attributes.
Roots can use `st sessions emit ROOT EVENT_TYPE --source-key REVISION --attributes '{...}'`
to return compact typed result/progress refs and change deltas through the same seam.
Per-trace transaction advisory locking orders allocation with commit, and a
same-key/same-digest retry returns the same retained identity. A mismatch is 409.
Database failure never wakes Redis; Redis failure never removes committed rows.

Retention preserves lifecycle rows and the latest high-water event under the
same lock, so append never reuses a pruned sequence. A skipped retained sequence
returns explicit `stale_cursor` with the next retained sequence. Reconcile current
source revisions and the current capsule before choosing a new cursor. Delivery
is at least once and advisory, not exactly once. Idempotency keys are guaranteed
while their rows are retained; producers must reconcile an expired revision
against the source before retrying after a retention gap.

The API host socket defaults to `/run/user/<uid>/aico/gui-control.sock` and supports
`AICO_GUI_CONTROL_SOCKET` for the existing host configuration. Native End uses
`/run/user/<uid>/aico/control.sock` or `AICO_CONTROL_SOCKET`. No new dependency,
queue, scheduler, session store, or mandatory Agent Hub telemetry is introduced.
The schema migration and SDK wheel must be installed through the existing release
workflow before these commands are available in an accepted runtime.
A-Term defaults to `http://127.0.0.1:8002` and supports the local
`A_TERM_ROOT_CONTROL_URL` override. Existing password/proxy mode rejection is
reported as unavailable; the adapter does not supply or invent credentials.
# Direct exact-thread recovery

`st sessions title REQUEST_ID "Project · Focus" [--surface aico|a-term]` renames
one exact running retained owner root. The default owner is Aico, matching direct
create; use `--surface a-term` for A-Term. The command reads that exact request,
then posts `{generation, label}` to `/v1/roots/REQUEST_ID/title`. Missing, ended,
uncertain or stale generations cannot authorize an update. After trimming surrounding
whitespace, labels require 1-160 UTF-8 bytes of control-free single-line Unicode.
Code points below 32, 127-159, surrogates and U+2028/U+2029 are rejected.
Supply no secrets or private target data.
Content exists only in the input and the owner's existing session metadata.
SummitFlow retains no title, fleet event or duplicate session store, and output
contains only identity/status metadata. Configured owner authentication applies.
Owner source changes require their normal managed release before live use.

`st aico create REQUEST_ID [PROMPT] --project PROJECT --project-root PATH
--resume-session SESSION_ID [--surface aico|a-term]` forwards directly to the existing
owner create contract. It retains no prompt or fleet event and supplies no fleet
orchestration text. The public ID is TUI-agnostic; only the Codex resume adapter
is currently implemented, requiring a canonical lowercase UUID.
The default surface is Aico; A-Term uses its established loopback HTTP route and
enforces configured authentication. Aico shows the allocated root; A-Term creates
a detached pane. Neither command starts the owner service.

The optional prompt is sanitized and limited to 2000 UTF-8 bytes; `--stdin`
supplies the same bounded input. Without a prompt, resume uses a fixed instruction
to reconcile current state after the crash before continuing. Retry with the same
request ID and complete body; changed content conflicts and ended roots remain
tombstones. This is explicit exact recovery, not an automatic reboot scheduler.
Running receipts prove workload presence, not native thread loading or model
readiness. Direct `st aico create` roots have no fleet-event ledger; `sessions
emit` and `sessions wait` apply only to roots registered through fleet start.
Owner code changes need a managed rebuild before live use.

## Ordinary Aico widget controls

Use the ordinary-widget owner commands for the current managed pane before desktop
automation:

```sh
st aico widget status
st aico widget title "Project · Focus"
st aico widget position 0 0 960 720
```

Each command defaults to the exact `AICO_WIDGET_ID` inherited from the managed pane.
Use `--widget-id 0123abcd` to select another exact widget explicitly; the selector
requires eight lowercase hexadecimal characters. Missing or invalid identity fails
closed. Ordinary widgets have no retained root request ID, and these commands do not
discover fleet roots or infer a widget from a native thread.

The private GUI socket is the same configured `AICO_GUI_CONTROL_SOCKET`, with
`--root-socket PATH` available for an exact local socket. Status reads
`GET /v1/widgets/ID`, returning only owner, widget ID, session ID, generation,
status and availability. A title or position mutation reads this exact descriptor
immediately first, requires a running available workload, posts the generation to
`/v1/widgets/ID/title` or `/v1/widgets/ID/position`, and verifies the returned
identity and generation. GUI absence, missing widgets, changed identity and stale
generations fail closed; commands never start Aico.

Labels use the same non-secret 1-160 trimmed UTF-8 byte, control-free single-line
validation as retained root titles. Integer bounds require absolute values at
most 100000, width at least 360 and height at least 240. Content goes only to the
owner's existing session metadata. Receipts and errors contain no label, and ST
adds no fleet event or duplicate session record. Existing retained-root commands
continue addressing their exact request IDs.
