# Code Cleanliness - MANDATORY

Keep code lean. Remove bloat. No hoarding.

## Dead Code

**Delete immediately:**
- Unused functions, classes, variables
- Commented-out code blocks
- Deprecated code "kept for reference"
- Backwards-compatibility shims for removed features
- Unused imports/exports

**No excuses like:**
- "Might need it later" → Git has history
- "Keeping for backwards compatibility" → If nothing uses it, delete it
- "Reference implementation" → Link to git commit instead

## Comments

**Comments must be:**
- Concise (1-2 lines max for inline)
- Useful for search (function purpose at top)
- Explaining WHY, not WHAT

**Delete these:**
```python
# BAD: Obvious comments
i += 1  # increment i
user = get_user(id)  # get the user

# BAD: Changelog in code
# Added 2024-01-15 by John
# Modified 2024-02-20 to fix bug

# BAD: Commented-out code
# def old_function():
#     pass
```

**Keep these:**
```python
# GOOD: File header (what this module does)
"""User authentication service. Handles login, logout, token refresh."""

# GOOD: Why, not what
# Skip validation for internal API calls (already validated at gateway)
if request.is_internal:
    return True

# GOOD: Non-obvious behavior
# Redis returns bytes, decode to string for JSON serialization
```

## Duplicate Code

**Consolidate when:**
- Same logic appears 2+ times
- Same pattern with minor variations

**Extract to:**
- `utils/` for pure helpers
- `services/` for business logic
- Shared module for cross-domain

## Verification Before Deletion

**Safe deletion checklist:**
1. Search for usages: `grep -r "function_name" .`
2. Check imports: `grep -r "from .* import.*function_name"`
3. Run tests: `pytest`
4. If tests pass and no usages → DELETE

## Enforcement

During refactoring, dead code removal is a **required phase**, not optional cleanup.
