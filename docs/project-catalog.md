# Project catalog and representation

SummitFlow's project registry is the catalog for project discovery. A registered
project has a stable ID, category, and canonical checkout path. The checkout's
`project.identity.json`, when present, describes the project and its managed
services. Git is source history, not a lifecycle switch. The backup source and
schedule are separate durable records. A project may have no running service,
and some projects have no service declaration at all.

| Surface | Expected relationship to a project |
| --- | --- |
| Git | A development project's registered checkout resolves to its Git working tree. A managed release's copied source is not the catalog root. |
| SummitFlow default list and session pickers | Active projects outside the `testing` category appear. Testing fixtures stay registered and are omitted from routine discovery. |
| Runtime | Only services declared by that project's identity are checked. A project with no declared services is valid; stopped optional or on-demand services do not imply retirement. |
| Backups | A project backup source points at the canonical checkout. Its enablement and history are independent of runtime and lifecycle. A disabled source is reported explicitly; retirement does not erase backups. |

An owner-authenticated retirement decision in the SummitFlow database controls
whether a project is retired. The decision includes a reason, actor, timestamp,
and history. A checkout manifest's `project.lifecycle` is advisory so a source
edit cannot silently remove a project from SummitFlow or session pickers. The
catalog exposes effective and declared lifecycle separately when they differ.
Changing the registry root must identify the same project and must not point to
a managed release copy. Re-activating a project reverses the current decision
without deleting its history, backup source, or Git repository.

`st projects audit` inspects every registered project, including hidden testing
fixtures and retired entries. Its JSON reports checkout/Git identity, effective
and declared lifecycle, default-list visibility, backup source state, and
declared runtime services. It marks unavailable evidence as `unknown`; picker
rendering remains a separate UI check. `st check --quick --changed-only` also
checks the current checkout's identity and compares it with the live registry
when the API is reachable. A registry outage leaves that comparison partial,
while local manifest and Git checks still run.

The catalog review sequence is: compare the inclusive registry with the default
list, verify each checkout and its Git identity, compare backup source paths and
enablement, then inspect declared runtime services where they exist. Resolve
unexplained mismatches with the project owner before changing lifecycle or
classifying an entry as a testing fixture. A change to one surface does not
implicitly authorize changing another surface's policy.
