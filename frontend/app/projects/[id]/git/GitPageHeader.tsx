'use client'

import { Loader2, RefreshCw } from 'lucide-react'

interface GitPageHeaderProps {
  cleanCount: number
  dirtyCount: number
  isSyncing: boolean
  onSync: () => void
}

export function GitPageHeader({
  cleanCount,
  dirtyCount,
  isSyncing,
  onSync,
}: GitPageHeaderProps) {
  return (
    <header className="relative">
      <div className="flex items-center gap-3 mb-2">
        <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">
          Git Control
        </span>
        <div className="h-px flex-1 bg-gradient-to-r from-phosphor-500/50 via-outrun-500/30 to-transparent" />
      </div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="display text-3xl font-bold text-white tracking-tight">
            Repository Status
          </h1>
          <p className="text-slate-400 mt-1">
            Monitor and sync managed repositories
          </p>
        </div>

        {/* Sync All Button */}
        <button
          onClick={onSync}
          disabled={isSyncing}
          className="relative group flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-phosphor-600 to-phosphor-500 text-slate-900 font-semibold rounded-lg transition-all hover:shadow-[0_0_30px_rgba(0,245,255,0.4)] disabled:opacity-50 disabled:cursor-not-allowed overflow-hidden"
        >
          {/* Shimmer effect */}
          <div className="absolute inset-0 -translate-x-full group-hover:translate-x-full transition-transform duration-700 bg-gradient-to-r from-transparent via-white/20 to-transparent" />

          {isSyncing ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <RefreshCw className="w-5 h-5" />
          )}
          <span>{isSyncing ? 'Syncing...' : 'Sync All'}</span>

          {/* Glow ring when syncing */}
          {isSyncing && (
            <span className="absolute inset-0 rounded-lg animate-pulse ring-2 ring-phosphor-400/50" />
          )}
        </button>
      </div>

      {/* Quick Stats Bar */}
      <div className="mt-6 flex items-center gap-6">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-phosphor-500 shadow-[0_0_8px_rgba(0,245,255,0.6)]" />
          <span className="text-sm text-slate-300">{cleanCount} Clean</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-outrun-500 shadow-[0_0_8px_rgba(255,0,102,0.6)]" />
          <span className="text-sm text-slate-300">{dirtyCount} Modified</span>
        </div>
      </div>
    </header>
  )
}
