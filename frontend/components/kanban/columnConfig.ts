import type { TaskStatus } from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

// Kanban columns (6 columns: Ideas + Planning + Queue + Active + Blocked + Done)
export type TaskKanbanColumn =
  | 'ideas'
  | 'planning'
  | 'queue'
  | 'active'
  | 'blocked'
  | 'done'

export interface KanbanColumn {
  id: TaskKanbanColumn
  title: string
  color: string
  icon: 'lightbulb' | 'pen-line' | 'clock' | 'zap' | 'shield-alert' | 'circle-check' | null
}

// ============================================================================
// Column Configuration (6 columns: Ideas + Planning + Queue + Active + Blocked + Done)
// ============================================================================

export const COLUMNS: KanbanColumn[] = [
  { id: 'ideas', title: 'Ideas', color: 'yellow', icon: 'lightbulb' },
  { id: 'planning', title: 'Planning', color: 'slate', icon: 'pen-line' },
  { id: 'queue', title: 'Queue', color: 'sky', icon: 'clock' },
  { id: 'active', title: 'Active', color: 'blue', icon: 'zap' },
  { id: 'blocked', title: 'Blocked', color: 'orange', icon: 'shield-alert' },
  { id: 'done', title: 'Done', color: 'phosphor', icon: 'circle-check' },
]

// ============================================================================
// Row Layout Configuration
// ============================================================================

const ROW_ORDER: Record<TaskKanbanColumn, number> = {
  ideas: 0,
  planning: 1,
  queue: 2,
  active: 3,
  done: 4,
  blocked: 5,
}

// Rows that always start collapsed and never persist expand state
export const ALWAYS_COLLAPSED: readonly TaskKanbanColumn[] = ['done']

export const ROWS: KanbanColumn[] = [...COLUMNS].sort(
  (a, b) => ROW_ORDER[a.id] - ROW_ORDER[b.id],
)

// ============================================================================
// Status Mapping (6 columns)
// ============================================================================

// Map task status to Kanban column
// Note: 'idea' status handled specially via crowdsourced label check
export const statusToColumn: Record<TaskStatus, TaskKanbanColumn> = {
  // Planning column
  pending: 'planning',
  // Queue column (waiting for execution)
  queue: 'queue',
  // Active column (all running/transient states)
  running: 'active',
  paused: 'active',
  pr_created: 'active',
  ai_reviewing: 'active',
  // Blocked column
  blocked: 'blocked',
  // Done column
  completed: 'done',
  failed: 'done',
  cancelled: 'done',
  abandoned: 'done',
}

// Map Kanban column to task status (for drag-drop)
export const columnToStatus: Record<TaskKanbanColumn, TaskStatus> = {
  ideas: 'pending',
  planning: 'pending',
  queue: 'queue',
  active: 'running',
  blocked: 'blocked',
  done: 'completed',
}

// ============================================================================
// Column Styles
// ============================================================================

export const columnColorClasses: Record<
  string,
  { header: string; border: string; bg: string; dropIndicator: string }
> = {
  yellow: {
    header: 'text-yellow-400',
    border: 'border-yellow-500/30',
    bg: 'bg-yellow-950/20',
    dropIndicator: 'border-yellow-400/60 bg-yellow-950/40',
  },
  slate: {
    header: 'text-slate-400',
    border: 'border-slate-700',
    bg: 'bg-slate-900/30',
    dropIndicator: 'border-slate-400/60 bg-slate-900/50',
  },
  sky: {
    header: 'text-sky-400',
    border: 'border-sky-500/30',
    bg: 'bg-sky-950/20',
    dropIndicator: 'border-sky-400/60 bg-sky-950/40',
  },
  blue: {
    header: 'text-blue-400',
    border: 'border-blue-700/50',
    bg: 'bg-slate-900/30',
    dropIndicator: 'border-blue-400/60 bg-blue-950/40',
  },
  amber: {
    header: 'text-amber-400',
    border: 'border-amber-500/30',
    bg: 'bg-amber-950/20',
    dropIndicator: 'border-amber-400/60 bg-amber-950/40',
  },
  orange: {
    header: 'text-orange-400',
    border: 'border-orange-500/30',
    bg: 'bg-orange-950/20',
    dropIndicator: 'border-orange-400/60 bg-orange-950/40',
  },
  violet: {
    header: 'text-violet-400',
    border: 'border-violet-500/30',
    bg: 'bg-violet-950/20',
    dropIndicator: 'border-violet-400/60 bg-violet-950/40',
  },
  phosphor: {
    header: 'text-phosphor-400',
    border: 'border-phosphor-700/50',
    bg: 'bg-slate-900/30',
    dropIndicator: 'border-phosphor-400/60 bg-phosphor-950/40',
  },
}
