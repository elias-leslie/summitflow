'use client'

import { useState } from 'react'
import { clsx } from 'clsx'
import { AlertTriangle, CheckCircle2, Disc, Loader2 } from 'lucide-react'
import {
  type WalStatus,
  disableWalArchiving,
  enableWalArchiving,
} from '@/lib/api/backups'

interface WalCardProps {
  walStatus: WalStatus | undefined
  isLoading: boolean
  onRefresh: () => void
}

export function WalCard({ walStatus, isLoading, onRefresh }: WalCardProps) {
  const [toggling, setToggling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const enabled = walStatus?.enabled ?? false
  const pendingRestart = !enabled && (walStatus?.pending_restart ?? false)

  const handleToggle = async () => {
    setToggling(true)
    setError(null)
    setNotice(null)
    try {
      if (enabled || pendingRestart) {
        await disableWalArchiving()
        setNotice('WAL archiving disabled.')
      } else {
        await enableWalArchiving()
        setNotice(
          'Archive command configured. PostgreSQL must be restarted to activate archive mode.',
        )
      }
      onRefresh()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to update WAL archiving. Check database user permissions.',
      )
    }
    setToggling(false)
  }

  return (
    <div className="bg-slate-800/50 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Disc className="w-4 h-4 text-slate-400" />
        <h3 className="text-sm font-medium text-slate-200">
          Database Change Log (WAL)
        </h3>
        {enabled && (
          <span className="text-xs text-green-400 ml-auto">Active</span>
        )}
        {pendingRestart && (
          <span className="text-xs text-amber-400 ml-auto">
            Pending restart
          </span>
        )}
        {!enabled && !pendingRestart && (
          <span className="text-xs text-slate-500 ml-auto">Off</span>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading...
        </div>
      ) : (
        <>
          {/* Description — show when not active */}
          {!enabled && !pendingRestart && (
            <p className="text-xs text-slate-400 leading-relaxed mb-3">
              Saves a continuous log of every PostgreSQL database write between
              scheduled backups. Enables recovery to any point in time, not just
              the last backup. Only covers database data — file backups are
              handled separately by source schedules.
            </p>
          )}

          {/* Pending restart notice */}
          {pendingRestart && (
            <div className="flex items-start gap-2 p-2.5 bg-amber-500/10 border border-amber-500/20 rounded mb-3">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
              <p className="text-xs text-amber-300 leading-relaxed">
                Archive command is configured but{' '}
                <code className="text-amber-200">archive_mode</code> requires a
                PostgreSQL restart to activate.
              </p>
            </div>
          )}

          {/* Stats when active */}
          {enabled && (
            <div className="grid grid-cols-2 gap-2 text-xs mb-3">
              <div>
                <p className="text-slate-500">Current LSN</p>
                <p className="text-slate-200 font-mono">
                  {walStatus?.current_lsn}
                </p>
              </div>
              {(walStatus?.archived_count ?? 0) > 0 && (
                <div>
                  <p className="text-slate-500">Archived</p>
                  <p className="text-slate-200">
                    {walStatus?.archived_count} WAL files
                  </p>
                </div>
              )}
              {walStatus?.last_archived_wal && (
                <div>
                  <p className="text-slate-500">Last WAL</p>
                  <p className="text-slate-200 font-mono truncate">
                    {walStatus.last_archived_wal}
                  </p>
                </div>
              )}
              {(walStatus?.failed_count ?? 0) > 0 && (
                <div>
                  <p className="text-slate-500">Failed</p>
                  <p className="text-red-400">
                    {walStatus?.failed_count} failures
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Toggle button */}
          <button
            type="button"
            onClick={handleToggle}
            disabled={toggling}
            className={clsx(
              'flex items-center gap-2 px-3 py-1.5 text-xs rounded-md font-medium transition-colors disabled:opacity-50',
              enabled || pendingRestart
                ? 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                : 'bg-emerald-600 text-white hover:bg-emerald-500',
            )}
          >
            {toggling && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {enabled || pendingRestart
              ? 'Disable Archiving'
              : 'Enable Archiving'}
          </button>

          {/* Feedback */}
          {error && (
            <p className="mt-2 text-xs text-rose-400">{error}</p>
          )}
          {notice && !error && (
            <div className="flex items-start gap-1.5 mt-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0 mt-0.5" />
              <p className="text-xs text-green-400">{notice}</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
