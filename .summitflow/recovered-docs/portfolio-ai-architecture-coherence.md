# Architecture Coherence - MANDATORY

Prevent code and database silos. Enforce DRY principles. Consolidate over create.

**Reference:** See `~/.claude/docs/task-reference.md` for valid types, labels, and commands.

## CRITICAL RULE: SummitFlow vs App Code

**Before building ANY feature, ask:** "If this project was done and no longer connected to SummitFlow, what should remain?"

| Belongs in SummitFlow (dev tooling) | Stays in App (operational) |
|-------------------------------------|----------------------------|
| Features/capabilities tracking | The actual app functionality |
| Evidence capture & verification | User-facing dashboards |
| Sitemap/codebase health | Operational monitoring (`/status`) |
| File analysis & metrics | App-specific settings |
| Task architecture explorer | Background jobs themselves |
| Vision/goals tracking | Health checks ("is it running?") |
| Code quality tools | Business logic |

**Test:** Would a user of the finished app need this? → App code
**Test:** Is this for understanding/developing the codebase? → SummitFlow

**Example mistake:** Building a "Tasks Explorer" (hierarchical Celery task viewer) in portfolio-ai. This is dev tooling for understanding task architecture, not operational monitoring. Belongs in SummitFlow as cross-project feature.

## CRITICAL RULE: Consolidation Over Creation

**RULE**: Before writing ANY new code, function, class, table, or column - verify it doesn't already exist or belong elsewhere.

## Pre-Implementation Checklist (MANDATORY)

Before writing any code, complete ALL of these checks:

1. **Search for existing implementations**
   ```bash
   # Search for similar functions/classes
   grep -r "def similar_name" backend/
   grep -r "class SimilarName" backend/
   ```

2. **Check established patterns**
   - Review `backend/app/utils/` for existing utilities
   - Check `backend/app/services/` for existing service patterns
   - Look at `frontend/lib/` and `frontend/utils/` for frontend helpers

3. **Review existing utilities/helpers**
   - `backend/app/utils/formatters.py` - formatting functions
   - `backend/app/utils/validators.py` - validation logic
   - `frontend/lib/utils.ts` - frontend utilities

4. **Verify naming conventions**
   - Python: `snake_case` for functions/variables, `PascalCase` for classes
   - TypeScript: `camelCase` for functions/variables, `PascalCase` for components
   - Database: `snake_case` for tables/columns, singular table names

5. **For DB changes: review existing schema**
   ```bash
   # Check existing tables and columns
   psql -d portfolio -c "\dt"
   psql -d portfolio -c "\d table_name"
   ```

## What Constitutes a "Silo"

### Code Silos

| Red Flag | Example | Problem |
|----------|---------|---------|
| Duplicate functions | `format_date()` in 3 modules | DRY violation |
| Similar implementations | Two different validation approaches | Inconsistency |
| Copy-paste patterns | Same error handling duplicated | Maintenance burden |
| Inconsistent naming | `get_user` vs `fetch_user` vs `load_user` | Confusion |
| Isolated utilities | Helper in one module that could be shared | Hidden functionality |

### Database Silos

| Red Flag | Example | Problem |
|----------|---------|---------|
| Overlapping tables | `user_preferences` AND `user_settings` | Data duplication |
| Denormalized data | User email stored in 3 tables | Update anomalies |
| Missing relationships | Related tables without FK | Data integrity risk |
| Inconsistent naming | `created_at` vs `date_created` | Query confusion |
| Isolated columns | Config in wrong table | Schema pollution |

## Red Flags - STOP and Investigate

When you see ANY of these, pause and investigate:

- "I'll create a new utility for this" - Does one exist?
- "This table needs a new column" - Does it belong here?
- "Let me add a helper function" - Is there a shared one?
- "I'll create a new service" - Does responsibility overlap?
- "This needs its own table" - Can existing table be extended?
- Similar function/class names in search results
- Multiple modules importing similar external libraries for same purpose

## Immediate Task Creation Protocol

When ANY architecture violation is discovered:

### MANDATORY Actions (in order):

1. **STOP** - Do not continue until issue is tracked

2. **CHECK** if task already exists:
   ```bash
   st list --status pending --json | jq -r '.tasks[] | "\(.id) \(.title)"'
   ```
   Scan the FULL list - don't filter by keywords.

3. **CREATE** task if not exists:
   ```bash
   st create "Arch: <clear description>" -t chore -p 2 \
     -l "complexity:<small|medium|large>,domains:<backend|frontend|database>" \
     -d "**Issue Type:** <DRY Violation|Data Silo|Pattern Mismatch|Schema Issue|Boundary Violation>

   **Severity:** <CRITICAL|HIGH|MEDIUM|LOW>

   **Locations:**
   - file1.py:123
   - file2.py:456

   **Current State:** <what exists now>

   **Desired State:** <what it should be>

   **Impact:** <why this matters>

   **Suggested Approach:** <how to fix>

   **Found during:** <parent-task-id> <task description>"
   ```

4. **LINK** to parent task if applicable:
   ```bash
   st dep add <new-id> <parent-id> --type discovered-from
   ```

5. **CONTINUE** with original work

### Priority Guidelines

| Priority | When to Use |
|----------|-------------|
| P1 | CRITICAL - data integrity, security, blocking other work |
| P2 | HIGH - >3 occurrences, relationship issues, boundary violations |
| P3 | MEDIUM/LOW - 2-3 occurrences, minor inconsistencies |

## Examples: BAD vs GOOD

### Code Example: Date Formatting

**BAD (Silo):**
```python
# In backend/app/api/reports.py
def format_report_date(dt):
    return dt.strftime("%Y-%m-%d")

# In backend/app/api/analytics.py
def format_analytics_date(dt):
    return dt.strftime("%Y-%m-%d")
```

**GOOD (Holistic):**
```python
# In backend/app/utils/formatters.py
def format_date(dt, format="%Y-%m-%d"):
    return dt.strftime(format)

# In backend/app/api/reports.py
from app.utils.formatters import format_date
# Uses shared utility
```

### Database Example: User Preferences

**BAD (Silo):**
```sql
-- Creating separate table when users table exists
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    theme VARCHAR(20),
    notifications BOOLEAN
);
```

**GOOD (Holistic):**
```sql
-- Extend existing table or create proper relationship
ALTER TABLE users
ADD COLUMN theme VARCHAR(20) DEFAULT 'light',
ADD COLUMN notifications_enabled BOOLEAN DEFAULT true;

-- OR if complex, create with proper FK
CREATE TABLE user_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    ...
);
```

### Service Example: Data Fetching

**BAD (Silo):**
```python
# In backend/app/services/reports.py
class ReportDataFetcher:
    async def fetch_stock_data(self, symbol):
        # Custom implementation

# In backend/app/services/analytics.py
class AnalyticsDataFetcher:
    async def get_stock_info(self, symbol):
        # Similar but different implementation
```

**GOOD (Holistic):**
```python
# In backend/app/services/market_data.py
class MarketDataService:
    async def get_stock_data(self, symbol):
        # Single source of truth

# Both modules use the shared service
```

## FORBIDDEN Behaviors

- Creating new utility files without checking existing ones
- Adding columns to random tables without schema review
- Duplicating validation logic across modules
- Creating new services with overlapping responsibilities
- Ignoring search results showing similar implementations
- "I'll refactor this later" without creating a task
- Assuming no prior art exists without searching

## Cross-Reference

- Run `/audit_it` for comprehensive codebase health audit
- See `.claude/rules/issue-tracking.md` for task creation protocol
