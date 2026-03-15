'use client'

import { Loader2 } from 'lucide-react'
import type { BackupHealthResponse, StorageStatus, StorageSummary } from '@/lib/api/backups'
import { formatBytes } from '@/lib/format'

interface StatusRibbonProps {
  health: BackupHealthResponse | undefined
  storageSummary: StorageSummary | undefined
  storageStatus: StorageStatus | undefined
  isLoading: boolean
}

export function StatusRibbon({ health, storageSummary, storageStatus, isLoading }: StatusRibbonProps) {
  if (isLoading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700 px-4 py-3 mb-6 flex items-center gap-2 text-sm text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading status...
      </div>
    )
  }

  const sources = health?.sources ?? []
  const greenCount = sources.filter(s => s.health_status === 'green').length
  const yellowCount = sources.filter(s => s.health_status === 'yellow').length
  const redCount = sources.filter(s => s.health_status === 'red').length
  const totalBackups = storageSummary?.total_count ?? 0
  const totalBytes = storageSummary?.total_bytes ?? 0

  return (
    <div className="bg-slate-800/50 rounded-lg border border-slate-700 px-4 py-3 mb-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
      {/* Health */}
      {sources.length > 0 && (
        <span className="flex items-center gap-2 text-slate-300">
          {greenCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              {greenCount} healthy
            </span>
          )}
          {yellowCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              {yellowCount} warning
            </span>
          )}
          {redCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
              {redCount} failing
            </span>
          )}
        </span>
      )}

      <span className="text-slate-600 hidden sm:inline">&middot;</span>

      {/* Storage totals */}
      <span className="text-slate-400">
        {totalBackups} backup{totalBackups !== 1 ? 's' : ''}
        <span className="text-slate-600 mx-1">&middot;</span>
        {formatBytes(totalBytes)}
      </span>

      <span className="text-slate-600 hidden sm:inline">&middot;</span>

      {/* Backend */}
      {storageStatus?.configured ? (
        <span className="text-slate-400">
          {storageStatus.default_backend_name}
        </span>
      ) : (
        <span className="text-amber-400 text-xs">No storage backend</span>
      )}
    </div>
  )
}
