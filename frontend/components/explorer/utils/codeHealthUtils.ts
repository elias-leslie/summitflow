/**
 * Utility functions for code health data processing
 */

import type { RefactorTarget } from './codeHealthApi'

export type SortField =
  | 'path'
  | 'complexity_score'
  | 'lines_of_code'
  | 'hotspot_score'
  | 'priority'
export type SortDir = 'asc' | 'desc'
export type PriorityFilter = 'all' | 'high' | 'medium'

/**
 * Filter targets by priority
 */
export function filterByPriority(
  targets: RefactorTarget[],
  filter: PriorityFilter,
): RefactorTarget[] {
  if (filter === 'all') {
    return targets
  }
  return targets.filter((t) => t.priority === filter)
}

/**
 * Sort targets by field and direction
 */
export function sortTargets(
  targets: RefactorTarget[],
  field: SortField,
  dir: SortDir,
): RefactorTarget[] {
  const sorted = [...targets].sort((a, b) => {
    let cmp = 0
    switch (field) {
      case 'path':
        cmp = a.path.localeCompare(b.path)
        break
      case 'complexity_score':
        cmp = a.complexity_score - b.complexity_score
        break
      case 'hotspot_score':
        cmp = a.hotspot_score - b.hotspot_score
        break
      case 'lines_of_code':
        cmp = a.lines_of_code - b.lines_of_code
        break
      case 'priority': {
        const priorityOrder = { high: 0, medium: 1, none: 2 }
        cmp = priorityOrder[a.priority] - priorityOrder[b.priority]
        break
      }
    }
    return dir === 'desc' ? -cmp : cmp
  })
  return sorted
}

/**
 * Get priority badge styles
 */
export function getPriorityStyles(priority: RefactorTarget['priority']) {
  const styles = {
    high: {
      bg: 'bg-red-950/30',
      border: 'border-red-500/30',
      text: 'text-red-400',
      badge: 'bg-red-500',
      label: 'CRITICAL',
    },
    medium: {
      bg: 'bg-amber-950/30',
      border: 'border-amber-500/30',
      text: 'text-amber-400',
      badge: 'bg-amber-500',
      label: 'WARNING',
    },
    none: {
      bg: 'bg-slate-800/30',
      border: 'border-slate-700/30',
      text: 'text-slate-400',
      badge: 'bg-slate-500',
      label: 'OK',
    },
  }
  return styles[priority]
}
