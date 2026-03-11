/**
 * DesignStandardsPanel - Reference panel showing design standards and rules
 *
 * Displays the project's effective design standards organized by category.
 * Features:
 * - Collapsible category sections
 * - Rule requirements with severity indicators
 * - Links page health to compliance status
 */

'use client'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Loader2,
  Palette,
} from 'lucide-react'
import { useState } from 'react'
import { POLL_RARE } from '@/lib/polling'
import { cn } from '@/lib/utils'
import { fetchEffectiveRules } from './api'
import { CategorySection } from './CategorySection'
import type { DesignRule, DesignStandardsPanelProps } from './types'

export function DesignStandardsPanel({
  projectId,
  className,
}: DesignStandardsPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(),
  )

  const {
    data: rules,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['design-rules', projectId],
    queryFn: () => fetchEffectiveRules(projectId),
    staleTime: POLL_RARE,
    refetchOnWindowFocus: false,
  })

  // Group rules by category
  const rulesByCategory = rules?.reduce<Record<string, DesignRule[]>>(
    (acc, rule) => {
      if (!acc[rule.category]) acc[rule.category] = []
      acc[rule.category].push(rule)
      return acc
    },
    {},
  )

  const toggleCategory = (category: string) => {
    const next = new Set(expandedCategories)
    if (next.has(category)) {
      next.delete(category)
    } else {
      next.add(category)
    }
    setExpandedCategories(next)
  }

  const totalRules = rules?.length ?? 0
  const categoryCount = rulesByCategory
    ? Object.keys(rulesByCategory).length
    : 0

  if (error) {
    return (
      <div
        className={cn('border border-red-500/30 bg-red-950/20 p-4', className)}
      >
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          <span>Failed to load design standards</span>
        </div>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'border border-slate-700/50 bg-gradient-to-b from-slate-900/80 to-slate-950/90',
        'font-mono text-sm',
        className,
      )}
    >
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/30 transition-colors border-b border-slate-700/30"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-pink-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <Palette className="w-4 h-4 text-pink-500" />
          <span className="text-pink-400 font-semibold tracking-wide">
            DESIGN STANDARDS
          </span>
          {isLoading && (
            <Loader2 className="w-3 h-3 animate-spin text-slate-500 ml-2" />
          )}
        </div>

        {/* Summary in header */}
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/50 border border-slate-700/30">
            <span className="text-slate-400">{totalRules}</span>
            <span className="text-slate-500">rules</span>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/50 border border-slate-700/30">
            <span className="text-slate-400">{categoryCount}</span>
            <span className="text-slate-500">categories</span>
          </div>
        </div>
      </button>

      {isExpanded && (
        <div className="p-4 space-y-2 max-h-[500px] overflow-y-auto">
          {/* Category sections */}
          {rulesByCategory &&
            Object.entries(rulesByCategory).map(([category, categoryRules]) => (
              <CategorySection
                key={category}
                category={category}
                rules={categoryRules}
                isExpanded={expandedCategories.has(category)}
                onToggle={() => toggleCategory(category)}
              />
            ))}

          {!isLoading && !rulesByCategory && (
            <div className="text-center py-8 text-slate-500">
              <Palette className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No design standards configured</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
