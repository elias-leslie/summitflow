/**
 * DataRow - Expandable row with status border
 *
 * Generic expandable row component that renders custom content
 * and an optional detail panel when expanded.
 */

'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'
import { useCallback } from 'react'
import { cn } from '@/lib/utils'

// Depth-based padding classes for tree indentation
// Maps depth to Tailwind classes (depth * 20 + 12 for row, depth * 20 + 24 for detail)
const depthRowPadding: Record<number, string> = {
  0: 'pl-3', // 12px
  1: 'pl-8', // 32px
  2: 'pl-[52px]',
  3: 'pl-[72px]',
  4: 'pl-[92px]',
  5: 'pl-[112px]',
}

const depthDetailMargin: Record<number, string> = {
  0: 'ml-6', // 24px
  1: 'ml-11', // 44px
  2: 'ml-[64px]',
  3: 'ml-[84px]',
  4: 'ml-[104px]',
  5: 'ml-[124px]',
}

import { StatusBorder } from './StatusIndicator'
import type { HealthStatus } from './types'

interface DataRowProps {
  id: string
  healthStatus: HealthStatus
  isExpanded: boolean
  onToggle: (id: string) => void
  renderContent: () => React.ReactNode
  renderDetail?: () => React.ReactNode
  depth?: number
  hasChildren?: boolean
  className?: string
}

export function DataRow({
  id,
  healthStatus,
  isExpanded,
  onToggle,
  renderContent,
  renderDetail,
  depth = 0,
  hasChildren = false,
  className,
}: DataRowProps) {
  const handleClick = useCallback(() => {
    onToggle(id)
  }, [id, onToggle])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onToggle(id)
      }
    },
    [id, onToggle],
  )

  return (
    <div className={cn('group', className)}>
      {/* Row content */}
      <StatusBorder status={healthStatus}>
        <div
          role="button"
          tabIndex={0}
          onClick={handleClick}
          onKeyDown={handleKeyDown}
          className={cn(
            'flex items-center gap-2 py-2.5',
            'cursor-pointer select-none',
            'transition-colors duration-100',
            'hover:bg-slate-800/40',
            isExpanded && 'bg-slate-800/30',
            depthRowPadding[Math.min(depth, 5)] || depthRowPadding[0],
          )}
        >
          {/* Expand/collapse chevron */}
          {hasChildren || renderDetail ? (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onToggle(id)
              }}
              className={cn(
                'flex-shrink-0 p-0.5 rounded',
                'text-slate-500 hover:text-slate-300',
                'hover:bg-slate-700/50 transition-colors',
              )}
            >
              {isExpanded ? (
                <ChevronDown className="w-4 h-4" />
              ) : (
                <ChevronRight className="w-4 h-4" />
              )}
            </button>
          ) : (
            <span className="w-5" /> // Spacer for alignment
          )}

          {/* Custom content */}
          {renderContent()}
        </div>
      </StatusBorder>

      {/* Expandable detail panel */}
      {renderDetail && (
        <div
          className={cn(
            'grid transition-all duration-200 ease-out',
            isExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]',
          )}
        >
          <div className="overflow-hidden">
            <div
              className={cn(
                'mr-3 mb-2 p-4 rounded-lg',
                'bg-slate-900/50 border border-slate-700/50',
                'animate-in fade-in-0 slide-in-from-top-1 duration-200',
                depthDetailMargin[Math.min(depth, 5)] || depthDetailMargin[0],
              )}
            >
              {renderDetail()}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * DataRowSkeleton - Loading placeholder
 */
// Deterministic widths to avoid hydration mismatch (no Math.random())
const SKELETON_WIDTHS = [180, 220, 160, 200, 190]

export function DataRowSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-1 p-2">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3 px-3 py-3 animate-pulse"
          style={{ animationDelay: `${i * 50}ms` }}
        >
          <div className="w-4 h-4 rounded bg-slate-800" />
          <div className="w-4 h-4 rounded bg-slate-800" />
          <div
            className="h-4 rounded bg-slate-800"
            style={{
              width: `${SKELETON_WIDTHS[i % SKELETON_WIDTHS.length]}px`,
            }}
          />
          <div className="flex-1" />
          <div className="w-16 h-4 rounded bg-slate-800" />
          <div className="w-12 h-4 rounded bg-slate-800" />
        </div>
      ))}
    </div>
  )
}
