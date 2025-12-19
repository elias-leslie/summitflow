# UI Accessibility Audit

**Date:** 2025-12-19
**Auditor:** Claude (Opus 4.5)
**Scope:** Frontend routes, components, navigation, user flows

---

## Executive Summary

**Overall Assessment:** The SummitFlow frontend is **more complete than expected**. The original concern about missing navigation was largely unfounded - there IS a proper navigation system with Sidebar, TopBar, and project-scoped tabs. However, several **critical gaps** exist that prevent full functionality.

### Critical Issues (3)

1. **Missing `/projects/new` page** - Links exist in UI but page doesn't exist. Users cannot create projects through the UI.
2. **Orphaned Kanban page** - Page exists at `/projects/[id]/kanban` but no navigation links to it.
3. **Dead TopBar buttons** - Terminal and Refresh buttons do nothing.

### Moderate Issues (4)

4. **Orphaned components** - Terminal, Roundtable, TaskLogViewer, StartTaskDialog, IssueTasksTab are built but not wired up.
5. **Beads tab still exists** - Project detail page shows "Beads" tab but system migrated to Tasks.
6. **Features only creatable via curl** - No UI to create features (though the concern was correct here).
7. **No Task creation UI** - Tasks API exists but no frontend form.

---

## 1. Route Mapping

### Existing Pages (8 total)

| Route | Status | Purpose | Notes |
|-------|--------|---------|-------|
| `/` | ACCESSIBLE | Dashboard | Shows projects, stats, activity feed |
| `/projects` | ACCESSIBLE | Projects list | Lists all projects with health status |
| `/projects/[id]` | ACCESSIBLE | Project detail | Tabs: Explorer, Features, Vision, Evidence, Beads |
| `/projects/[id]/kanban` | **ORPHANED** | Kanban board | **No navigation links to this page** |
| `/features` | ACCESSIBLE | Features fallback | Placeholder: "Select a project" |
| `/evidence` | ACCESSIBLE | Evidence fallback | Placeholder: "Select a project" |
| `/settings` | ACCESSIBLE | Settings | Static, minimal settings |
| `/explorer-demo` | UNLISTED | Demo page | Not linked from anywhere |

### Missing Pages

| Route | Links Exist? | Impact |
|-------|--------------|--------|
| `/projects/new` | **YES** (Dashboard, Projects) | **CRITICAL** - Users see "Add Project" but clicking leads to 404 |

---

## 2. Navigation Analysis

### Global Navigation (Root Layout)

```
┌─────────────────────────────────────────────────────────────┐
│ TopBar: [Search] [Camera] [Terminal*] [Refresh*] [Notif] [Time] │
├──────────┬──────────────────────────────────────────────────┤
│ Sidebar  │                                                  │
│          │                                                  │
│ [Logo]   │            Main Content Area                    │
│          │                                                  │
│ [Select  │                                                  │
│  Project]│                                                  │
│          │                                                  │
│ Dashboard│                                                  │
│ Projects │                                                  │
│ Explorer*│                                                  │
│ Features*│                                                  │
│ Evidence*│                                                  │
│          │                                                  │
│ Settings │                                                  │
│          │                                                  │
│ [Online] │                                                  │
└──────────┴──────────────────────────────────────────────────┘

* = Project-scoped (links to /projects/[id]?tab=xxx when project selected)
```

### Navigation Features

- **Project Selector Dropdown** - Persists selection in localStorage
- **Context-Aware Links** - Explorer/Features/Evidence link to project-scoped tabs when project is selected
- **Tab Navigation** - Project detail page has internal tabs (Explorer, Features, Vision, Evidence, Beads)

### Dead/Non-Functional Elements

| Element | Location | Issue |
|---------|----------|-------|
| Terminal button | TopBar | No onClick handler, does nothing |
| Refresh button | TopBar | No onClick handler, does nothing |
| "Add Project" button | Dashboard, Projects page | Links to `/projects/new` which doesn't exist |

---

## 3. Component Analysis

### UI Component Library

- **shadcn/ui** components: button, badge, tabs, dialog, sheet, select, input, textarea, checkbox, table, tooltip, scroll-area, skeleton, label, progress
- **dnd-kit** for drag-and-drop (used in Kanban)
- **Lucide** icons
- **TanStack Query** for data fetching
- **clsx** for conditional classes

### Component Inventory

#### Used Components (Wired to Pages)

| Component | Used In | Purpose |
|-----------|---------|---------|
| `Sidebar` | `layout.tsx` | Global navigation |
| `TopBar` | `layout.tsx` | Search, actions, notifications |
| `FeaturesTab` | `projects/[id]/page.tsx` | Features display |
| `ExplorerTab` | `projects/[id]/page.tsx` | Explorer display |
| `EvidenceTab` | `projects/[id]/page.tsx` | Evidence display |
| `VisionGoalsTab` | `projects/[id]/page.tsx` | Vision goals |
| `BeadsTab` | `projects/[id]/page.tsx` | Beads (deprecated?) |
| `KanbanBoard` | `projects/[id]/kanban/page.tsx` | Kanban board (orphaned page) |
| `FeatureCard` | `KanbanBoard` | Feature card in Kanban |
| `FeatureDetailDrawer` | `projects/[id]/kanban/page.tsx` | Feature detail slide-out |
| `EvidenceCaptureModal` | `TopBar` | Screenshot capture |
| `NotificationBell` | `TopBar` | Notifications dropdown |
| Explorer components | `ExplorerTab` | Files, tasks, endpoints, tables, pages |

#### Orphaned Components (Not Used in Any Page)

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `Terminal.tsx` | `components/terminal/` | Interactive terminal | Backend API exists |
| `TerminalTabs.tsx` | `components/terminal/` | Multi-tab terminal | Depends on Terminal |
| `RoundtableChat.tsx` | `components/roundtable/` | AI discussion interface | Backend API exists |
| `TaskLogViewer.tsx` | `components/tasks/` | Task execution logs | |
| `StartTaskDialog.tsx` | `components/tasks/` | Start task dialog | |
| `IssueTasksTab.tsx` | `components/tasks/` | Tasks tab | Should replace BeadsTab? |

---

## 4. User Flow Analysis

### Can Access? Matrix

| Action | Possible? | Method |
|--------|-----------|--------|
| View dashboard | YES | Navigate to `/` |
| View projects list | YES | Sidebar → Projects |
| View project detail | YES | Click project card |
| View Explorer | YES | Project detail → Explorer tab |
| View Features | YES | Project detail → Features tab |
| View Evidence | YES | Project detail → Evidence tab |
| View Vision | YES | Project detail → Vision tab |
| View Kanban | **NO** | Page exists but no navigation |
| Create project | **NO** | Link exists but page missing |
| Create feature | **NO** | No UI exists |
| Create task | **NO** | No UI exists (though API exists) |
| Capture evidence | YES | TopBar → Camera button |
| Use terminal | **NO** | Button exists but does nothing |
| Use Roundtable | **NO** | No UI entry point |

### User Journey: New User

1. User arrives at `/` (Dashboard)
2. Sees "No projects registered" empty state
3. Clicks "Add Project" button
4. **BLOCKED** - Gets 404 error

### User Journey: Existing User with Projects

1. User arrives at `/` (Dashboard)
2. Sees project cards, clicks one
3. Lands on project detail page
4. Can switch between tabs: Explorer, Features, Vision, Evidence, Beads
5. **Cannot access Kanban** - no link exists
6. **Cannot use Terminal** - button does nothing

---

## 5. Existing Patterns

### File Organization

```
frontend/
├── app/                    # Next.js App Router pages
│   ├── page.tsx           # Dashboard
│   ├── layout.tsx         # Root layout (Sidebar + TopBar)
│   ├── projects/
│   │   ├── page.tsx       # Projects list
│   │   └── [id]/
│   │       ├── page.tsx   # Project detail with tabs
│   │       └── kanban/
│   │           └── page.tsx  # Orphaned Kanban
│   ├── features/page.tsx  # Fallback
│   ├── evidence/page.tsx  # Fallback
│   └── settings/page.tsx  # Settings
├── components/
│   ├── ui/                # shadcn/ui components
│   ├── layout/            # Sidebar, TopBar
│   ├── explorer/          # Explorer components + hooks
│   ├── features/          # FeaturesTab
│   ├── evidence/          # Evidence components
│   ├── kanban/            # Kanban components
│   ├── terminal/          # Terminal (orphaned)
│   ├── roundtable/        # Roundtable (orphaned)
│   ├── tasks/             # Task components (orphaned)
│   ├── vision/            # Vision components
│   ├── beads/             # Beads (deprecated?)
│   └── notifications/     # Notification components
├── hooks/
│   └── useFeatures.tsx    # Feature hooks
└── lib/
    └── api.ts             # API client functions
```

### Code Patterns

**Data Fetching:** TanStack Query with hooks
```tsx
const { data, isLoading, error } = useQuery({
  queryKey: ["projects"],
  queryFn: fetchProjects,
});
```

**Styling:** Tailwind CSS with custom theme (phosphor accent color)
```tsx
className="bg-phosphor-500/10 text-phosphor-400"
```

**Tab Navigation:** State-based tabs with URL sync
```tsx
const [activeTab, setActiveTab] = useState<TabId>(urlTab || "explorer");
```

**Page Structure:** Header + Content pattern
```tsx
<div className="p-6 space-y-6">
  <header className="animate-in">...</header>
  <section>...</section>
</div>
```

---

## 6. API Coverage

### Backend Endpoints with No Frontend

| Endpoint | Purpose | Frontend Status |
|----------|---------|-----------------|
| `POST /api/projects` | Create project | API client exists, no UI form |
| `POST /api/projects/{id}/features` | Create feature | No API client, no UI |
| `POST /api/projects/{id}/tasks` | Create task | API client exists, no UI |
| `/api/projects/{id}/terminal/*` | Terminal operations | Components exist, not wired |
| `/api/projects/{id}/roundtable/*` | Roundtable chat | Component exists, not wired |

---

## 7. Verification: Original Assumptions vs Reality

| Assumption | Reality |
|------------|---------|
| "No way to navigate to components" | **MOSTLY FALSE** - Good navigation exists |
| "Page routes may be missing" | **PARTIALLY TRUE** - `/projects/new` is missing |
| "No application shell/layout" | **FALSE** - Proper layout with Sidebar + TopBar |
| "Feature creation only via curl" | **TRUE** - No UI for creating features |
| "Users may have no way to access app" | **FALSE** - Dashboard works fine |

---

## 8. Gaps Summary

### Priority 1 (Critical)

1. **Create `/projects/new` page** - Blocking new user onboarding
2. **Add Kanban link** - Fully built feature is inaccessible

### Priority 2 (High)

3. **Wire Terminal button** - Component exists, just needs connection
4. **Replace BeadsTab with IssueTasksTab** - Migration incomplete
5. **Add Feature creation UI** - Currently curl-only

### Priority 3 (Medium)

6. **Wire Roundtable** - Component exists, needs page/modal
7. **Add Task creation UI** - API exists, needs form
8. **Fix Refresh button** - Should invalidate TanStack Query cache

### Priority 4 (Low)

9. **Clean up orphaned components** - Or wire them up
10. **Add project edit/delete UI** - APIs exist

---

## Appendix: File References

| File | Lines | Purpose |
|------|-------|---------|
| `frontend/app/layout.tsx` | 38 | Root layout with Sidebar + TopBar |
| `frontend/app/page.tsx` | 291 | Dashboard with projects grid |
| `frontend/components/layout/Sidebar.tsx` | 270 | Navigation sidebar |
| `frontend/components/layout/TopBar.tsx` | 134 | Top action bar |
| `frontend/app/projects/[id]/page.tsx` | 226 | Project detail with tabs |
| `frontend/app/projects/[id]/kanban/page.tsx` | 111 | Orphaned Kanban page |
| `frontend/lib/api.ts` | 838 | Comprehensive API client |
