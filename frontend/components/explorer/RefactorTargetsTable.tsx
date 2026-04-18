/**
 * RefactorTargetsTable - Sortable table with expandable rows for refactor targets
 */

'use client'

import { FileCode } from 'lucide-react'
import { SortableHeader, TargetRow } from './RefactorTargetsTableRows'
import type { RefactorTarget } from './utils/codeHealthApi'
import type { SortDir, SortField } from './utils/codeHealthUtils'

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
      <div className="grid grid-cols-[2rem_1fr_5rem_5rem_4rem_5rem] gap-2 px-3 py-2 bg-slate-800/80 border-b border-slate-700/50 text-xs text-slate-400">
        <div /> {/* Expand toggle */}
        <SortableHeader
          field="path"
          label="FILE"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
        />
        <SortableHeader
          field="hotspot_score"
          label="HOTSPOT"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="justify-end"
        />
        <SortableHeader
          field="complexity_score"
          label="COMPLEXITY"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="justify-end"
        />
        <SortableHeader
          field="lines_of_code"
          label="LOC"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="justify-end"
        />
        <SortableHeader
          field="priority"
          label="STATUS"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="justify-center"
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
