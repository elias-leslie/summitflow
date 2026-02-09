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
  icon: 'sparkles' | 'eye' | 'lightbulb' | null
}

// ============================================================================
// Column Configuration (6 columns: Ideas + Planning + Queue + Active + Blocked + Done)
// ============================================================================

export const COLUMNS: KanbanColumn[] = [
  { id: 'ideas', title: 'Ideas', color: 'yellow', icon: 'lightbulb' },
  { id: 'planning', title: 'Planning', color: 'slate', icon: null },
  { id: 'queue', title: 'Queue', color: 'sky', icon: null },
  { id: 'active', title: 'Active', color: 'blue', icon: null },
  { id: 'blocked', title: 'Blocked', color: 'orange', icon: null },
  { id: 'done', title: 'Done', color: 'phosphor', icon: null },
]

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
  { header: string; border: string; bg: string }
> = {
  yellow: {
    header: 'text-yellow-400',
    border: 'border-yellow-500/30',
    bg: 'bg-yellow-950/20',
  },
  slate: {
    header: 'text-slate-400',
    border: 'border-slate-700',
    bg: 'bg-slate-900/30',
  },
  sky: {
    header: 'text-sky-400',
    border: 'border-sky-500/30',
    bg: 'bg-sky-950/20',
  },
  blue: {
    header: 'text-blue-400',
    border: 'border-blue-700/50',
    bg: 'bg-slate-900/30',
  },
  amber: {
    header: 'text-amber-400',
    border: 'border-amber-500/30',
    bg: 'bg-amber-950/20',
  },
  orange: {
    header: 'text-orange-400',
    border: 'border-orange-500/30',
    bg: 'bg-orange-950/20',
  },
  violet: {
    header: 'text-violet-400',
    border: 'border-violet-500/30',
    bg: 'bg-violet-950/20',
  },
  phosphor: {
    header: 'text-phosphor-400',
    border: 'border-phosphor-700/50',
    bg: 'bg-slate-900/30',
  },
}
