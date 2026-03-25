'use client'

import { clsx } from 'clsx'
import type { FeedbackStatusFilter, FeedbackSummary } from '@/lib/api/feedback'

function StatCard({
  value,
  label,
  description,
  tone,
  isActive,
  onClick,
}: {
  value: number
  label: string
  description: string
  tone: string
  isActive: boolean
  onClick: () => void
}) {
  if (value === 0 && !isActive) return null
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      className={clsx(
        'rounded-[1.35rem] border px-4 py-4 text-left transition-all duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40',
        isActive
          ? 'ring-1 ring-phosphor-500/30 shadow-[0_18px_40px_rgba(2,6,23,0.32)]'
          : 'hover:-translate-y-0.5 hover:shadow-[0_18px_40px_rgba(2,6,23,0.24)]',
        tone,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
          {label}
        </span>
        {isActive ? (
          <span className="rounded-full border border-phosphor-500/20 bg-phosphor-500/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-phosphor-300">
            filtered
          </span>
        ) : null}
      </div>
      <div className="mt-4 font-mono text-3xl tabular-nums text-slate-50">
        {value}
      </div>
      <div className="mt-2 text-xs leading-relaxed text-slate-400">
        {description}
      </div>
    </button>
  )
}

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
    <div className="rounded-[1.35rem] border border-slate-800/70 bg-slate-950/55 px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
            Component pressure map
          </div>
          <p className="mt-1 text-xs text-slate-400">
            Larger segments indicate the components collecting the most signal.
          </p>
        </div>
        <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-3 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
          {components.length} components
        </span>
      </div>

      <div className="mt-4 flex h-3 overflow-hidden rounded-full border border-white/5 bg-slate-800/50">
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
    </div>
  )
}

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

  const cards = [
    {
      key: 'active',
      value: active,
      label: 'Active',
      description: 'Open and acknowledged items that still need a response.',
      tone: 'border-slate-700/70 bg-slate-950/60 text-slate-200',
      isActive: activeStatus === 'active' && !activeType,
    },
    {
      key: 'friction',
      value: friction,
      label: 'Friction',
      description: 'Pain points reported by agents while working.',
      tone: 'border-rose-500/20 bg-rose-500/10 text-rose-200',
      isActive: activeType === 'friction',
    },
    {
      key: 'idea',
      value: ideas,
      label: 'Ideas',
      description: 'Potential opportunities and experiments worth evaluating.',
      tone: 'border-amber-500/20 bg-amber-500/10 text-amber-200',
      isActive: activeType === 'idea',
    },
    {
      key: 'improvement',
      value: improvements,
      label: 'Improvements',
      description: 'Refinements that can upgrade the working experience.',
      tone: 'border-blue-500/20 bg-blue-500/10 text-blue-200',
      isActive: activeType === 'improvement',
    },
    {
      key: 'praise',
      value: praise,
      label: 'Praise',
      description: 'Signals showing what is already working well.',
      tone: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200',
      isActive: activeType === 'praise',
    },
  ]

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
    <section className="card-elevated space-y-4 px-5 py-5">
      <div>
        <div className="eyebrow">Signal overview</div>
        <h2 className="display mt-2 text-2xl font-semibold text-slate-100">
          What the feedback mix is saying
        </h2>
      </div>
      <FeedbackHealthBar summary={summary} />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {cards.map((card) => (
          <StatCard
            key={card.key}
            value={card.value}
            label={card.label}
            description={card.description}
            tone={card.tone}
            isActive={card.isActive}
            onClick={() => handleClick(card.key)}
          />
        ))}
      </div>
    </section>
  )
}
