'use client'

import { useState } from 'react'
import { clsx } from 'clsx'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Disc,
  Loader2,
} from 'lucide-react'
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
  const [expanded, setExpanded] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const enabled = walStatus?.enabled ?? false
  const pendingRestart = !enabled && (walStatus?.pending_restart ?? false)

  const accentClass = enabled
    ? 'border-l-emerald-500'
    : pendingRestart
      ? 'border-l-amber-500'
      : 'border-l-slate-600'

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
    <div
      className={clsx(
        'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 overflow-hidden transition-all duration-200',
        accentClass,
        expanded
          ? 'border-slate-700/80 shadow-lg shadow-black/20'
          : 'hover:bg-slate-800/60',
      )}
    >
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-800/30"
      >
        <ChevronRight
          className={clsx(
            'w-3.5 h-3.5 text-slate-600 transition-transform duration-200 shrink-0',
            expanded && 'rotate-90',
          )}
        />
        <div
          className={clsx(
            'w-2 h-2 rounded-full shrink-0',
            enabled
              ? 'bg-emerald-500'
              : pendingRestart
                ? 'bg-amber-500'
                : 'bg-slate-600',
          )}
        />
        <Disc className="w-3.5 h-3.5 text-slate-500 shrink-0" />
        <span className="text-sm font-medium text-white">
          Database Change Log (WAL)
        </span>
        <span className="text-xs text-slate-500 flex-1 text-right">
          {enabled
            ? 'Active'
            : pendingRestart
              ? 'Pending restart'
              : 'Off'}
        </span>
      </button>

      {/* Expandable content */}
      <div
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/40 px-4 py-4 space-y-3">
            {isLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading...
              </div>
            ) : (
              <>
                {/* Description — show when not active */}
                {!enabled && !pendingRestart && (
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Saves a continuous log of every PostgreSQL database write
                    between scheduled backups. Enables recovery to any point in
                    time, not just the last backup.
                  </p>
                )}

                {/* Pending restart notice */}
                {pendingRestart && (
                  <div className="flex items-start gap-2 p-2.5 bg-amber-500/8 border border-amber-500/20 rounded">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                    <p className="text-xs text-amber-300 leading-relaxed">
                      Archive command configured but{' '}
                      <code className="text-amber-200">archive_mode</code>{' '}
                      requires a PostgreSQL restart to activate.
                    </p>
                  </div>
                )}

                {/* Stats when active */}
                {enabled && (
                  <div className="grid grid-cols-2 gap-1.5">
                    <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                        Current LSN
                      </div>
                      <div className="truncate text-xs text-slate-200 font-mono">
                        {walStatus?.current_lsn}
                      </div>
                    </div>
                    {(walStatus?.archived_count ?? 0) > 0 && (
                      <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                        <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                          Archived
                        </div>
                        <div className="truncate text-xs text-slate-200">
                          {walStatus?.archived_count} WAL files
                        </div>
                      </div>
                    )}
                    {walStatus?.last_archived_wal && (
                      <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                        <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                          Last WAL
                        </div>
                        <div className="truncate text-xs text-slate-200 font-mono">
                          {walStatus.last_archived_wal}
                        </div>
                      </div>
                    )}
                    {(walStatus?.failed_count ?? 0) > 0 && (
                      <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                        <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                          Failed
                        </div>
                        <div className="truncate text-xs text-red-400">
                          {walStatus?.failed_count} failures
                        </div>
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
                    'text-[11px] px-2.5 py-1 rounded transition-colors disabled:opacity-40 flex items-center gap-1.5',
                    enabled || pendingRestart
                      ? 'bg-slate-700/50 text-slate-400 hover:bg-slate-700/80'
                      : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20',
                  )}
                >
                  {toggling && (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  )}
                  {enabled || pendingRestart
                    ? 'Disable Archiving'
                    : 'Enable Archiving'}
                </button>

                {/* Feedback */}
                {error && (
                  <p className="text-xs text-rose-400">{error}</p>
                )}
                {notice && !error && (
                  <div className="flex items-start gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                    <p className="text-xs text-emerald-400">{notice}</p>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
