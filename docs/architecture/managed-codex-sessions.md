# Managed Codex capture retirement

The optional SummitFlow stdio App Server recorder, durable delivery outbox and
private staged-runtime update controls are retired. The Runtime card, operator
API, `st sessions managed-codex` command, recorder/update scripts and drain unit
templates have been removed. New SummitFlow rebuilds do not install the drain.

Normal Codex launch/resume and context integration remain native. Agent Hub owns
rollout/history ingestion through `codex-session-sync.timer` and its existing
collector. Tether session state and continuity remain separate. Native ST thread
delivery and receipt inspection still use the installed `codex` from `PATH` with
the same stdio App Server protocol; they do not import the retired recorder.
These mechanisms provide different evidence and are not interchangeable capture
methods. No protocol schemas, migrations, SDK observation APIs or stored history
are removed by this retirement.

## Installed-state handoff

Source retirement does not remove installed services or private state. Before
deploying the change, the owner must:

1. Verify ordinary native launch/resume and Agent Hub history ingestion, and check
   for active consumers of the optional recorder. Agent Hub retains canonical
   projection support for `collector_id=summitflow/codex-managed`; inspect any
   sessions in `canonical_managed` mode before cutover. Rollout ingestion alone
   does not prove their live canonical projection is covered.
2. Inspect only content-free pending/conflicted/quarantined delivery metadata in
   each configured outbox. Preserve undelivered evidence and its project/source
   provenance; drain supported pending delivery through the existing runtime
   before removing that runtime when necessary. Do not execute old status/update
   actions merely to inspect SQLite metadata: they can change spool state.
3. Keep a recovery copy of the outboxes and any selected private runtime resources.
   Preserve history, stored schemas and retained backups. Source Git history and
   the historical canary receipt in `evidence/managed-codex-canary.json` remain
   available; that receipt describes the former implementation, not current
   installed acceptance.
4. Through the existing managed service mechanism, disable and remove the
   obsolete `summitflow-codex-managed-drain.timer` and its paired service, then
   reload the owning user manager. Remove unused managed-capture environment and
   launch bindings only after confirming no active consumer uses them. Preserve
   shared Agent Hub credentials and native launcher/context configuration.
5. Deploy the accepted SummitFlow backend/frontend source and verify the Runtime
   services view retains its other cards and controls without the capture panel.
   Confirm the old API and CLI command are absent, the drain stays uninstalled,
   and normal native/history workflows remain available.

The retired environment names are `SUMMITFLOW_CODEX_MANAGED_CAPTURE`,
`SUMMITFLOW_CODEX_OUTBOXES_JSON`, `SUMMITFLOW_CODEX_OUTBOX`,
`SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES`, `SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS` and
`SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION`. Their removal from host configuration
is separate from source retirement. No history or outbox deletion is required.

The trusted `native-sessions` ST extension still selects Agent Hub's accepted
runtime and matching Python environment. Missing or incomplete accepted releases
continue to fail explicitly. This extension is unrelated to the retired
SummitFlow recorder command.
