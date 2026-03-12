/**
 * DataList - Generic data list with column headers
 *
 * Renders a list of items with sortable column headers
 * and expandable rows. Used by all explorer types.
 */

'use client'

import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DataRowSkeleton } from './DataRow'
import type { ExplorerColumn } from './types'

interface DataListProps<T> {
  items: T[]
  columns: ExplorerColumn<T>[]
  sortField: string
  sortDir: 'asc' | 'desc'
  onSort: (field: string) => void
  renderRow: (item: T, index: number) => React.ReactNode
  isLoading?: boolean
  emptyMessage?: string
  emptyIcon?: React.ReactNode
  className?: string
}

export function DataList<T>({
  items,
  columns,
  sortField,
  sortDir,
  onSort,
  renderRow,
  isLoading = false,
  emptyMessage = 'No items found',
  emptyIcon,
  className,
}: DataListProps<T>) {
  if (isLoading) {
    return <DataRowSkeleton count={8} />
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-500">
        {emptyIcon && <div className="mb-4 opacity-40">{emptyIcon}</div>}
        <p className="text-sm">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Column headers */}
      <div
        className={cn(
          'flex items-center gap-2 px-3 py-2',
          'bg-slate-900/50 border-b border-slate-700/50',
          'text-xs font-medium text-slate-500 uppercase tracking-wide',
        )}
      >
        {/* Spacer for chevron and status */}
        <span className="w-10" />

        {columns.map((col) => (
          <button
            type="button"
            key={col.key}
            onClick={() => onSort(col.key)}
            className={cn(
              'flex items-center gap-1 transition-colors',
              'hover:text-slate-300',
              col.align === 'right' && 'justify-end',
              col.align === 'center' && 'justify-center',
              sortField === col.key && 'text-phosphor-400',
            )}
            style={{ width: col.width, flex: col.width ? undefined : 1 }}
          >
            <span>{col.label}</span>
            {sortField === col.key ? (
              sortDir === 'asc' ? (
                <ArrowUp className="w-3 h-3" />
              ) : (
                <ArrowDown className="w-3 h-3" />
              )
            ) : (
              <ArrowUpDown className="w-3 h-3 opacity-40" />
            )}
          </button>
        ))}
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-auto">
        <div className="divide-y divide-slate-800/50">
          {items.map((item, index) => renderRow(item, index))}
        </div>
      </div>
    </div>
  )
}

/**
 * ColumnValue - Helper for rendering column values with consistent styling
 */
export function ColumnValue({
  children,
  align = 'left',
  mono = false,
  muted = false,
  highlight = false,
  width,
  className,
}: {
  children: React.ReactNode
  align?: 'left' | 'center' | 'right'
  mono?: boolean
  muted?: boolean
  highlight?: boolean
  width?: string
  className?: string
}) {
  return (
    <span
      className={cn(
        'text-sm truncate',
        mono && 'font-mono',
        muted && 'text-slate-500',
        highlight && 'text-phosphor-400 font-medium',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        className,
      )}
      style={{ width }}
    >
      {children}
    </span>
  )
}
