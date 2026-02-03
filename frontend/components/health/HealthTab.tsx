'use client'

import { ActivityFeed } from './ActivityFeed'
import { FixPipelineCard } from './FixPipelineCard'
import { HealthSummaryBar } from './HealthSummaryBar'
import { NeedsAttentionCard } from './NeedsAttentionCard'
import { QuickLinksCard } from './QuickLinksCard'
import { useHealthData } from './useHealthData'

interface HealthTabProps {
  projectId: string
}

export function HealthTab({ projectId }: HealthTabProps) {
  const {
    health,
    healthLoading,
    recentResults,
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
      {/* Health Summary Bar */}
      <HealthSummaryBar
        health={health}
        fixedToday={metrics.fixedToday}
        inProgress={metrics.inProgress}
        escalated={metrics.escalated}
        autoFixRate={metrics.autoFixRate}
      />

      {/* Two Column Layout */}
      <div className="grid grid-cols-3 gap-6">
        {/* Activity Feed (2 cols) */}
        <ActivityFeed
          projectId={projectId}
          items={recentResults?.items ?? []}
        />

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

          {/* Quick Links */}
          <QuickLinksCard projectId={projectId} />
        </div>
      </div>
    </div>
  )
}
