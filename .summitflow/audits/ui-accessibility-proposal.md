# UI Accessibility Proposal

**Date:** 2025-12-19
**Based on:** `ui-accessibility-audit.md`

---

## Proposed Changes

### 1. Create `/projects/new` Page (CRITICAL)

**Problem:** Links to "Add Project" exist but page doesn't exist.

**Solution:** Create a simple form page.

**Files to Create:**
- `frontend/app/projects/new/page.tsx`

**Implementation Approach:**
```
- Single form with fields: name, id (auto-generated), base_url, health_endpoint
- Uses existing createProject() from lib/api.ts
- On success: redirect to /projects/[id]
- Follow existing page patterns (header + card form)
```

**Scope:** ~80 lines, single file

**Alternative Considered:** Modal dialog on Projects page instead of separate page. Rejected because the existing links point to `/projects/new` and a full page provides better UX for entering multiple fields.

---

### 2. Add Kanban Navigation Link (CRITICAL)

**Problem:** Kanban page exists but is inaccessible.

**Solution:** Add "Kanban" button/link to project detail page.

**Files to Modify:**
- `frontend/app/projects/[id]/page.tsx`

**Implementation Approach:**
```
Option A: Add as 6th tab (simplest)
Option B: Add as action button in header area
Option C: Add as link in Features tab header

Recommendation: Option A - Add as tab for consistency
```

**Scope:** ~15 lines modification

---

### 3. Wire Terminal Button (HIGH)

**Problem:** Terminal button in TopBar does nothing.

**Solution:** Open Terminal in a modal/drawer.

**Files to Modify:**
- `frontend/components/layout/TopBar.tsx`

**Files to Create (if needed):**
- `frontend/components/terminal/TerminalModal.tsx` (wrapper)

**Implementation Approach:**
```
- Add state: isTerminalOpen
- Wrap Terminal or TerminalTabs in a Sheet (slide-out drawer)
- Use existing shadcn/ui Sheet component
```

**Scope:** ~40 lines

**Question for Review:** Should Terminal be:
- A. Full-screen modal?
- B. Side drawer (Sheet)?
- C. Bottom panel (like VS Code)?

---

### 4. Replace BeadsTab with IssueTasksTab (HIGH)

**Problem:** Project detail shows "Beads" tab but system migrated to Tasks.

**Solution:** Replace BeadsTab import with IssueTasksTab.

**Files to Modify:**
- `frontend/app/projects/[id]/page.tsx`

**Implementation:**
```tsx
// Change:
import { BeadsTab } from "@/components/beads/BeadsTab";
// To:
import { IssueTasksTab } from "@/components/tasks/IssueTasksTab";

// Update tab button and content to use IssueTasksTab
```

**Scope:** ~10 lines modification

**Question for Review:** Should we rename the tab to "Tasks" or keep "Beads"?

---

### 5. Add Feature Creation UI (HIGH)

**Problem:** Features can only be created via curl.

**Solution:** Add "Create Feature" button and dialog to FeaturesTab.

**Files to Modify:**
- `frontend/components/features/FeaturesTab.tsx`

**Files to Create:**
- `frontend/components/features/CreateFeatureDialog.tsx`

**Implementation Approach:**
```
- Add "Create Feature" button to FeaturesTab header
- Dialog with form: name, category, description, layers
- POST to /api/projects/{id}/features
- Invalidate TanStack Query cache on success
```

**Scope:** ~150 lines (new dialog + FeaturesTab modification)

**Note:** Need to first verify the backend endpoint exists and understand the schema.

---

### 6. Fix Refresh Button (MEDIUM)

**Problem:** Refresh button in TopBar does nothing.

**Solution:** Invalidate TanStack Query cache to refresh all data.

**Files to Modify:**
- `frontend/components/layout/TopBar.tsx`

**Implementation:**
```tsx
import { useQueryClient } from "@tanstack/react-query";

const queryClient = useQueryClient();

<button onClick={() => queryClient.invalidateQueries()}>
  <RefreshCw />
</button>
```

**Scope:** ~5 lines

---

### 7. Add Task Creation UI (MEDIUM)

**Problem:** Tasks API exists but no UI form.

**Solution:** Use existing StartTaskDialog or create CreateTaskDialog.

**Files to Assess:**
- `frontend/components/tasks/StartTaskDialog.tsx` - May already handle this

**Files to Modify (likely):**
- `frontend/components/tasks/IssueTasksTab.tsx` - Add "Create Task" button

**Scope:** TBD after assessing existing component

---

### 8. Wire Roundtable (LOW)

**Problem:** RoundtableChat component exists but isn't accessible.

**Solution:** Add entry point (button or menu item).

**Options:**
- A. TopBar button (like Terminal)
- B. Project detail tab
- C. Floating action button
- D. Part of Terminal tabs

**Recommendation:** Defer until Terminal is wired, then add as tab within Terminal panel.

---

## Implementation Order

Based on dependencies and impact:

| Order | Change | Effort | Blocks |
|-------|--------|--------|--------|
| 1 | Create `/projects/new` | Small | User onboarding |
| 2 | Add Kanban link | Tiny | Kanban feature |
| 3 | Replace BeadsTab with IssueTasksTab | Tiny | None |
| 4 | Fix Refresh button | Tiny | None |
| 5 | Wire Terminal button | Small | Terminal feature |
| 6 | Add Feature creation UI | Medium | Feature creation |
| 7 | Add Task creation UI | Medium | Task creation |
| 8 | Wire Roundtable | Small | Roundtable feature |

**Recommended First Sprint:** Items 1-4 (all tiny/small, high impact)

---

## Questions Requiring Clarification

1. **Terminal presentation:** Modal, drawer, or bottom panel?
2. **Tab naming:** Rename "Beads" to "Tasks" or keep existing name?
3. **Roundtable scope:** Wire now or defer?
4. **Feature creation:** Is the backend endpoint ready? What's the schema?

---

## Files Summary

### To Create

| File | Purpose | Lines (est) |
|------|---------|-------------|
| `frontend/app/projects/new/page.tsx` | Project creation form | 80 |
| `frontend/components/terminal/TerminalModal.tsx` | Terminal wrapper | 40 |
| `frontend/components/features/CreateFeatureDialog.tsx` | Feature creation | 100 |

### To Modify

| File | Change | Lines (est) |
|------|--------|-------------|
| `frontend/app/projects/[id]/page.tsx` | Add Kanban tab, replace BeadsTab | 25 |
| `frontend/components/layout/TopBar.tsx` | Wire Terminal + Refresh buttons | 20 |
| `frontend/components/features/FeaturesTab.tsx` | Add create button | 10 |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing navigation | Test each change in isolation |
| API incompatibility | Verify endpoints before UI work |
| Style inconsistency | Use existing component patterns |
| Terminal websocket issues | Backend may need verification |

---

## Ready for Approval

**Awaiting your review before implementation.**

Key decisions needed:
1. Approve implementation order
2. Answer clarification questions
3. Confirm scope (all 8 items or subset?)
