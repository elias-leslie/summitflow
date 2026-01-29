/**
 * FilterBar - Priority filter controls for refactor targets
 */

'use client'

import { cn } from '@/lib/utils'
import type { PriorityFilter } from './utils/codeHealthUtils'

interface FilterBarProps {
  activeFilter: PriorityFilter
  onFilterChange: (filter: PriorityFilter) => void
  highCount: number
  mediumCount: number
}

export function FilterBar({
  activeFilter,
  onFilterChange,
  highCount,
  mediumCount,
}: FilterBarProps) {
  const filters: { value: PriorityFilter; label: string; count: number }[] = [
    { value: 'all', label: 'All', count: highCount + mediumCount },
    { value: 'high', label: 'Critical', count: highCount },
    { value: 'medium', label: 'Warning', count: mediumCount },
  ]

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500 mr-2">FILTER:</span>
      {filters.map((f) => (
        <button
          key={f.value}
          onClick={() => onFilterChange(f.value)}
          className={cn(
            'px-3 py-1.5 text-xs rounded border transition-colors',
            activeFilter === f.value
              ? 'bg-slate-700 border-slate-600 text-slate-200'
              : 'bg-transparent border-slate-700/50 text-slate-500 hover:text-slate-300 hover:border-slate-600',
          )}
        >
          {f.label} ({f.count})
        </button>
      ))}
    </div>
  )
}
