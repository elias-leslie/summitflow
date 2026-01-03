# Explorer Architecture - MANDATORY

**Reference:** `docs/explorer-architecture.md` is the authoritative source.

## CRITICAL: Before ANY Explorer Code

1. **READ** `docs/explorer-architecture.md` completely
2. **SEARCH** for existing implementations before creating new ones
3. **IDENTIFY** which layer your code belongs in
4. **FOLLOW** existing patterns (cite file:line reference)

## Layer Boundaries (ENFORCED)

| Layer | Location | Allowed Operations |
|-------|----------|-------------------|
| API | `backend/app/api/explorer.py` | Request validation, response formatting, delegate to services |
| Service | `backend/app/services/explorer/` | Business logic, scanning, analysis |
| Storage | `backend/app/storage/explorer.py` | ALL database operations |
| Frontend | `frontend/components/explorer/` | UI rendering, state management |

**FORBIDDEN:**
- Database queries outside `storage/explorer.py`
- Business logic in API layer
- Data fetching in renderer components
- Direct API calls outside hooks

## Directory Rules

```
Type-specific code → types/ subdirectory ONLY
Shared code → parent directory
```

**Example:**
- `FileScanner` → `services/explorer/types/files.py` ✓
- `BaseScanner` → `services/explorer/base.py` ✓
- `FileScanner` → `services/explorer/scanner.py` ✗ (wrong location)

## Pre-Implementation Checklist (MANDATORY)

Before writing ANY Explorer code, verify:

```bash
# 1. Search for existing utilities
grep -r "function_name" backend/app/services/explorer/
grep -r "ComponentName" frontend/components/explorer/

# 2. Check shared utilities in architecture doc
cat docs/explorer-architecture.md | grep -A20 "Shared Utilities"

# 3. Verify file doesn't exist
ls -la backend/app/services/explorer/types/
ls -la frontend/components/explorer/types/
```

## Red Flags - STOP and Refactor

| Red Flag | Action |
|----------|--------|
| File > 200 lines | Split into smaller modules |
| Same logic in 2+ files | Extract to shared utility |
| Direct DB query in service | Move to storage layer |
| Fetch in renderer component | Move to hook |
| Component > 300 lines | Split into sub-components |
| New utility not in arch doc | Add to doc FIRST |

## Creating New Utilities

**BEFORE creating any new shared utility:**

1. Add entry to `docs/explorer-architecture.md` → "Shared Utilities Registry"
2. Get approval (or self-approve with justification in commit)
3. Then implement

**Utility Naming:**
- Backend: `snake_case` functions
- Frontend: `camelCase` functions, `PascalCase` components
- Hooks: `use` prefix

## Type-Specific Code Requirements

When adding code to `types/` subdirectory:

1. **ONLY** include type-specific logic
2. **IMPORT** shared utilities from parent
3. **FOLLOW** the config pattern:

```typescript
// Frontend example
export const filesConfig: ExplorerTypeConfig = {
  type: 'file',
  columns: fileColumns,        // Define here
  renderRow: FileRow,          // Define here
  renderDetail: FileDetail,    // Define here
};
```

```python
# Backend example
class FileScanner(BaseScanner):
    entry_type = "file"

    def scan(self) -> list[ExplorerEntry]:
        # ONLY file-specific logic here
        # Use self.save() from base class
        pass
```

## Code Review Checklist

Before marking Explorer task complete:

- [ ] No duplicate code introduced
- [ ] Follows layer boundaries
- [ ] Type-specific code in `types/` only
- [ ] Shared utilities registered in arch doc
- [ ] File sizes under limits (200 backend, 300 frontend)
- [ ] Tests added for new functionality

## Enforcement

This rule is checked during:
- Pre-implementation (read arch doc)
- Implementation (follow patterns)
- Code review (checklist above)
- Checkpoint phases (DRY audit tasks in epic)

**Violations block task completion.**
