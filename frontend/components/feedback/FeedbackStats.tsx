'use client'

import { clsx } from 'clsx'
import {
  Lightbulb,
  Loader2,
  MessageSquareWarning,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'
import type { FeedbackStatusFilter, FeedbackSummary } from '@/lib/api/feedback'

const STAT_CARDS = [
  {
    key: 'active',
    label: 'Active',
    icon: MessageSquareWarning,
    getCount: (s: FeedbackSummary) => (s.by_status?.open ?? 0) + (s.by_status?.acknowledged ?? 0),
    color: 'text-slate-200',
    bg: 'bg-slate-500/20',
    iconColor: 'text-slate-400',
  },
  {
    key: 'friction',
    label: 'Friction',
    icon: Zap,
    getCount: (s: FeedbackSummary) => s.by_type?.friction ?? 0,
    color: 'text-rose-400',
    bg: 'bg-rose-500/20',
    iconColor: 'text-rose-400',
  },
  {
    key: 'idea',
    label: 'Ideas',
    icon: Lightbulb,
    getCount: (s: FeedbackSummary) => s.by_type?.idea ?? 0,
    color: 'text-amber-400',
    bg: 'bg-amber-500/20',
    iconColor: 'text-amber-400',
  },
  {
    key: 'improvement',
    label: 'Improvements',
    icon: TrendingUp,
    getCount: (s: FeedbackSummary) => s.by_type?.improvement ?? 0,
    color: 'text-blue-400',
    bg: 'bg-blue-500/20',
    iconColor: 'text-blue-400',
  },
  {
    key: 'praise',
    label: 'Praise',
    icon: Sparkles,
    getCount: (s: FeedbackSummary) => s.by_type?.praise ?? 0,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/20',
    iconColor: 'text-emerald-400',
  },
] as const

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
  return (
    <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
      {STAT_CARDS.map((card) => {
        const Icon = card.icon
        const isActive =
          (card.key === 'active' && activeStatus === 'active') ||
          (card.key !== 'active' && activeType === card.key)
        const handleClick = () => {
          if (card.key === 'active') {
            onTypeClick(undefined)
            onStatusClick(activeStatus === 'active' ? undefined : 'active')
          } else {
            onStatusClick(undefined)
            onTypeClick(activeType === card.key ? undefined : card.key)
          }
        }

        return (
          <button
            key={card.key}
            onClick={handleClick}
            className={clsx(
              'p-4 rounded-lg border transition-all duration-200 text-left cursor-pointer',
              'bg-slate-800/50 hover:bg-slate-800/80',
              isActive
                ? 'border-outrun-500/40 ring-1 ring-outrun-500/20'
                : 'border-slate-700 hover:border-slate-600',
            )}
          >
            <div className="flex items-center gap-3">
              <div className={clsx('p-2 rounded-lg', card.bg)}>
                <Icon className={clsx('w-4 h-4', card.iconColor)} />
              </div>
              <div>
                <p className={clsx('text-xl font-semibold', card.color)}>
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : summary ? (
                    card.getCount(summary)
                  ) : (
                    '—'
                  )}
                </p>
                <p className="text-xs text-slate-500">{card.label}</p>
              </div>
            </div>
          </button>
        )
      })}
    </section>
  )
}
