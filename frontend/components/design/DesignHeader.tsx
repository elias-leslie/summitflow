'use client'

import { CheckSquare, Grid3X3, List, Palette, Sparkles, X } from 'lucide-react'

export type ViewMode = 'grid' | 'list'

interface DesignHeaderProps {
  title: string
  subtitle?: string
  totalLabel?: string
  primaryActionLabel: string
  viewMode: ViewMode
  selectMode: boolean
  hasItems: boolean
  onViewModeChange: (mode: ViewMode) => void
  onSelectModeToggle: () => void
  onCancelSelectMode: () => void
  onPrimaryAction: () => void
}

export function DesignHeader({
  title,
  subtitle,
  totalLabel,
  primaryActionLabel,
  viewMode,
  selectMode,
  hasItems,
  onViewModeChange,
  onSelectModeToggle,
  onCancelSelectMode,
  onPrimaryAction,
}: DesignHeaderProps): React.ReactElement {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <div className="rounded-2xl bg-cyan-500/10 p-3 ring-1 ring-cyan-400/20">
          <Palette className="h-6 w-6 text-cyan-300" />
        </div>
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-slate-100 display tracking-tight">{title}</h2>
            {totalLabel && (
              <span className="rounded-full bg-slate-900 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                {totalLabel}
              </span>
            )}
          </div>
          {subtitle && <p className="mt-2 max-w-2xl text-sm text-slate-400">{subtitle}</p>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {!selectMode && (
          <button type="button" onClick={onPrimaryAction} className="btn-primary flex items-center gap-2">
            <Sparkles className="h-4 w-4" />
            {primaryActionLabel}
          </button>
        )}

        {hasItems && (
          <button
            type="button"
            onClick={() => (selectMode ? onCancelSelectMode() : onSelectModeToggle())}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition ${
              selectMode
                ? 'border-cyan-400/40 bg-cyan-500/10 text-cyan-200'
                : 'border-slate-700 bg-slate-900 text-slate-300 hover:text-white'
            }`}
          >
            {selectMode ? <X className="h-4 w-4" /> : <CheckSquare className="h-4 w-4" />}
            {selectMode ? 'Cancel' : 'Select'}
          </button>
        )}

        {!selectMode && (
          <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/80 p-1">
            <button
              type="button"
              onClick={() => onViewModeChange('grid')}
              className={`rounded-lg p-2 ${
                viewMode === 'grid'
                  ? 'bg-cyan-500/10 text-cyan-300'
                  : 'text-slate-500 hover:text-white'
              }`}
            >
              <Grid3X3 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => onViewModeChange('list')}
              className={`rounded-lg p-2 ${
                viewMode === 'list'
                  ? 'bg-cyan-500/10 text-cyan-300'
                  : 'text-slate-500 hover:text-white'
              }`}
            >
              <List className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
