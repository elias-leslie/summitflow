# Issue Tracking - MANDATORY

**Reference:** See `~/.claude/docs/task-reference.md` for valid types, labels, and commands.

## CRITICAL RULE: Every Discovered Bug Gets a Task

**When you encounter ANY pre-existing bug, error, warning, or issue during your work:**

### MANDATORY Actions (in order):

1. **STOP** - Do not continue until issue is tracked
2. **REVIEW ALL OPEN TASKS** (do NOT filter by keywords - you might miss matches):
   ```bash
   st list --status pending --json | jq -r '.tasks[] | "\(.id) \(.title)"'
   ```
   Scan the FULL list to check if issue already exists.
3. **CREATE** if none exists, with `discovered-from` dependency link:
   ```bash
   # Create the bug with complexity and domain labels
   st create "Fix: <clear problem description>" -t bug -p 2 \
     -l "complexity:<small|medium|large>,domains:<backend|frontend|database>" \
     -d "Error: <exact error message>

   Location: <file:line>

   Fix needed:
   - <specific action items>

   Found during: <parent-task-id> <parent task title>"

   # MANDATORY: Link to parent task with discovered-from dependency
   st dep add <new-id> <parent-task-id> --type discovered-from
   ```

   **Complexity Labels (REQUIRED):**
   | Label | Criteria |
   |-------|----------|
   | `complexity:small` | <3 files, <50 lines, single domain |
   | `complexity:medium` | 3-10 files, <200 lines |
   | `complexity:large` | >10 files OR >200 lines OR multi-domain |

   **Domain Labels (REQUIRED):**
   | Label | When |
   |-------|------|
   | `domains:backend` | Python/FastAPI changes |
   | `domains:frontend` | React/Next.js changes |
   | `domains:database` | Schema/migration changes |

   *Multiple domains = add multiple labels (e.g., `complexity:medium,domains:backend,domains:frontend`)*
4. **UPDATE** if task exists: `st update <id> -d "Additional context..."`
5. **CONTINUE** with original task

### What Qualifies as a Discoverable Issue:

- Database errors (missing tables, columns, constraints)
- Import errors (missing modules, wrong paths)
- Type errors caught during testing
- Runtime exceptions in logs
- Failed tests unrelated to current work
- Deprecated API usage warnings
- Security vulnerabilities spotted
- Performance issues observed
- Dead code or orphaned files found
- Schema mismatches

### FORBIDDEN Behaviors:

- Mentioning bugs only in task summaries
- Saying "pre-existing issue" without creating task
- Noting "not related to this task" and moving on
- Leaving issues for "future discovery"
- Assuming someone else will track it

### Priority Guidelines for Discovered Issues:

| Severity | Priority | Examples |
|----------|----------|----------|
| Blocks functionality | P1 | Missing table, import error |
| Causes errors but workaround exists | P2 | Wrong column name, type mismatch |
| Cosmetic or minor | P3 | Deprecated warning, style issue |
| Future consideration | P4 | Optimization opportunity |

## Enforcement

**Every discovered issue = immediate task creation.**

**No exceptions. No delays. No excuses.**

This rule takes priority over task completion speed.

## Labels Reference

### Complexity (REQUIRED - pick ONE)

| Label | Criteria |
|-------|----------|
| `complexity:small` | <3 files, <50 lines, single domain |
| `complexity:medium` | 3-10 files, <200 lines |
| `complexity:large` | >10 files OR >200 lines OR multi-domain |

### Domains (REQUIRED - pick ALL that apply)

| Label | When |
|-------|------|
| `domains:backend` | Python/FastAPI/Celery changes |
| `domains:frontend` | React/Next.js/TypeScript changes |
| `domains:database` | Schema/migration/SQL changes |
