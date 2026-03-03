'use client'

import { Skeleton } from '@/components/ui/skeleton'
import { AutonomousStatusBar } from './AutonomousStatusBar'
import { FixPipelineCard } from './FixPipelineCard'
import { InfraStatusBar } from './InfraStatusBar'
import { NeedsAttentionCard } from './NeedsAttentionCard'
import { PipelineHealthDashboard } from './PipelineHealthDashboard'
import { QualityGateStatus } from './QualityGateStatus'
import { RecentActivityCard } from './RecentActivityCard'
import { useHealthData } from './useHealthData'
import { usePipelineData } from './usePipelineData'

interface HealthTabProps {
  projectId: string
}

export function HealthTab({ projectId }: HealthTabProps) {
  const {
    health,
    healthLoading,
    unfixedResults,
    metrics,
  } = useHealthData(projectId)

  const { pipelineData, pipelineLoading } = usePipelineData(projectId)

  if (healthLoading && pipelineLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Infrastructure Status Bar — system + DB/Redis health */}
      <InfraStatusBar />

      {/* Autonomous Execution Status Bar */}
      {pipelineLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : pipelineData ? (
        <AutonomousStatusBar autonomous={pipelineData.autonomous} />
      ) : null}

      {/* Quality Gate Status — per-check pass/fail badges */}
      <QualityGateStatus checks={health?.checks} />

      {/* Pipeline Health Dashboard */}
      {pipelineLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-64 w-full" />
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        </div>
      ) : pipelineData ? (
        <PipelineHealthDashboard data={pipelineData} />
      ) : null}

      {/* Quality Health Section */}
      <div className="grid grid-cols-2 gap-4">
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

      {/* Recent Activity */}
      <RecentActivityCard projectId={projectId} />
    </div>
  )
}
