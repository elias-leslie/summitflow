'use client'

import {
  CheckSquare,
  Grid3X3,
  List,
  Palette,
  Sparkles,
  X,
} from 'lucide-react'

export type ViewMode = 'grid' | 'list'

interface DesignHeaderProps {
  totalMockups: number | undefined
  viewMode: ViewMode
  selectMode: boolean
  hasMockups: boolean
  onViewModeChange: (mode: ViewMode) => void
  onSelectModeToggle: () => void
  onCancelSelectMode: () => void
  onGenerateClick: () => void
}

export function DesignHeader({
  totalMockups,
  viewMode,
  selectMode,
  hasMockups,
  onViewModeChange,
  onSelectModeToggle,
  onCancelSelectMode,
  onGenerateClick,
}: DesignHeaderProps): React.ReactElement {
  return (
    <div className="flex items-center justify-between mb-6">
      <div className="flex items-center gap-3">
        <Palette className="w-6 h-6 text-outrun-500" />
        <h1 className="display text-xl font-semibold text-white">Design</h1>
        {totalMockups !== undefined && (
          <span className="text-slate-400 text-sm">
            {totalMockups} mockups
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-4">
        {/* Generate button */}
        {!selectMode && (
          <button
            onClick={onGenerateClick}
            className="btn-primary flex items-center gap-2"
          >
            <Sparkles className="w-4 h-4" />
            Generate Mockup
          </button>
        )}

        {/* Select mode toggle */}
        {hasMockups && (
          <button
            onClick={() =>
              selectMode ? onCancelSelectMode() : onSelectModeToggle()
            }
            className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-all ${
              selectMode
                ? 'bg-outrun-500/20 text-outrun-400 border border-outrun-500/50'
                : 'bg-slate-800 text-slate-300 hover:text-white border border-slate-700'
            }`}
          >
            {selectMode ? (
              <X className="w-4 h-4" />
            ) : (
              <CheckSquare className="w-4 h-4" />
            )}
            {selectMode ? 'Cancel' : 'Select'}
          </button>
        )}

        {/* View toggle */}
        {!selectMode && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => onViewModeChange('grid')}
              className={`p-2 rounded ${
                viewMode === 'grid'
                  ? 'bg-outrun-500/20 text-outrun-400'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Grid3X3 className="w-4 h-4" />
            </button>
            <button
              onClick={() => onViewModeChange('list')}
              className={`p-2 rounded ${
                viewMode === 'list'
                  ? 'bg-outrun-500/20 text-outrun-400'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <List className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
