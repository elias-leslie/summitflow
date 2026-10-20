# Owner runtime route

`runtime.runtime_user = "owner"` is a symbolic Nightshift target. It never names a
Unix deploy socket, and it never falls back to the caller's user manager.
`svc`, `broker` and `agent` retain their existing deploy sockets.

The public route uses the installed `nightshift` CLI:

- Deploy: `nightshift request owner.deploy project=ID sha=FULL_MAIN_SHA operation=deploy --reason deploy --agent summitflow --wait 3600`
- Rollback: the same action with `operation=rollback` and the exact desired SHA.
- Status: `nightshift request owner.status project=ID --reason diagnose --agent summitflow --wait 3600`
- Stop: `nightshift request owner.service project=ID operation=stop --reason deploy --agent summitflow --wait 3600`

The supported JSON response must report `outcome=applied`, `outcome=no-op`, or the legacy `outcome=noop`, with a
successful CLI exit, before SummitFlow reports success. An approval or pending
request is not a completed deployment. Source and acceptance overrides cannot
bypass this route. Owner units keep their existing `%h` environment paths;
migrations use the owner's existing `~/.config/credstore/PROJECT/env` path.

## Installed tool protocol

Nightshift launches an accepted, root-owned SummitFlow tool, already dropped to its
configured owner, as `st service owner-runtime --phase PHASE`. PHASE is `precheck`,
`apply`, `verify`, or `rollback`. One bounded JSON object arrives on stdin:

```json
{
  "schema": 1,
  "request_id": "frozen request id",
  "action": "owner.deploy",
  "params": {"project": "example", "sha": "40 lowercase hex characters", "operation": "deploy"},
  "expected_uid": 1000,
  "tool_revision": "installed accepted revision"
}
```

`before` is omitted for precheck; the importer returns a
frozen transaction and previous-release reference for later phases. Nightshift's helper unwraps
its outer preparation record before passing the handler's `before` value. No environment flag or
caller-provided UID authorizes the handler. It reads root-owned
`/etc/nightshift/site.json` (`owner.user`) and `/etc/nightshift/owner-actions.json`
(`tool_revision`, `projects.ID.units`). Actual real/effective UID, owner runtime
directory, session-bus address and kernel bus peer UID must match. Missing route,
wrong target or unknown project refuses the operation.

The successful JSON response contract has `schema`, `request_id`, `action`,
`project`, `phase`, `uid`, `manager_uid`, `tool_revision`, and `ok`, plus `before`
on precheck or bounded `result` evidence. Nightshift handles status and service
control itself; SummitFlow does not duplicate that implementation. Installed unit
lists must exclude intentionally disabled optional timers, including the
managed-drain and steward timers.

## Agent build and owner activation

Use ordinary `st service rebuild PROJECT --detach` for a project whose identity
declares `runtime.runtime_user = "owner"`. The command submits the existing typed
Nightshift action. A live work session covers routine actions; otherwise the owner
approves in Nightshift. Missing registry or installed tool is an explicit error.

Preparation, canonical acceptance validation and transfer cleanup run as the agent
through Tether using the exact installed `tool_argv`, never PATH `st`. Preparation
reuses accepted source materialization and existing dependency/build steps. The
owner privately copies the exported archive, verifies its digest and the accepted
tracked Git bytes, links and executable modes, then activates it. Owner operations
are migrations with existing credentials, unit sync, service restart, health checks
and deployment receipts. Source and dependency builds remain agent operations.

The import binds project, exact commit/tree, canonical full acceptance, build
outputs and tool revision. Supported apps include portable Node releases such as
Aico and Python backends with `pyproject.toml` and `uv.lock`. Python preparation
copies the build tool's compatible interpreter unchanged, builds a locked,
non-editable relocatable environment, and bundles both with internal relative
links. A moved-copy smoke check verifies that the bundled interpreter supplies its
own standard library under a clean home. Runtime Python downloads and dependencies
on the agent's interpreter or package caches are unnecessary. Custom release
installers remain unsupported. Aico runs prebuilt entrypoints without startup builds.

Existing current/previous pointers and the deployment lock are retained. The
transaction snapshots unit files and their activity, including timer/socket
companion services. Failed activation restores and checks the previous accepted
release. On the first managed deployment, it restores the existing unit files and
restarts only the previously active units; inactive timers remain inactive even
when their companion service was running. Undo preserves later release changes or
owner unit edits. Neither recovery path rebuilds source as the owner.
Successful private import removes the agent's transfer archive and unused staging.

## Pinned tool installation

The deployment tool is distinct from the app artifact: it includes accepted
SummitFlow source, its complete Python runtime and copied frozen dependencies.
The existing Nightshift pinned deploy-gate installer promotes it and writes the
root-owned owner-actions registry. The installer approval binds the full capsule
digest as well as source and acceptance identity. Root only verifies and copies
the payload; it never runs source builds or the tool itself.

Both identities use the same exact installed interpreter and launcher. The tool
stays pinned across unrelated SummitFlow commits, so routine app deployments do
not require reinstalling it. Installer support and live owner deployment must be
verified before declaring the route operational.
