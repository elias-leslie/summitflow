'use client'

import { clsx } from 'clsx'
import {
  Loader2,
  Zap,
} from 'lucide-react'
import type { FeedbackSummary } from '@/lib/api/feedback'

// ============================================================================
// Constants
// ============================================================================

const COMPONENT_LABELS: Record<string, string> = {
  'sf.cli': 'ST CLI',
  'sf.cli.memory': 'Memory CLI',
  'sf.dt': 'Dev Tools',
  'sf.quality': 'Quality Gates',
  'sf.worktree': 'Worktree',
  'sf.api': 'SF API',
  'sf.storage': 'Storage',
  'sf.workflows': 'Workflows',
  'sf.explorer': 'Explorer',
  'sf.frontend': 'Frontend',
  'sf.scripts': 'Scripts',
  'ah.memory': 'AH Memory',
  'ah.memory.tiers': 'Memory Tiers',
  'ah.memory.continuity': 'Continuity',
  'ah.memory.citations': 'Citations',
  'ah.memory.learning': 'Learning',
  'ah.completion': 'Completion',
  'ah.adapters': 'Adapters',
  'ah.sessions': 'Sessions',
  'ah.sdk': 'SDK',
  'ah.orchestration': 'Orchestration',
  'ah.hooks': 'Hooks',
  'xc.tool_registry': 'Tool Registry',
  'xc.error_handling': 'Error Handling',
  'xc.documentation': 'Documentation',
  'xc.testing': 'Testing',
}

// ============================================================================
// Component
// ============================================================================

interface ComponentSummaryProps {
  summary: FeedbackSummary | undefined
  isLoading: boolean
  activeComponent: string | undefined
  onComponentClick: (componentId: string | undefined) => void
}

export function ComponentSummary({
  summary,
  isLoading,
  activeComponent,
  onComponentClick,
}: ComponentSummaryProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
      </div>
    )
  }

  if (!summary || !summary.by_component) {
    return null
  }

  // Only show components with feedback
  const components = Object.entries(summary.by_component)
    .filter(([_, data]) => data.total > 0)
    .sort((a, b) => b[1].open - a[1].open)

  if (components.length === 0) {
    return null
  }

  return (
    <section>
      <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
        Components
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
        {components.map(([componentId, data]) => {
          const isActive = activeComponent === componentId
          const label = COMPONENT_LABELS[componentId] || componentId

          return (
            <button
              key={componentId}
              onClick={() =>
                onComponentClick(isActive ? undefined : componentId)
              }
              className={clsx(
                'p-3 rounded-lg border text-left transition-all duration-150',
                isActive
                  ? 'bg-outrun-500/10 border-outrun-500/30'
                  : 'bg-slate-800/30 border-slate-700/50 hover:border-slate-600',
              )}
            >
              <p className="text-xs font-medium text-slate-300 truncate">
                {label}
              </p>
              <p className="mono text-2xs text-slate-600 mb-2">{componentId}</p>
              <div className="flex items-center gap-3">
                {data.open > 0 && (
                  <span className="flex items-center gap-1 text-2xs text-rose-400">
                    <Zap className="w-2.5 h-2.5" />
                    {data.open}
                  </span>
                )}
                <span className="text-2xs text-slate-500">
                  {data.total} total
                </span>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
