Phase 1: Cross-Project Audit (Parallel Teams)

Deploy a team of explorer agents — one per project (Terminal, Monkey Fight, Portfolio-AI, Agent-Hub, SummitFlow) — to perform two audits in parallel:

AUDIT A: DRY Violations
Scan for duplicated packages, methods, and code patterns both within and across projects.

AUDIT B: Integration Health & Code Quality
Focus on API contracts, SDK alignment, shared types, schema drift between projects. Compare patterns, error handling, logging, and testing consistency across codebases. Identify all dead and unnecessary code.

Both audits must target 100% completeness, not 80%.

The audit runs in iterative passes until the lead is satisfied that discovery is exhaustive:

Pass 1: Each project agent performs a broad scan for both DRY violations and integration/quality issues within its project. The lead collects and cross-references results across all projects.

Pass 2+: The lead assigns targeted deep dives back to project agents based on cross-project patterns flagged in prior passes, hunting for anything missed.

Final pass: The lead performs a verification sweep across all agent findings to confirm completeness. The audit is not done until the lead is confident nothing has been overlooked.

For each duplicated package, method, or code pattern:
- Identify the best implementation — not overengineered, fulfills all requirements, efficient and optimal. The perfect balance.
- Identify all inferior alternatives — incomplete, overengineered, redundant, or siloed implementations of the same thing.
- Flag deficiencies in the "best" implementation, if any still exist, so they can be addressed during the fix-it phase.

For integration health and code quality:
- Flag all contract mismatches, schema drift, and dead code with file:line references
- Note where one project's pattern is better and should be adopted by others
- Prioritize by severity (P0 breaking, P1 high, P2 medium, P3 low)

Deliver a unified report covering:
- The winning implementation for each duplicated concern
- All inferior/redundant implementations that should be migrated away from
- All integration mismatches, dead code, and quality inconsistencies
- A prioritized ranking by importance and impact
- Any gaps in the best implementations that need improvement before migration

Phase 2: Fix-It (after my approval)

Deploy agent teams to parallelize the work, grouped by concern:
- Extend/improve/finalize the best implementations where deficiencies were flagged
- Migrate all callers across all projects to use the best implementations
- Fix all integration contract mismatches and remove all dead code
- Fully remove all old code — no deprecation wrappers, no backward-compatibility shims, no stubs, no leftover comments or traces, no tech debt

Nothing ships with remnants of the old code.

After all fixes are applied, run /review_it on each project.
