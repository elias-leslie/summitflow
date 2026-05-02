'use client'

import { clsx } from 'clsx'
import { ChevronRight } from 'lucide-react'
import { type ReactNode, useState } from 'react'

interface CollapsibleSectionProps {
  title: string
  titleAccessory?: ReactNode
  summary: ReactNode
  children: ReactNode
  defaultExpanded?: boolean
  className?: string
  expandedClassName?: string
  collapsedClassName?: string
  contentClassName?: string
}

export function CollapsibleSection({
  title,
  titleAccessory,
  summary,
  children,
  defaultExpanded = false,
  className,
  expandedClassName,
  collapsedClassName,
  contentClassName = 'border-t border-slate-800/60 px-4 py-4',
}: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <section
      className={clsx(
        'rounded-lg border border-slate-700/60 bg-slate-900/30 overflow-hidden',
        expanded ? expandedClassName : collapsedClassName,
        className,
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-800/30"
        aria-expanded={expanded}
      >
        <ChevronRight
          className={clsx(
            'mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-600 transition-transform duration-200',
            expanded && 'rotate-90',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300 display">
                {title}
              </h2>
              {titleAccessory}
            </div>
            <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              {expanded ? 'Collapse' : 'Expand'}
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-500">{summary}</div>
        </div>
      </button>

      <div
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className={contentClassName}>{children}</div>
        </div>
      </div>
    </section>
  )
}
