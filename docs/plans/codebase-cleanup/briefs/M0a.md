# M0a brief (builder: Sonnet 5.5 high, native subagent)

Goal: milestone M0a of the codebase cleanup plan, in /srv/workspaces/projects/aico. Pure restructure, NO behavior change.

Read first (they are the spec): cutlist.md section 1 (layout 1.1, enforcement 1.2 for what M0b adds later, separate deploys 1.4, existing aico code mapped 1.5) and the M0a row in section 4. Skim plan.md "Settled consolidation choices" for context.

Scope (all of M0a, nothing from M0b or later):
1. Move plan.md, cutlist.md, harness-review/ and briefs/ from summitflow/docs/plans/codebase-cleanup/ into aico/docs/plans/codebase-cleanup/ (copy into aico and commit; in summitflow replace the folder with a one-line README pointing to the new place and commit). Fix relative links.
2. Move existing aico code into `packages/<name>/` and `native/<name>/` as section 1.5 maps it. Only packages that existing code moves into; no empty placeholders. Each package: own package.json (exact-pinned deps), tsconfig.json with `composite` + project references so `tsc -b` from the root builds all. Vitest: one project per package.
3. Delete the dead code the M0a row names (C1, a_term, __pycache__) after rg confirms nothing references it.
4. Fix every path the move breaks: imports, scripts/, systemd units and install scripts, tether/web build and start commands, biome.json, project.identity.json, ui-spec.json, st check config, docs links. rg for old paths until none remain.

Proof: run `st check --acceptance` once BEFORE starting (baseline counts) and once at the end; same tests pass, none deleted except with dead code. Iterate with `st check --quick --changed-only` (never raw tsc/vitest/biome). Commit in a few checkpoints with `st commit -m "..." --paths <files>`, message ending "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>". Never git stash, reset or rebase.

Deploy: tether, aico-web and timers (aico-notes-export) run from this repo, and live agent sessions run under Tether. Check `st sessions may-disrupt` and how `st service rebuild aico` restarts things; deploy with `st service rebuild aico --detach` only if tmux sessions survive. Then verify: tether status OK, Aico web loads (`st browser check` on the local URL), aico user units active. If a restart would end live sessions, commit everything, don't deploy, and say so.

Gotchas: hold the repo first (`st lease --hold "M0a restructure"`, release when done). Never open /srv/workspaces/projects/neri or hunting/case data; never read credentials, .env or auth files. Keep owner-visible behavior identical; if a move forces a real choice, take the smallest option and list it. Usage is tight: no optional refactors or reviews of unrelated code.

Report (<= 30 lines): commits (full SHAs), final package/native list with LOC, test counts before/after, what was deployed and the live checks, anything undone and why.
