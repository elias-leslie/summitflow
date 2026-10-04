# ST caller identity

Core task claim, renewal, acceptance attachment and completion compare the opaque
`current_worker_id()` returned by `cli.lib.task_claims`. Callers should not parse
this value or compare provider/session telemetry to establish ownership.

The existing multi-provider identity resolver validates full session IDs using
the native identifier syntax (1–128 ASCII letters, digits, dots, underscores,
colons or hyphens, starting with a letter or digit). Resolution order is
`ST_SESSION_ID`, `CLAUDE_SESSION_ID`, `CODEX_SESSION_ID`, Agent Hub's
`AGENT_HUB_AGENT_SLUG` plus `AGENT_HUB_SESSION_ID`, then `PI_SESSION_ID`.
Other TUIs can provide a stable unique `ST_SESSION_ID` for successive ST commands.
Codex's inherited `CODEX_THREAD_ID` is not a task owner identity.

Trusted extension dispatch always computes `ST_CALLER_IDENTITY` as JSON:

```json
{"member_id":"codex_cli:codex:native-session-id","provider":"codex_cli","session_id":"native-session-id"}
```

`member_id` is the full stable opaque task owner. `provider` and `session_id` are
telemetry; session_id is omitted for the legacy hostname fallback. Dispatch
overwrites an inherited envelope, and only explicitly allow-listed additional
environment variables reach an owner extension. This envelope is identity
context, not authentication: owner backends must authenticate requests before
using a forwarded `X-ST-Caller-Identity` value.

Non-session callers retain their existing hostname owner identity. Existing
hostname claims are not silently adopted by native sessions. During rollout,
pause a legacy claim before switching the CLI and reclaim it with the session
identity, or finish it before switching. The normal stale-claim lifecycle and
explicit API worker IDs are unchanged. No database migration is required.
