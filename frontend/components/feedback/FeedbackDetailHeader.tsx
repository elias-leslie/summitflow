'use client'

import { clsx } from 'clsx'
import { Lightbulb, Sparkles, TrendingUp, X, Zap } from 'lucide-react'

// ============================================================================
// Constants
// ============================================================================

export const TYPE_CONFIG = {
  friction: { icon: Zap, label: 'Friction', color: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/30' },
  idea: { icon: Lightbulb, label: 'Idea', color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30' },
  improvement: { icon: TrendingUp, label: 'Improvement', color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30' },
  praise: { icon: Sparkles, label: 'Praise', color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
} as const

// ============================================================================
// Component
// ============================================================================

interface FeedbackDetailHeaderProps {
  feedbackType: keyof typeof TYPE_CONFIG
  componentId: string
  title: string
  onClose: () => void
}

export function FeedbackDetailHeader({
  feedbackType,
  componentId,
  title,
  onClose,
}: FeedbackDetailHeaderProps) {
  const typeConf = TYPE_CONFIG[feedbackType]
  const TypeIcon = typeConf.icon

  return (
    <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-slate-700/50">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-2">
          <span
            className={clsx(
              'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border',
              typeConf.bg,
              typeConf.color,
              typeConf.border,
            )}
          >
            <TypeIcon className="w-3 h-3" />
            {typeConf.label}
          </span>
          <span className="mono text-xs text-slate-500">{componentId}</span>
        </div>
        <h2 className="text-lg font-semibold text-slate-100 leading-tight">{title}</h2>
      </div>
      <button
        onClick={onClose}
        className="flex-shrink-0 p-1.5 text-slate-500 hover:text-slate-300 transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
