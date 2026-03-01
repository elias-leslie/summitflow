'use client'

import {
  CheckSquare,
  ChevronDown,
  Grid3X3,
  Image,
  List,
  Palette,
  Sparkles,
  X,
} from 'lucide-react'
import { useRef, useState, useEffect } from 'react'

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
  onGenerateAssetClick?: () => void
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
  onGenerateAssetClick,
}: DesignHeaderProps): React.ReactElement {
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [dropdownOpen])

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
        {/* Generate dropdown */}
        {!selectMode && (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="btn-primary flex items-center gap-2"
            >
              <Sparkles className="w-4 h-4" />
              Generate
              <ChevronDown className="w-3 h-3" />
            </button>
            {dropdownOpen && (
              <div className="absolute right-0 mt-2 w-56 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-10 py-1">
                <button
                  onClick={() => {
                    setDropdownOpen(false)
                    onGenerateClick()
                  }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-700 hover:text-white"
                >
                  <Sparkles className="w-4 h-4 text-outrun-400" />
                  Analyze Page Design
                </button>
                <button
                  onClick={() => {
                    setDropdownOpen(false)
                    onGenerateAssetClick?.()
                  }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-700 hover:text-white"
                >
                  <Image className="w-4 h-4 text-phosphor-500" />
                  Generate Game Asset
                </button>
              </div>
            )}
          </div>
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
