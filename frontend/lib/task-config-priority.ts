/**
 * Priority color and configuration helpers.
 */

// ============================================================================
// Priority Colors
// ============================================================================

export interface PriorityColorConfig {
  bg: string
  text: string
  border: string
}

export const priorityColors: Record<number, PriorityColorConfig> = {
  0: {
    bg: 'bg-rose-500/30',
    text: 'text-rose-300',
    border: 'border-rose-500/40',
  },
  1: {
    bg: 'bg-orange-500/20',
    text: 'text-orange-400',
    border: 'border-orange-500/30',
  },
  2: {
    bg: 'bg-amber-500/20',
    text: 'text-amber-400',
    border: 'border-amber-500/30',
  },
  3: {
    bg: 'bg-blue-500/20',
    text: 'text-blue-400',
    border: 'border-blue-500/30',
  },
  4: {
    bg: 'bg-slate-500/20',
    text: 'text-slate-400',
    border: 'border-slate-500/30',
  },
}

/** Combined class string for priority badges (TaskCard style) */
export const priorityColorClasses: Record<number, string> = {
  0: 'bg-rose-500/30 text-rose-300 border-rose-500/40', // Critical
  1: 'bg-orange-500/20 text-orange-400 border-orange-500/30', // High
  2: 'bg-amber-500/20 text-amber-400 border-amber-500/30', // Medium
  3: 'bg-blue-500/20 text-blue-400 border-blue-500/30', // Low
  4: 'bg-slate-500/20 text-slate-400 border-slate-500/30', // Backlog
}

export function getPriorityColors(priority: number): PriorityColorConfig {
  return priorityColors[priority] || priorityColors[2]
}

export function getPriorityClasses(priority: number): string {
  return priorityColorClasses[priority] || priorityColorClasses[2]
}

// ============================================================================
// Priority Config (label + color variant, used by TaskRow/TaskListRow)
// ============================================================================

export const priorityConfig: Record<
  number,
  { label: string; color: string; className: string }
> = {
  0: {
    label: 'P0',
    color: 'text-red-500',
    className: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  1: {
    label: 'P1',
    color: 'text-orange-500',
    className: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  },
  2: {
    label: 'P2',
    color: 'text-yellow-500',
    className: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
  3: {
    label: 'P3',
    color: 'text-blue-500',
    className: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  4: {
    label: 'P4',
    color: 'text-slate-500',
    className: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  },
}

// ============================================================================
// Priority Detail Config (label + shortLabel + color, used by TaskPreview)
// ============================================================================

export interface PriorityDetailConfig {
  label: string
  shortLabel: string
  color: string
}

export const PRIORITY_CONFIG: Record<number, PriorityDetailConfig> = {
  0: { label: 'P0 Critical', shortLabel: 'P0', color: 'text-red-400' },
  1: { label: 'P1 High', shortLabel: 'P1', color: 'text-orange-400' },
  2: { label: 'P2 Medium', shortLabel: 'P2', color: 'text-yellow-400' },
  3: { label: 'P3 Low', shortLabel: 'P3', color: 'text-slate-400' },
  4: { label: 'P4 Backlog', shortLabel: 'P4', color: 'text-slate-500' },
}

export function getPriorityConfig(priority: number): PriorityDetailConfig {
  return PRIORITY_CONFIG[priority] || PRIORITY_CONFIG[2]
}
