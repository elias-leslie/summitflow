# Git-only workflow retirement — 2026-10-04

ST task: `task-79a1bc0861ac44f0`. Fydor preservation task:
`task-9d7dbae0cda145f0`.

Git already serves the live source-control needs. The active Jujutsu command,
its four CLI libraries and command tests, command registration, tool catalogue
entry, commit dispatch, pulse/status projection, sync/rebase path, alternative
publication transport callback, and publication route fallback were removed.
`st commit` creates checked local Git checkpoints with task linkage and selected
paths. `st vcs publish --source ID --sha FULL_OID --now` retains explicit,
accepted-source publication. Git diff/log serve source inspection. Pulling a
detached HEAD fails before transport rather than moving local work implicitly.

Fydor was the only colocated checkout in the inspected 40 local project
directories. Its Git checkout was clean at detached `272e77bdbebc`, two local
commits beyond `main`/`origin/main` (`e24f9d54b97e`). Its empty working revision
`31c8fbbf9913` had the same tree as Git HEAD. Every visible revision, including
the additional empty `c5e67d06db16`, existed in the backing Git object store and
was protected by retained `refs/jj/keep` refs. Its operation store includes
split/undo evidence that must survive retirement. No branch switch, advance,
ref deletion, history rewrite, or remote publication is part of this change.

Historical evidence remains historical: `docs/local-first-implementation.md`,
`docs/st-help-evidence/`, Fydor's sourced handoff documents, backup manifests,
old publication reason codes and preserved Git refs. Recovery capture still
protects legacy metadata in old/restored repositories, including its exact
empty transient lock exception. File-safety checks protect those stores, and
command/publication guards refuse retired-tool mutations or direct publication.
These protections do not initialize or invoke the retired runtime. No package
manifest contained a Jujutsu dependency.

The focused regression gates passed 367 tests via `st check pytest` across Git
checkpoint, closeout, VCS/pulse, command/publication guard, publication-hook,
source-selection and Git-core tests. Receipt:
`.dev-tools/pytest-18dba91451a9f7a2-1936274-727b1c3e-details.txt` and
`.dev-tools/pytest-18dbac2d9f6d3b65-2077193-dd35a6c2-details.txt`.
Canonical full acceptance and managed rebuild remain required against the final
committed source. Their receipts belong on the ST task; older rollout receipts
do not establish acceptance of these changes.
