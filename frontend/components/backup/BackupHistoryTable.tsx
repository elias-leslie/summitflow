'use client'

import { clsx } from 'clsx'
import {
  AlertCircle,
  ChevronDown,
  Loader2,
  ShieldCheck,
  ShieldX,
} from 'lucide-react'
import { Fragment, type ReactNode } from 'react'
import type { Backup, BackupSource } from '@/lib/api/backups'
import { BackupExpandedRow } from './BackupExpandedRow'
import { StatusBadge } from './StatusBadge'

export type BackupColumn = {
  key: string
  label: string
  className?: string
  render: (backup: Backup) => ReactNode
}

export function BackupTypeBadge({
  backupType,
}: {
  backupType: Backup['backup_type']
}) {
  return (
    <span
      className={clsx(
        'text-xs px-2 py-0.5 rounded-full',
        backupType === 'scheduled'
          ? 'bg-indigo-500/20 text-indigo-400'
          : 'bg-slate-600 text-slate-300',
      )}
    >
      {backupType}
    </span>
  )
}

export function BackupHistoryTable({
  backups,
  isLoading,
  hasError,
  onRetry,
  emptyState,
  expandedId,
  onToggleExpanded,
  columns,
  renderActions,
  getExpandedSourceName,
  getExpandedSourceType,
}: {
  backups: Backup[]
  isLoading: boolean
  hasError: boolean
  onRetry: () => void
  emptyState: ReactNode
  expandedId: string | null
  onToggleExpanded: (id: string | null) => void
  columns: BackupColumn[]
  renderActions: (backup: Backup) => ReactNode
  getExpandedSourceName: (backup: Backup) => string
  getExpandedSourceType: (
    backup: Backup,
  ) => BackupSource['source_type'] | undefined
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (hasError) {
    return (
      <div className="p-6 bg-red-500/10 border border-red-500/30 rounded-lg text-center">
        <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
        <p className="text-red-400">Failed to load backups</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 text-sm text-slate-400 hover:text-slate-200"
        >
          Try again
        </button>
      </div>
    )
  }

  if (backups.length === 0) return emptyState

  const expandedColSpan = columns.length + 3

  return (
    <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-slate-700 bg-slate-800/80">
            <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-8" />
            <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
              Status
            </th>
            {columns.map((column) => (
              <th
                key={column.key}
                className={clsx(
                  'px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider',
                  column.className,
                )}
              >
                {column.label}
              </th>
            ))}
            <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {backups.map((backup) => {
            const isExpanded = expandedId === backup.id
            return (
              <Fragment key={backup.id}>
                <tr
                  className={clsx(
                    'hover:bg-slate-700/30 transition-colors cursor-pointer',
                    isExpanded && 'bg-slate-700/20',
                  )}
                  onClick={() =>
                    onToggleExpanded(isExpanded ? null : backup.id)
                  }
                >
                  <td className="px-4 py-3">
                    <ChevronDown
                      className={clsx(
                        'w-4 h-4 text-slate-500 transition-transform',
                        isExpanded && 'rotate-180',
                      )}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <StatusBadge status={backup.status} />
                      {backup.verified != null && (
                        <span
                          title={
                            backup.verified ? 'Verified' : 'Verification failed'
                          }
                        >
                          {backup.verified ? (
                            <ShieldCheck className="w-3.5 h-3.5 text-green-400" />
                          ) : (
                            <ShieldX className="w-3.5 h-3.5 text-red-400" />
                          )}
                        </span>
                      )}
                    </div>
                  </td>
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={clsx('px-4 py-3', column.className)}
                    >
                      {column.render(backup)}
                    </td>
                  ))}
                  <td className="px-4 py-3 text-right">
                    <div
                      className="flex items-center justify-end gap-2"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {renderActions(backup)}
                    </div>
                  </td>
                </tr>
                {isExpanded && (
                  <BackupExpandedRow
                    backup={backup}
                    sourceName={getExpandedSourceName(backup)}
                    sourceType={getExpandedSourceType(backup)}
                    colSpan={expandedColSpan}
                  />
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
