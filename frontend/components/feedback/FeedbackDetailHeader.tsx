'use client'

import { clsx } from 'clsx'
import { X } from 'lucide-react'
import { TYPE_CONFIG } from './feedbackConstants'

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
    <div className="flex items-start justify-between px-4 pt-4 pb-3 border-b border-slate-800/60">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-2">
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] border',
              typeConf.bg,
              typeConf.color,
              typeConf.border,
            )}
          >
            <TypeIcon className="w-3 h-3" />
            {typeConf.label}
          </span>
          <span className="rounded bg-slate-700/70 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-400">
            {componentId}
          </span>
        </div>
        <h2 className="text-sm font-medium text-slate-100 leading-tight">
          {title}
        </h2>
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="shrink-0 p-1 text-slate-600 hover:text-slate-300 transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
