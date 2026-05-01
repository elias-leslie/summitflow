'use client'

import clsx from 'clsx'
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  GitCompareArrows,
} from 'lucide-react'

interface RemoteStatusBadgeProps {
  ahead: number
  behind: number
  branch: string
  checkedAt?: Date | null
  compact?: boolean
}

function formatCheckedAt(checkedAt?: Date | null): string {
  if (!checkedAt) return 'not checked this session'
  return checkedAt.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function RemoteStatusBadge({
  ahead,
  behind,
  branch,
  checkedAt,
  compact = false,
}: RemoteStatusBadgeProps) {
  const diverged = ahead > 0 && behind > 0
  const isBehind = behind > 0 && ahead === 0
  const isAhead = ahead > 0 && behind === 0
  const label = diverged
    ? `Diverged ${ahead}/${behind}`
    : isBehind
      ? `Behind ${behind}`
      : isAhead
        ? `Ahead ${ahead}`
        : 'In sync'
  const Icon = diverged
    ? GitCompareArrows
    : isBehind
      ? ArrowDown
      : isAhead
        ? ArrowUp
        : CheckCircle2
  const tone = diverged
    ? 'border-rose-500/25 bg-rose-500/10 text-rose-300'
    : isBehind
      ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
      : isAhead
        ? 'border-cyan-500/25 bg-cyan-500/10 text-cyan-300'
        : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
  const checkedText = formatCheckedAt(checkedAt)
  const tooltip = `${label} vs origin/${branch}. Remote refs ${checkedText}. Use Check Remote to refresh.`

  return (
    <span className="group relative inline-flex shrink-0">
      <span
        className={clsx(
          'inline-flex items-center rounded-md border font-mono tabular-nums',
          compact
            ? 'gap-0.5 px-1.5 py-0.5 text-[10px]'
            : 'gap-1 px-2 py-0.5 text-2xs',
          tone,
        )}
        title={tooltip}
      >
        <Icon className={compact ? 'h-2.5 w-2.5' : 'h-3 w-3'} />
        <span>{compact ? label.replace('In sync', 'Sync') : label}</span>
      </span>
      <span className="pointer-events-none absolute right-0 top-full z-30 mt-2 w-max max-w-[260px] rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-[11px] leading-snug text-slate-200 opacity-0 shadow-xl shadow-black/30 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {tooltip}
      </span>
    </span>
  )
}
