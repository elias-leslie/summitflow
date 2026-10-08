# Retained tool-result cost

`st tools cost` measures recorded result payloads, not named call rows. Results
without a tool name resolve through a use row with the same session and call ID.
One authoritative result is selected for each call; results without a call ID
remain distinct. The lookback uses source time when available, so importing old
history today does not make it today's output. Incomplete capture stays unknown.

The report includes UTF-8 payload bytes, measured result counts, p50/p95/max,
truncation evidence and coverage, and separate wrapper and nested counts. An
exact nested-command correlation to a measured wrapper identifies execution
provenance; it is excluded from the delivery summary. A provisional correlation
remains separate and may overlap. Payload text repeated in JSON metadata and
content is measured once. Retained bytes are not provider context or billed cost.

Use `st tools cost --advisory --session <session-id>` for a bounded diagnostic.
`--gate` is an alias. Healthy and unknown cases emit one small line; advice is
limited to 1.5 KB. Both modes exit successfully when telemetry is missing or a
database query fails. They never authorize, stop, or schedule work. Ordinary
cost inspection retains its detailed output; `st --no-compact tools cost`
returns structured measurements. Queries use a read-only connection and a
10-second statement timeout.

Advice requires observable evidence:

- At least 20 measured results, with confirmed truncation in at least 10%.
  The rate is a lower bound; missing truncation flags are unknown.
- At least three unchanged retrievals in the same recorded role/task, with
  at least 32 KiB of duplicate bytes after the first retrieval.
- At least two unchanged catalog or task-packet retrievals of at least 32 KiB
  where an existing compact or file route is known.

Repeat detection uses exact command/output fingerprints in PostgreSQL and sends
only aggregates to the CLI. Its supported retrieval commands are listed in the
query; arbitrary shell scripts and opaque tools remain unclassified. A wrapper
with exactly one correlated nested command can use that command's identity.
Recorded session `agent_slug` and a recognized `task-...` caller `external_id`
supply role/task scope; other correlation IDs and absent scope do not establish
repeated same-task work. No source content is
printed. Large useful source reads alone do not trigger advice, nor do changed
results, aggregate tokens, HTTP errors, or missing telemetry.

Native usage groups response records by observed model and source. Cached input
keeps its field coverage. Uncached input is calculated only for response records
with both valid input and cached-input counters; it is never derived by
subtracting aggregates with different coverage. Cumulative counter observations
remain separate. Unknown model attribution, capture completeness, and billed cost
remain unknown.

Automatic cadence requires a separate authorized runtime or prompt caller for
this diagnostic. This command adds no timer, polling loop, LLM call, feedback
publication, lifecycle rule, or schema migration.
