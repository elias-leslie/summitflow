# UI-Backend Lockstep Rule

Backend changes MUST have corresponding UI visibility.

## The Lockstep Rule

**RULE**: Backend changes MUST have corresponding UI visibility. No exceptions.

### Before Marking ANY Task Complete

1. **Identify UI impact** - What should the user SEE differently?
2. **Implement UI change** - Update frontend to expose new backend capability
3. **Screenshot verification** - Take screenshot proving the change is visible
4. **If no UI impact** - The feature may be dead code / tech debt

### Examples

- **INCOMPLETE**: "Added feature scanning to backend" → User sees nothing
- **COMPLETE**: "Added feature scanning + updated Features tab to show scan results"

### Value Test

If I can't show the user a visual difference, did I add value?

### Dead Code Prevention

- Code that isn't wired to UI may never be used
- Backend changes without UI = potential tech debt spiral
- Always complete the full vertical slice (DB → Backend → API → UI)

## UI Testing Protocol

**RULE**: Never say frontend work is "complete" without testing changed pages.

```bash
# Quick verification - USE NETWORK IP, not localhost (SSR routing issues)
# Adapt URL based on your network configuration
curl -s http://localhost:3001/api/health
```

## Evidence Capture for Verification

**RULE: Use API endpoint for evidence capture!**

```bash
# Captures screenshot AND registers in DB
curl -s -X POST "http://localhost:8001/api/projects/{project_id}/evidence/capture" \
  -H "Content-Type: application/json" \
  -d '{"capability_id": "login", "criterion_id": "ac-001", "url": "https://dev.summitflow.dev/projects"}'
```

**Captures**: screenshot, console errors, network failures, page state, performance metrics

**Storage**: `data/projects/{project_id}/evidence/{capability_id}/{criterion_id}/v{n}/` (versioned)

**UI Access**: `/projects/{id}` → Evidence tab
