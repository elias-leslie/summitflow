/**
 * RefactorTargetsTable - Sortable table with expandable rows for refactor targets
 */

'use client'

import {
  ArrowUpDown,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileCode,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RefactorTarget } from './utils/codeHealthApi'
import {
  getPriorityStyles,
  type SortDir,
  type SortField,
} from './utils/codeHealthUtils'

interface RefactorTargetsTableProps {
  targets: RefactorTarget[]
  sortField: SortField
  sortDir: SortDir
  onSort: (field: SortField) => void
  expandedRows: Set<string>
  onToggleRow: (path: string) => void
  onFileSelect?: (path: string) => void
  isLoading?: boolean
}

export function RefactorTargetsTable({
  targets,
  sortField,
  sortDir,
  onSort,
  expandedRows,
  onToggleRow,
  onFileSelect,
  isLoading,
}: RefactorTargetsTableProps) {
  if (targets.length === 0 && !isLoading) {
    return (
      <div className="text-center py-8 text-slate-500">
        <FileCode className="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p>No refactoring targets match current filters</p>
      </div>
    )
  }

  return (
    <div className="border border-slate-700/50 rounded overflow-hidden">
      {/* Table header */}
      <div className="grid grid-cols-12 gap-2 px-3 py-2 bg-slate-800/80 border-b border-slate-700/50 text-xs text-slate-400">
        <div className="col-span-1" /> {/* Expand toggle */}
        <SortableHeader
          field="path"
          label="FILE"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-5"
        />
        <SortableHeader
          field="complexity_score"
          label="COMPLEXITY"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-2 justify-end"
        />
        <SortableHeader
          field="lines_of_code"
          label="LOC"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-2 justify-end"
        />
        <SortableHeader
          field="priority"
          label="STATUS"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-2 justify-center"
        />
      </div>

      {/* Table body */}
      <div className="max-h-[400px] overflow-y-auto">
        {targets.map((target) => (
          <TargetRow
            key={target.path}
            target={target}
            isExpanded={expandedRows.has(target.path)}
            onToggle={() => onToggleRow(target.path)}
            onFileSelect={onFileSelect}
          />
        ))}
      </div>
    </div>
  )
}

function SortableHeader({
  field,
  label,
  currentField,
  currentDir,
  onSort,
  className,
}: {
  field: SortField
  label: string
  currentField: SortField
  currentDir: SortDir
  onSort: (field: SortField) => void
  className?: string
}) {
  const isActive = currentField === field

  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        'flex items-center gap-1 hover:text-slate-200 transition-colors',
        isActive && 'text-emerald-400',
        className,
      )}
    >
      <span>{label}</span>
      <ArrowUpDown
        className={cn(
          'w-3 h-3',
          isActive ? 'opacity-100' : 'opacity-30',
          isActive && currentDir === 'asc' && 'rotate-180',
        )}
      />
    </button>
  )
}

function TargetRow({
  target,
  isExpanded,
  onToggle,
  onFileSelect,
}: {
  target: RefactorTarget
  isExpanded: boolean
  onToggle: () => void
  onFileSelect?: (path: string) => void
}) {
  const style = getPriorityStyles(target.priority)

  return (
    <div className={cn('border-b border-slate-700/30', style.bg)}>
      {/* Main row */}
      <div
        className="grid grid-cols-12 gap-2 px-3 py-2 items-center cursor-pointer hover:bg-slate-700/20 transition-colors"
        onClick={onToggle}
      >
        <div className="col-span-1">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </div>
        <div className="col-span-5 truncate text-slate-300" title={target.path}>
          <span className="text-slate-500">
            {target.path.split('/').slice(0, -1).join('/')}/
          </span>
          <span className="font-medium">{target.name}</span>
        </div>
        <div className={cn('col-span-2 text-right tabular-nums', style.text)}>
          {target.complexity_score.toFixed(1)}
        </div>
        <div className="col-span-2 text-right tabular-nums text-slate-400">
          {target.lines_of_code.toLocaleString()}
        </div>
        <div className="col-span-2 flex justify-center">
          <span
            className={cn(
              'px-2 py-0.5 text-xs rounded text-white font-medium',
              style.badge,
            )}
          >
            {style.label}
          </span>
        </div>
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div
          className={cn('px-3 py-3 border-t', style.border, 'bg-slate-900/50')}
        >
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div className="space-y-2">
              <div>
                <span className="text-slate-500">Full Path:</span>
                <span className="ml-2 text-slate-300 font-mono">
                  {target.path}
                </span>
              </div>
              <div>
                <span className="text-slate-500">Reason:</span>
                <span className={cn('ml-2', style.text)}>{target.reason}</span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex gap-4">
                <span>
                  <span className="text-slate-500">Functions:</span>
                  <span className="ml-2 text-slate-300">
                    {target.function_count}
                  </span>
                </span>
                <span>
                  <span className="text-slate-500">Classes:</span>
                  <span className="ml-2 text-slate-300">
                    {target.class_count}
                  </span>
                </span>
              </div>
              {onFileSelect && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onFileSelect(target.path)
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 transition-colors"
                >
                  <ExternalLink className="w-3 h-3" />
                  View in Explorer
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
