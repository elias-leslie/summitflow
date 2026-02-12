'use client'

import { FixPipelineCard } from './FixPipelineCard'
import { NeedsAttentionCard } from './NeedsAttentionCard'
import { useHealthData } from './useHealthData'

interface HealthTabProps {
  projectId: string
}

export function HealthTab({ projectId }: HealthTabProps) {
  const {
    healthLoading,
    unfixedResults,
    metrics,
  } = useHealthData(projectId)

  if (healthLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Right Sidebar */}
      <div className="space-y-4">
        {/* Needs Attention */}
        <NeedsAttentionCard items={unfixedResults?.items ?? []} />

        {/* Fix Pipeline */}
        <FixPipelineCard
          detected={metrics.detected}
          flashFixed={metrics.flashFixed}
          sonnetFixed={metrics.sonnetFixed}
          escalatedCount={metrics.escalatedCount}
          autoFixRate={metrics.autoFixRate}
        />
      </div>
    </div>
  )
}
