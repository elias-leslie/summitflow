'use client'

import { clsx } from 'clsx'
import type { FeedbackStatusFilter, FeedbackSummary } from '@/lib/api/feedback'

// ─── Stat Pill ───────────────────────────────────────────────────

function StatPill({
  value,
  label,
  tone,
  isActive,
  onClick,
}: {
  value: number
  label: string
  tone: string
  isActive: boolean
  onClick: () => void
}) {
  if (value === 0 && !isActive) return null
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-mono tabular-nums transition-all',
        isActive ? 'ring-1 ring-white/20 shadow-lg shadow-black/20' : '',
        tone,
      )}
    >
      <span className="font-semibold">{value}</span>
      <span className="opacity-60">{label}</span>
    </button>
  )
}

// ─── Health Bar ──────────────────────────────────────────────────

function FeedbackHealthBar({
  summary,
}: {
  summary: FeedbackSummary | undefined
}) {
  if (!summary?.by_component) return null

  const components = Object.entries(summary.by_component)
    .filter(([, d]) => d.total > 0)
    .sort((a, b) => b[1].total - a[1].total)

  if (components.length === 0) return null

  return (
    <div className="flex gap-0.5 h-2 rounded-full overflow-hidden bg-slate-800/50">
      {components.map(([id, data]) => {
        const frictionRatio = data.total > 0 ? data.friction / data.total : 0
        const praiseRatio = data.total > 0 ? data.praise / data.total : 0
        const tone =
          frictionRatio > 0.5
            ? 'bg-red-500'
            : praiseRatio > 0.5
              ? 'bg-emerald-500'
              : frictionRatio > 0.25
                ? 'bg-amber-500'
                : 'bg-blue-500'
        return (
          <div
            key={id}
            className={clsx('transition-colors duration-500', tone)}
            style={{ flex: data.total }}
            title={`${id}: ${data.friction} friction, ${data.idea} ideas, ${data.praise} praise`}
          />
        )
      })}
    </div>
  )
}

// ─── Main ────────────────────────────────────────────────────────

interface FeedbackStatsProps {
  summary: FeedbackSummary | undefined
  isLoading: boolean
  activeType: string | undefined
  activeStatus: FeedbackStatusFilter | undefined
  onTypeClick: (type: string | undefined) => void
  onStatusClick: (status: FeedbackStatusFilter | undefined) => void
}

export function FeedbackStats({
  summary,
  isLoading,
  activeType,
  activeStatus,
  onTypeClick,
  onStatusClick,
}: FeedbackStatsProps) {
  if (isLoading || !summary) return null

  const active = (summary.by_status?.open ?? 0) + (summary.by_status?.acknowledged ?? 0)
  const friction = summary.by_type?.friction ?? 0
  const ideas = summary.by_type?.idea ?? 0
  const improvements = summary.by_type?.improvement ?? 0
  const praise = summary.by_type?.praise ?? 0

  const handleClick = (key: string) => {
    if (key === 'active') {
      onTypeClick(undefined)
      onStatusClick(activeStatus === 'active' ? undefined : 'active')
    } else {
      onStatusClick(undefined)
      onTypeClick(activeType === key ? undefined : key)
    }
  }

  return (
    <div className="space-y-3">
      <FeedbackHealthBar summary={summary} />
      <div className="flex flex-wrap items-center gap-2">
        <StatPill
          value={active}
          label="active"
          tone="bg-slate-500/8 text-slate-400 border-slate-500/20"
          isActive={activeStatus === 'active' && !activeType}
          onClick={() => handleClick('active')}
        />
        <StatPill
          value={friction}
          label="friction"
          tone="bg-red-500/8 text-red-400 border-red-500/20"
          isActive={activeType === 'friction'}
          onClick={() => handleClick('friction')}
        />
        <StatPill
          value={ideas}
          label="ideas"
          tone="bg-amber-500/8 text-amber-400 border-amber-500/20"
          isActive={activeType === 'idea'}
          onClick={() => handleClick('idea')}
        />
        <StatPill
          value={improvements}
          label="improvements"
          tone="bg-blue-500/8 text-blue-400 border-blue-500/20"
          isActive={activeType === 'improvement'}
          onClick={() => handleClick('improvement')}
        />
        <StatPill
          value={praise}
          label="praise"
          tone="bg-emerald-500/8 text-emerald-400 border-emerald-500/20"
          isActive={activeType === 'praise'}
          onClick={() => handleClick('praise')}
        />
        <span className="ml-auto text-[11px] text-slate-500">
          {summary.total} total
        </span>
      </div>
    </div>
  )
}
