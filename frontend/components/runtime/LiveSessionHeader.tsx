'use client'

import { clsx } from 'clsx'
import {
  Lock,
  Monitor,
  MousePointer2,
  Power,
  RefreshCw,
  Unlock,
} from 'lucide-react'
import type { LiveSessionStatus } from '@/lib/api/runtime'

interface LiveSessionHeaderProps {
  session: LiveSessionStatus
  tokenMissing: boolean
  hasOperatorToken: boolean
  sensitivePending: boolean
  controlGrantPending: boolean
  teardownPending: boolean
  onRefreshFrame: () => void
  onToggleSensitive: () => void
  onToggleControlGrant: () => void
  onTeardown: () => void
}

export function LiveSessionHeader({
  session,
  tokenMissing,
  hasOperatorToken,
  sensitivePending,
  controlGrantPending,
  teardownPending,
  onRefreshFrame,
  onToggleSensitive,
  onToggleControlGrant,
  onTeardown,
}: LiveSessionHeaderProps) {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-950/95 px-4 py-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-md border border-sky-500/20 bg-sky-500/10">
        <Monitor className="h-4 w-4 text-sky-300" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">
          {session.title || session.current_url || session.target_url}
        </div>
        <div className="mt-0.5 truncate text-2xs text-slate-500">
          {session.current_url || session.target_url}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onRefreshFrame}
          disabled={tokenMissing}
          title="Refresh frame"
          className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-700 bg-slate-900 text-slate-300 transition-colors hover:border-sky-500/40 hover:text-sky-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onToggleSensitive}
          disabled={!hasOperatorToken || sensitivePending}
          title="Sensitive mode"
          className={clsx(
            'flex h-9 items-center gap-2 rounded-md border px-3 text-xs font-medium transition-colors',
            session.sensitive
              ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
              : 'border-slate-700 bg-slate-900 text-slate-300',
            !hasOperatorToken && 'cursor-not-allowed opacity-50',
          )}
        >
          {session.sensitive ? (
            <Lock className="h-3.5 w-3.5" />
          ) : (
            <Unlock className="h-3.5 w-3.5" />
          )}
          {session.sensitive ? 'Sensitive' : 'Standard'}
        </button>
        <button
          type="button"
          onClick={onToggleControlGrant}
          disabled={!hasOperatorToken || controlGrantPending}
          title="Input control"
          className={clsx(
            'flex h-9 items-center gap-2 rounded-md border px-3 text-xs font-medium transition-colors',
            session.control_enabled
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
              : 'border-slate-700 bg-slate-900 text-slate-300',
            !hasOperatorToken && 'cursor-not-allowed opacity-50',
          )}
        >
          <MousePointer2 className="h-3.5 w-3.5" />
          {session.control_enabled ? 'Input On' : 'Input Locked'}
        </button>
        <button
          type="button"
          onClick={onTeardown}
          disabled={teardownPending || session.state !== 'active'}
          title="Close session"
          className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-700 bg-slate-900 text-slate-400 transition-colors hover:border-rose-500/40 hover:text-rose-200 disabled:opacity-50"
        >
          <Power className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
