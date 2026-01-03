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

- **INCOMPLETE**: "Added catalyst scoring to backend" → User sees nothing
- **COMPLETE**: "Added catalyst scoring + updated score breakdown to show catalyst pillar"

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
node ~/.claude/skills/browser-automation/scripts/console.js http://192.168.8.233:3000/watchlist 10000
node ~/.claude/skills/browser-automation/scripts/screenshot.js http://192.168.8.233:3000/watchlist /tmp/watchlist.png
```

## UI Regression Testing

**Command**: `/test_it` or `bash ~/portfolio-ai/scripts/ui-regression.sh`

**Output**: `~/portfolio-ai/solution_state/{YYYYMMDD-HHMMSS}/`

```bash
# Full regression test (all pages, tabs, expanded, mobile)
/test_it --full

# Quick check (Dashboard + Watchlist only)
/test_it --quick

# Run script directly
bash ~/portfolio-ai/scripts/ui-regression.sh --full
```

**Coverage**:
- 9 pages (screenshot + JSON report)
- 12 tab variations
- 3+ expanded sections
- 7 mobile viewports

**Storage**: `~/portfolio-ai/solution_state/` (persistent, versioned)

## Evidence Capture for Verification

**RULE: Use API endpoint, NOT direct script call!**

```bash
# CORRECT - captures AND registers in DB
curl -s -X POST "http://localhost:8000/api/artifacts/refresh" \
  -H "Content-Type: application/json" \
  -d '{"feature_id": "FEAT-001", "criterion_id": "ac-001", "url": "http://192.168.8.233:3000/watchlist"}'
```

**Captures**: screenshot, console errors, network failures, page state, performance metrics

**Storage**: `data/artifacts/{feature_id}/{criterion_id}/v{n}/` (versioned)

**UI Access**: `/capabilities` → Features tab → expand → "Evidence" button
