# Fleet session control

`st sessions start "short sanitized instruction"` registers an opaque `root-…`
handle in the existing events table and requests a root through Aico's private
GUI socket. The project root comes from the registered project, not a client path.
`--execution-root PATH` optionally selects a different existing checkout for the
owner's working directory. The immutable capsule and returned state retain both
the registered `project_root` and effective `execution_root`; omitting the option
executes in the registered root. `FleetClient.start(execution_root=PATH, ...)`
uses the same versioned API field.

Supply an absolute, normalized directory path without symlink aliases. The
directory must be the registered root or inside it, or a strict descendant of
`projects` or `worktrees` under the existing `ST_WORKSPACES_ROOT`
(the shared workspace helper supplies its normal default). It must have the same
project checkout identity, validated through the existing identity manifest or
legacy Git checkout validator. Foreign, missing, malformed, or unqualified
directories fail before intent is retained or launch is requested. This option
does not create or manage directories. Changing the effective execution directory
for a retained request ID conflicts; retry with the same complete capsule.
Older retained capsules without this field expose the registered root as their
execution root and keep their original create digest on a default retry.

Use `--surface tether` to address Tether (the per-user session daemon that owns
Aico sessions) directly; unknown surfaces are unsupported. `--surface a-term` is
retired: new roots are refused (see the cutover note below). The same
role/lead/facet capsule goes to every owner. Tether keeps Aico's root contract
and reports `owner: "aico"` on its root descriptors.
The returned host descriptor is an owner acknowledgment; it does not attest a
delivered model or a Codex queue delivery. An unavailable or uncertain launch is
retained. Retry with `--request-id ROOT` and the same capsule; do not recreate a
root after an uncertain response.

`--resume-session SESSION_ID` passes one exact saved native session ID to the
owner's resume adapter, which launches it in the newly allocated root (Claude
Code and Codex each take a canonical lowercase UUID; Tether refuses other tools
with `unsupported_tool`). There is no picker,
latest-thread inference or terminal input. Start validates the ID's bounded
shape and that the instruction plus fleet directions fit the owner's 2000-byte
resumed-prompt limit before it registers intent. The capsule retains only
`resume_session_digest`, never the native ID; a retry with a different ID
conflicts. Generation fencing and `close-uncertain` behave exactly as for fresh
roots. Fresh starts send the unchanged owner body and capsule.

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
`st sessions activate` and `st sessions position` are gone with the Aico desktop
windows: there is no window to show or arrange. Sessions show in Aico web.
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

The `aico` surface prefers Tether: when `GET /v1/health` on Tether's socket
(`$XDG_RUNTIME_DIR/tether/default/control.sock`, or `TETHER_SOCKET` /
`TETHER_INSTANCE`) answers `ok` with a serving lifecycle, root requests and native
End go to that socket, which serves the same `/v1/roots*` and
`/v1/sessions/ID/end` routes and bodies. Otherwise the host socket is
`/run/user/<uid>/aico/gui-control.sock` and native End uses
`/run/user/<uid>/aico/control.sock`, exactly as before Tether. An explicit
`AICO_GUI_CONTROL_SOCKET` or `AICO_CONTROL_SOCKET` always wins. After the cutover
Tether also serves those legacy sockets, so either path reaches the same owner.
The `tether` surface always uses Tether's socket. Stored `aico`, `a-term` and
`tether` surface values all stay readable; no retained capsule is rewritten.
No new dependency,
queue, scheduler, session store, or mandatory Agent Hub telemetry is introduced.
The schema migration and SDK wheel must be installed through the existing release
workflow before these commands are available in an accepted runtime.
The `a-term` surface is retired. Aico's web server (`aico-web.service`) no longer
serves `/v1/roots`, and port 8002 is gone, so there is no A-Term root route and
`A_TERM_ROOT_CONTROL_URL` is ignored. The value stays valid in stored fleet
events (it is a wire value, not renamed): `st sessions show` still reads those
roots, but starting one is refused, and activate, position and End on one report
unavailable or unconfirmed. Use `--surface aico` or `--surface tether` instead.

# Direct exact-thread recovery

Owner operations for one exact retained root live under `st aico root`:

```sh
st aico root status REQUEST_ID
st aico root title REQUEST_ID "Project · Focus"
st aico root end REQUEST_ID
```

They address direct `st aico create` roots and fleet-started roots alike. Title
reads the exact request, requires a running descriptor, posts its
generation once and verifies identity and generation in the receipt. Missing,
ended, pending, uncertain or stale roots cannot authorize that update.
`root show` and `root position` are retired: Aico has no desktop windows any more;
sessions show in Aico web, so they print that and exit 2.
`applied: false` means nothing was applied; `applied: null` means the outcome is
unknown and must be reconciled with `st aico root status`, never blindly retried.
End pins the exact descriptor's generation and may contain a pending or uncertain
root without requiring a running workload. It uses Aico's headless
generation-fenced containment contract. An exact
ended tombstone is idempotent: End returns `applied: false` without another owner
mutation. A root without a generation cannot authorize End. For fleet roots
prefer `st sessions close`, which records the outcome in the fleet ledger; a
direct end leaves fleet state to reconcile on the next close.

`st sessions title REQUEST_ID "Project · Focus" [--surface aico|tether]` remains a
compatibility alias that forwards to `st aico root title`. For `aico` (when Tether
is running) and `tether` it passes `--root-socket` with Tether's socket. `st aico` has
no `--surface` or `--root-url`; stored roots with owner `a-term` are still read and
titled through Tether. The owner extension
performs all validation and reports the receipt. Labels require 1-160 UTF-8 bytes
of control-free single-line Unicode after ECMAScript whitespace trimming. The
owner's `contracts/view-mutation-vectors.json` pins label and bounds rules for
both its title handler and its Python client, so SummitFlow keeps no separate
label validator. Supply no secrets or private target data. Content exists only
in the input and the owner's existing session metadata. SummitFlow retains no
title, fleet event or duplicate session store, and output contains only
identity/status metadata. Configured owner authentication applies. Owner source
changes require their normal managed release before live use.

`st aico create REQUEST_ID [PROMPT] --tool claude-code|codex --project PROJECT
--project-root PATH --resume-session SESSION_ID [--surface aico]` forwards
directly to the existing owner create contract. `--tool` has no default and the
client keeps no tool list: it sends the tool as given, and Tether refuses one
without a resume adapter with `unsupported_tool` naming the tools it accepts
(today claude-code and codex). Each tool runs the model set in its own configuration. It retains no prompt or fleet event and supplies no fleet
orchestration text. The public ID is TUI-agnostic; the Claude Code and Codex resume
adapters each require a canonical lowercase UUID. Tether's `docs/root-control.md`
is the contract.
The default surface is Aico, which shows the allocated root. The command does
not start the owner service.

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

Use the ordinary-widget owner commands for the current managed pane:

```sh
st aico widget status
st aico widget title "Project · Focus"
```

Each command defaults to the exact `AICO_WIDGET_ID` inherited from the managed pane.
Use `--widget-id 0123abcd` to select another exact widget explicitly; the selector
requires eight lowercase hexadecimal characters. Missing or invalid identity fails
closed. Ordinary widgets have no retained root request ID, and these commands do not
discover fleet roots or infer a widget from a native thread.

The private GUI socket is the same configured `AICO_GUI_CONTROL_SOCKET`, with
`--root-socket PATH` available for an exact local socket. Status reads
`GET /v1/widgets/ID`, returning only owner, widget ID, session ID, generation,
status and availability. A title mutation reads this exact descriptor
immediately first, requires a running available workload, posts the generation to
`/v1/widgets/ID/title`, and verifies the returned
identity and generation. GUI absence, missing widgets, changed identity and stale
generations fail closed; commands never start Aico.

Labels use the same non-secret 1-160 trimmed UTF-8 byte, control-free single-line
validation as retained root titles. Content goes only to the
owner's existing session metadata. Receipts and errors contain no label, and ST
adds no fleet event or duplicate session record. Existing retained-root commands
continue addressing their exact request IDs.

## Coordination between running agents

Use `st sessions send AGENT_ID "question"` for another coordinating parent,
then answer incoming requests with `st sessions ack ID yes|no 'reason'|eta:MIN`.
The sender closes an answered exchange with `st sessions confirm ID`.
Keep messages short: agent, repo, coarse paths and ETA. Workers answer only
requests addressed to themselves; parent requests survive chat resets.
`st sessions inbox` distinguishes recorded (`open/unseen`), shown (`open/seen`)
and answered (`acked`), including the acknowledgment's reply note. A send receipt
alone does not prove a reply.
Use one channel; do not also type the message into the other terminal.

For a quick exchange, discover the peer's widget with `st aico sessions`, send
`st sessions send WIDGET_ID "question" --source-key STABLE_REVISION`, and read
`st sessions inbox` in each agent's own session. The receiver runs
`st sessions ack ID yes "short reply"` (or `no "reason"` / `eta:MIN`); the sender
reads the reply in its inbox and runs `st sessions confirm ID`. An explicit
inbox read works without waiting for an automatic notice. Pi's adapter delivers
new requests after tool results, immediately when a run settles, or within its
15-second idle poll. A request arriving during a provider response waits for
the next supported native boundary; `open/seen` is separate from an actual ack.

How the recipient learns of it: when it runs in an Aico window and Tether has
deliveries (API 16), the send queues one line, `[Message] 1 request from
cc:1c7a9f · st sessions inbox`, on that window's gated delivery queue
(`POST /v1/sessions/WIDGET/deliveries`, source `coord:AGENT_ID`, coalesced per
recipient). Tether delivers it once the agent is idle, nobody is typing and the
input line is empty, or through a native puller; the agent's own turn hook then
shows the request. Acks, reminders every 5 minutes, a lapsed `eta:` and memory
notices go the same way. The line never carries request or reply text. A
window on an agent host gets it through the hub. Recipients SummitFlow cannot
place in a window, shells, agy and an older Tether keep the earlier wakes
(Claude's asyncRewake hook, the Codex idle watcher, the cross-host inject).
`st sessions send --delivery native-thread` reports Tether's own record of
that line: `queued`, or `woken` once it was delivered.

Installed extension updates apply to newly launched or reloaded Pi processes.
A running process keeps its loaded adapter even when the installed symlink
changes. At the agent's next clean idle seam, native `/reload` loads the current
adapter; typing it during active work does not prove that it executed. There is
no atomic ST remote slash-command submission. For activation entirely through
ST, agree a stopped seam, retain the exact Pi native UUID and original project
root, end that exact retained root with `st aico root end REQUEST_ID`, then use
a new `st aico create NEW_REQUEST_ID ... --tool pi --model PROVIDER/MODEL
--project PROJECT --project-root ORIGINAL_ROOT --work-role ROLE
--resume-session EXACT_UUID`. Read the new root receipt and use its widget ID.
Do not end an active peer merely to refresh its extension.


New roots declare their fixed native-session work role with
`st sessions start 'Short instruction' --work-role implementation` (or
`st aico create ... --work-role implementation`). `--work-role-name Builder`
adds an optional human name. The fixed IDs are coordinator, implementation,
research, review, recon, hunting, operations and other. This declaration is
separate from fleet `--role` and is not inherited from the coordinator.

Fleet retains the explicit fields in its immutable creation capsule and passes
`workRole`/`workRoleDisplayName` through the existing owner request. Legacy
capsules and their original retry identity remain unchanged. Tether requires
the field for new roots and exports the creation provenance to native hooks;
Agent Hub binds it to the actual native UUID. Resume keeps that UUID's first
work role. Changing roles requires a new native session or a fitting existing
one. Neither launch path adds work-role text to the initial prompt.
