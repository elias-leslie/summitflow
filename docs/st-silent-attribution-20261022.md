# Silent ST attribution: execution-seam assessment

Task `task-5560be9533ec497f`; base `9cc352c031721679f20b5a3305578a4952776f6c`.
This delivery changes this report only. No CLI collector, dependency, prompt,
tool output, workflow step, Agent Hub write, deployment, or publication was added.

## Decision

Use the existing retained-event read side for the present delivery. The observed
isolated ST shell calls already have duration, retained output, and exit facts.
This supports useful sampled attribution without adding work to every invocation.
It does **not** establish global completeness or exact attribution for compound
shells, hidden scripts, unsupported syntax, other providers, or command targets.

An execution signal has a real potential benefit: 1,863 of 6,036 recognizable ST
source mentions (30.9%) share a shell call, so their individual duration/output
cannot be allocated from retained facts. These are source mentions, including
conditional commands that may not execute, rather than 1,863 proven missing runs.
A CLI observer would also see some script-hidden invocations. It cannot repair
historical data or establish an exclusive task association from a session alone.

A useful producer would need durable asynchronous transport, a consumer using the
existing event contract, and explicit provenance/correlation so observations are
not added to their enclosing transcript calls. No such generic ST execution
transport/consumer was found in the inspected SDK/CLI/scripts. A new spool would
be transport, not an analytics ledger, but an unconsumed spool supplies no
Activity coverage. Complete output counting also crosses Python/native subprocess
stream boundaries; counting only Python writes would mislabel partial output as
complete, while piping all output changes the execution path. Those integration
and streaming costs exceed the demonstrated incremental benefit for isolated
calls. Do not add an unwired recorder as this task's result. Reconsider an
execution producer when a consumer/correlation design and a representative
cross-provider measurement establish its benefit. The shared/hidden gaps remain
explicitly unresolved by this SummitFlow delivery.

## Observed coverage

The uncapped diagnostic window is **2026-10-21 16:50:00 UTC inclusive to
2026-10-22 16:50:00 UTC exclusive**, using `COALESCE(source_timestamp,created_at)`.
It reads tool-use/result inputs transiently for recognition and selects output
lengths in SQL. Only aggregates leave the process; no raw input, output, identity,
environment, or credentials are persisted by the probe.

| Measure | Observed |
| --- | ---: |
| Use/result events before deduplication | 38,074 |
| Deduplicated uses / results | 19,021 / 19,053 |
| Uses without result / results without use in window | 25 / 57 |
| Exact correlated wrappers suppressed | 3,883 |
| Native shell observations linked by exact digest / heuristic single-open wrapper | 3,909 / 6,611 |
| Calls after exact wrapper suppression / with valid duration | 15,138 / 10,863 |
| Native shell calls / parsed / unsupported | 10,863 / 9,957 / 906 |
| Parsed calls with an unrecognized `st` argument position | 60 |
| Unsuppressed `exec` wrappers | 3,562 |
| Those wrappers merely containing `st ` text | 3,152 |
| Unsupported shell calls merely containing `st ` text | 270 |
| Recognizable ST source mentions / enclosing calls / sessions | 6,036 / 5,221 / 63 |
| Recognized enclosing calls with result / valid duration | 5,221 / 5,221 |
| Isolated ST calls with duration / retained output length / exit code | 4,173 / 4,173 / 4,173 |
| Isolated calls with nonzero exit / recorded zero milliseconds | 418 / 10 |
| Shared ST mentions with unallocated duration/output | 1,863 |
| Isolated-call elapsed sum / retained returned characters | 7,014,926 ms / 5,750,089 |
| Normalized ST argv characters, including shared mentions | 592,966 |
| Recognized calls with known session project / unique matching durable task binding | 5,221 / 0 |
| Recognizable ST input mentions in either orphan group | 0 |

Every recognized ST call in this sample belongs to a `codex` session. This does
not validate Claude/Pi/other-provider coverage. Known session project is not the
command's selected project. Durable task coverage uses exactly one distinct,
nonempty `session_bindings.task_id` matching the session project, as Activity
does; external IDs are not task evidence. A unique binding still does not prove
exclusive work for that task.

Deduplication keys are session-local call identity plus event type; authoritative
source events outrank provisional `native-command:` observations. Only
`nested_command_digest` suppresses wrappers. Heuristic `single_open_exec` links
do not prove identity; unsuppressed wrappers can still duplicate text. Wrapper
and unsupported-source text matches are ambiguity counts, **not missing ST run
counts**. The bounded parser recognizes command positions and argv arrays, rejects
unsupported shell syntax, and excludes quoted prose. Assignment/env/sudo prefixes,
scripts and opaque wrappers can hide invocations. No neighboring-call or
equal-duration inference is used. Window orphans and late ingestion can affect
pairing/counts.

These numbers are **not a live Activity snapshot**. Activity caps events at 20,000
across tool/usage data and has its own boundary pairing. Its displayed sample may
contain fewer ST calls and different coverage; retain cap/orphan/unknown evidence
instead of transferring this uncapped probe's completeness to the UI.

## Existing integration contract and source evidence

- `backend/cli/main.py`: the console script is `cli.main:app`; `_RootGroup` lazily
  resolves commands. There is no execution recorder or stdout/stderr interception.
- `backend/cli/extensions.py`: owner execution inherits streams, forwards
  SIGINT/SIGTERM to its child process group, reaps, and preserves exit status.
  Introducing pipes or a capture wrapper would require separate verification.
- `backend/cli/commands/tools_cost.py`: current `st tools cost` already pairs
  retained results and computes text lengths, with source preference and exact
  wrapper handling. Its character approximation is not billed model usage.
- `packages/st-sdk/st_sdk/fleet.py`: `FleetClient.append` posts synchronously to
  root-specific fleet events. It is not an offline generic execution sink.
- `scripts/agent-observability-sync.py` and `backend/cli/_observability.py`:
  existing best-effort refresh invokes Agent Hub's Codex transcript collector;
  it does not consume ST execution records.
- Agent Hub's `backend/app/services/session_ingestion/adapters/_event_builders.py`:
  `_append_codex_response_item` retains opaque `exec` source;
  `_append_codex_command_execution` independently projects native command arrays,
  duration/output/exit facts. Narrow literal-command digest extraction explains
  why exact wrapper correlation does not cover all orchestration forms.
- Agent Hub's public `agent_hub.AgentHubClient.append_session_event` posts synchronously
  to `/api/sessions/{id}/events`. Its normalized batch endpoint is
  `/api/session-ingestion/sessions/{id}/events/append`, accepting existing
  `NormalizedEvent` fields including `source_event_id`, `source_timestamp`,
  `duration_ms`, `surface`, and structured tool metadata. Neither inspected
  contract provides a local transport queue. No endpoint was called by this work.

The read-side consumer should continue using existing session events and a
known-command-family allowlist, counts/lengths only in responses, strong
session/project identities and unique matching durable task bindings or unknown.
Command mentions are not proof of execution. Shared shell duration/output remains
unallocated; unknown output differs from measured empty output, and 0 ms is valid.
Reference-tokenizer input estimates operate on normalized recognized argv;
returned-output estimates use retained character lengths. Both are text-footprint
estimates, not causal provider tokens, resident context, or billed spend. This
probe measured input/output characters; it did **not** tokenize retained text.

Any future execution producer must reuse the public ingestion contract via an
asynchronous consumer, have stable idempotent observation identity and explicit
transcript correlation, retain unknowns, and emit no raw argv/stdin/stdout/stderr,
environment, credentials, or prompt text. It must not double-count with the
transcript, invent provider/task/project identity, perform per-command network
requests, or alter streaming/exit behavior. This is an integration constraint,
not an implemented or newly registered event schema.

## Reproducible evidence and checks

Safe scratch artifacts:

- `/srv/scratch/st-silent-attribution-probe-20261022.py`:
  SHA-256 `262af52ce03af6f9da3485e1a3c7dd0227fe39f0141d2e026faa13995faf591f`.
- `/srv/scratch/st-silent-attribution-probe-20261022.json`: aggregate results,
  SHA-256 `067bfdc38ddc6c5f0e2c4b93b6723f291eff8858490b5dcd6a50b970552a12d9`.
- Parser audit snapshot, an unmodified read-only copy:
  `/srv/scratch/st-silent-attribution-parser-20261022.py`,
  SHA-256 `448fb9b461ea88441de503d2b7ec225aafa5fe5e17110b9101f96144a2116ff3`.
  Original source provenance:
  `/srv/scratch/agent-hub-st-activity-20261022/backend/app/services/st_activity.py`.
  The probe executes the unchanged `shell_segments`/`_commands` AST bodies with
  their standard-library dependencies; it does not import the tokenizer. Source
  hash was unchanged during the run. The original concurrently changed only
  unrelated token-estimation code between earlier measurement and snapshot;
  coverage counts match. Reruns use the fixed snapshot, not the mutable original.

Run from this checkout with
`backend/.venv/bin/python /srv/scratch/st-silent-attribution-probe-20261022.py`.
The diagnostic uses the established DB resolver/project lock, a read-only
transaction and a 30-second statement timeout. Final DB fetch: **0.886 s**.
Synthetic recognition passed **21/21** cases, including arrays, quoted mentions,
compound/pipeline/conditional source and deliberately unsupported syntax; duration
normalization passed **6/6** missing/zero/positive/invalid cases. Parser-only
timing over 11 batches × 100 repetitions × 21 synthetic inputs was
**7.758 µs median per input** (7.537–8.721 µs batch range). This is a read-side
parser benchmark, not execution-time/output-estimation accuracy or CLI overhead.

Added per-command runtime operations are **zero by construction**: no runtime
source was changed. No A/B execution-overhead measurement is claimed.

Managed check, explicitly against the development checkout:

```text
ST_DEV_CHECKOUT=1 st check pytest -- -q tests/cli/test_tools_cost_results.py tests/cli/test_extensions.py tests/cli/test_global_project_option.py tests/cli/test_lazy_commands.py
146 passed, 1 warning in 3.38s
heavy lane; queue 1.625 ms; execution 3859.604 ms
```

The existing cases exercise actual retained-result SQL, duplicate/unknown/empty
results, passive help/lazy loading, project options, isolated child stdin/stdout/
stderr forwarding, nonzero exit, SIGINT/SIGTERM forwarding and child reaping.
They do not establish streaming latency or cross-provider production behavior.
The warning is the existing Starlette/httpx test-client deprecation.
Evidence: `.dev-tools/pytest-18e0e8b169312712-1795298-bfb1f518-details.txt` and
`.dev-tools/pytest-bd9dade05bc94871b3528a6ad13ae960-details.xml`.

Installed `scripts/st` defaults to accepted release
`ab025700711c42cfbba13505905eeae3`; `ST_DEV_CHECKOUT=1` selects this checkout.
No rebuild/deploy was performed. Independent review and local checkpoint are
recorded in the task history.
Delivered runtime model/reasoning effort is not exposed by this worker's runtime
tools; the requested GPT-6.1 Sol xhigh identity is not independently verified here.
