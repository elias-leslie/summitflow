# Checkpoint closeout and repository-noise audit — 2026-09-19

The audit covered all 26 repositories listed by `st vcs doctor --all`. The initial list contained 30 checkpoint records in four projects, including three paused records incorrectly presented as active. There were no task Git refs or Git conflicts. The backlog was primarily task metadata, not accumulated task branches.

## Cause and prevention

`st done` observed GitHub once, then treated ordinary pending CI as a failed command. Nothing owned the next observation. A PR could merge, or CI finish, while the task and checkpoint remained open. Claim expiry could erase publication evidence. The cleanup workflow also omitted its required project identity. Paused checkpoints were considered active and the Git UI hardcoded ACTIVE.

Completion now retains an immutable source revision after the normal local prerequisites pass. The existing 15-minute maintenance schedule dispatches the existing cleanup workflow to continue exact-source publication. It does not create another polling agent, add model calls, rerun completed local gates, commit a changed working tree, or push the saved revision again. It observes actual checks and uses the existing rule-aware PR publisher when a merge is needed. Later checkout work is preserved. Real failures become retained needs-attention states and stop automatic retries. An explicit retry uses the retained request.

Database locking and conditional request identity checks prevent concurrent continuations or a pause/reclaim during observation from completing superseded work. Claim expiry preserves queued completion evidence; explicit lifecycle changes invalidate it. Successful publication evidence is persisted before status finalization so cleanup can recover after a crash. Deferred metadata cleanup checks that the task is still terminal.

UI and CLI share checkpoint-state descriptions and show task names. Open, claimed, waiting for checks, and needs attention are distinct; checkpoint existence does not establish a live agent session. Paused work remains resumable outside the active checkpoint list.

Explorer no longer rewrites `.index.yaml` when only generation/scan timestamps change. Its live database remains the source for scan freshness; material index changes still update the snapshot.

## Cleanup performed

Ten tasks were reconciled through canonical task/status and checkpoint helpers. Their task records retain `verification_result.checkpoint_reconciliation`, including exact source and observed check evidence. No task history or commits were deleted.

| Project | Completed checkpoint | Evidence |
| --- | --- | --- |
| Agent Hub | task-a32cacf564dd4bd2 | PR 43 merged; exact PR source checks passed; source contained in verified main |
| Agent Hub | task-45e91daac9ee4790 | PR 42 merged; merge-source checks passed |
| Agent Hub | task-70b560e13efc41ba | PR 39 merged; retained completion/test/deployment summary; completed stale generic subtask; exact PR source and containing main checked |
| Agent Hub | task-5fb300cf41c84b20 | PR 38 merged; retained completion/test/runtime summary; exact PR source and containing main checked |
| Agent Hub | task-3dd1f868c45547c4 | PR 36 merged; retained completion/test/runtime summary; exact PR source and containing main checked |
| Agent Hub | task-f159061a3aeb462b | PR 33 merged; exact PR source and containing main checked |
| SummitFlow | task-b5550cc1a7f94203 | Source 54709a514e16c8b71a330ea3c7179ae3ba472e6a incorporated; checks passed |
| SummitFlow | task-3e16bb46523b4cb4 | Source 6cbd76e07816cc96ce60a9e77c806da0fa52a99a incorporated; checks passed |
| SummitFlow | task-d118368055a1464a | Source ddaf4c32bdc790bb76bf247552741790818c2777; incorporated; checks passed |
| SummitFlow | task-39b4f6bc967e4e0a | Source d899c324abdd2644c3d0a65a2142e3de9963c0fd incorporated; checks passed |

For five historical Agent Hub PRs, GitHub marked the original source itself incorporated without a new merge revision. The observer still expected a separate main-push workflow at that old SHA. Reconciliation therefore records successful PR checks on the exact source **and separately** successful checks on containing main. It preserves the original pending observation; it does not relabel missing old push runs as successful.

Two timestamp-only index diffs (A-Loom and Rootfall) were restored to their identical committed material snapshot. A temporary backup of the previous generated text was retained locally. Other index diffs contained material information and were preserved.

## Retained work

Fifteen earlier open checkpoints remain: seven SummitFlow, five Neri, and three Security Research. Five SummitFlow sources have failed historical backend checks; their exact failure evidence is now retained canonically for the owning agents. Other retained tasks have unfinished subtasks, explicitly ongoing research, or insufficient completion evidence. Age, a commit, or a broad passing test suite alone was not treated as completion.

Three old paused Agent Hub checkpoints retain their metadata and history. Two independently active tasks completed during the audit through their owning agent; they are not counted as this cleanup.

Other Git findings are distinct from checkpoint noise: A-Term has an unpublished feature commit; Fydor and the Codex/Claude configuration repositories have unpublished or divergent history, and the configuration repositories mix runtime artifacts with actual configuration edits. Those commits and files were preserved. Security Research has live working artifacts. No automatic force-push, branch deletion, blanket stash, or mixed-work cleanup was used.

## Verification

Regression coverage exercises queued pending checks, successful continuation, retained failures and explicit retry, exact-source/CI mismatch, later uncommitted edits, concurrent continuations, pause during observation and at finalization, expired claims, crash recovery, project-bound cleanup dispatch, disabled claim-reset settings, paused checkpoint visibility, and timestamp-only index stability. Canonical backend, frontend, type and lint gates are used. Production verification uses the managed SummitFlow backend/frontend/worker rebuild and the actual Git route.
