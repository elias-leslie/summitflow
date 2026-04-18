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
 * Human-readable labels and colors for refactor issue types
 */
const ISSUE_STYLES: Record<string, { label: string; color: string }> = {
  high_complexity: {
    label: 'High Complexity',
    color: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  medium_complexity: {
    label: 'Complexity',
    color: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  oversized: {
    label: 'Oversized',
    color: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  large_file: {
    label: 'Large File',
    color: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  bloat_critical: {
    label: 'Bloat',
    color: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  bloat_warning: {
    label: 'Bloat',
    color: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  too_many_functions: {
    label: 'Too Many Funcs',
    color: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  },
  too_many_classes: {
    label: 'Too Many Classes',
    color: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  },
  too_many_imports: {
    label: 'Too Many Imports',
    color: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  },
  has_long_functions: {
    label: 'Long Functions',
    color: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
  has_large_classes: {
    label: 'Large Classes',
    color: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
  deep_nesting: {
    label: 'Deep Nesting',
    color: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  },
  magic_strings: {
    label: 'Magic Strings',
    color: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  },
  stale_todos: {
    label: 'Stale TODOs',
    color: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  },
  deprecated_code: {
    label: 'Deprecated',
    color: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  legacy_code: {
    label: 'Legacy',
    color: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
}

export function getIssueStyle(issue: string) {
  return (
    ISSUE_STYLES[issue] ?? {
      label: issue.replace(/_/g, ' '),
      color: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
    }
  )
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
