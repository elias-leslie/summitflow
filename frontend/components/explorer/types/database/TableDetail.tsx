/**
 * TableDetail - Detail panel for database tables
 *
 * Shows columns, relationships, data quality metrics.
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'

interface TableDetailProps {
  entry: ExplorerEntry
}

const formatNumber = (n: number | undefined | null) => (n ?? 0).toLocaleString()

export function TableDetail({ entry }: TableDetailProps) {
  const meta = entry.metadata
  const columns = meta.columns ?? []
  const columnsWithData = meta.columns_with_data ?? []
  const columnsNull = meta.columns_mostly_null ?? []
  const refs = meta.relationships?.references ?? []
  const refdBy = meta.relationships?.referenced_by ?? []

  return (
    <div className="space-y-4">
      {/* Table name */}
      <div>
        <span className="text-xs text-slate-500 uppercase tracking-wide">
          Table
        </span>
        <p className="font-mono text-sm text-slate-300 mt-1">{entry.path}</p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Rows
          </span>
          <p className="font-mono text-sm text-slate-200 mt-1">
            {formatNumber(meta.row_count)}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Columns
          </span>
          <p className="font-mono text-sm text-slate-200 mt-1">
            {meta.column_count ?? 0}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Completeness
          </span>
          <p
            className={cn(
              'font-mono text-sm mt-1',
              meta.completeness_pct !== undefined && meta.completeness_pct >= 90
                ? 'text-emerald-400'
                : meta.completeness_pct !== undefined &&
                    meta.completeness_pct < 50
                  ? 'text-amber-400'
                  : 'text-slate-200',
            )}
          >
            {meta.completeness_pct !== undefined
              ? `${Math.round(meta.completeness_pct)}%`
              : '-'}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Freshness
          </span>
          <p className="font-mono text-sm text-slate-200 mt-1">
            {meta.freshness_days !== undefined
              ? meta.freshness_days === 0
                ? 'Today'
                : `${meta.freshness_days}d ago`
              : '-'}
          </p>
        </div>
      </div>

      {/* Columns list */}
      {columns.length > 0 && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Columns ({columns.length})
          </span>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {columns.map((col) => {
              const hasData = columnsWithData.includes(col)
              const isNull = columnsNull.includes(col)
              return (
                <span
                  key={col}
                  className={cn(
                    'px-2 py-0.5 rounded text-xs font-mono',
                    isNull
                      ? 'bg-amber-500/10 text-amber-400/70'
                      : hasData
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : 'bg-slate-700/50 text-slate-400',
                  )}
                >
                  {col}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {/* Relationships */}
      {(refs.length > 0 || refdBy.length > 0) && (
        <div className="pt-2 border-t border-slate-700/50">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Relationships
          </span>
          <div className="mt-2 space-y-2">
            {refs.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">References:</span>
                <span className="ml-2 text-xs font-mono text-blue-400">
                  {refs.join(', ')}
                </span>
              </div>
            )}
            {refdBy.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Referenced by:</span>
                <span className="ml-2 text-xs font-mono text-purple-400">
                  {refdBy.join(', ')}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
